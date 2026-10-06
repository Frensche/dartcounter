"""
Turnier-Logik für den Dartcounter (ohne tkinter, daher auch headless testbar).

- Tournament:        KO-Turnierbaum (Single Elimination, mit Freilosen)
- TournamentServer:  kleiner HTTP/JSON-Server, über den sich die Stationen
                     (die Dartcounter-Rechner) Matches holen und Ergebnisse melden
- TournamentClient:  Gegenstück auf den Stations-Rechnern
"""

import copy
import json
import os
import random
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

BYE = "BYE"
DEFAULT_PORT = 8765
DISCOVERY_PORT = 8766            # UDP: Stationen finden den Turnierleiter automatisch
DISCOVERY_MAGIC = b"DARTCOUNTER_DISCOVER_V1"
MIN_START_SCORE = 2
MAX_HANDICAP = 500
MIN_PLAYERS = 2
MAX_PLAYERS = 64
ONLINE_SECONDS = 8  # Station gilt als "online", wenn sie sich in dieser Zeit gemeldet hat

TOURNAMENT_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "dartcounter", "tournament.json"
)


class TournamentError(Exception):
    pass


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def seed_order(size):
    """Standard-Setzreihenfolge, z.B. size=8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [x for s in order for x in (s, total - s)]
    return order


def round_name(rnd, rounds):
    left = rounds - rnd  # 1 = Finale
    return {1: "Finale", 2: "Halbfinale", 3: "Viertelfinale", 4: "Achtelfinale"}.get(
        left, f"Runde {rnd + 1}"
    )


def local_ip():
    """Beste Schätzung der LAN-IP dieses Rechners (sendet nichts)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def start_scores(base, handicaps):
    """Startwerte mit Handicap.

    Die Vorgabe ist die Zahl der Punkte, die ein Spieler weniger braucht. Sie wird relativ zum
    Spieler mit der kleinsten Vorgabe vom Startwert abgezogen: Bei 501 und Vorgaben 0 / 100
    starten die beiden mit 501 bzw. 401.
    """
    low = min(handicaps)
    return [base - (h - low) for h in handicaps]


def check_start_scores(base, handicaps):
    if any(sc < MIN_START_SCORE for sc in start_scores(base, handicaps)):
        raise TournamentError(
            f"Die Vorgaben sind zu groß: Ein Spieler würde mit weniger als {MIN_START_SCORE} Punkten starten "
            f"(Startpunktzahl {base}, größter Unterschied {max(handicaps) - min(handicaps)}).")


def parse_players(lines):
    """Zeilen wie 'Anna' oder 'Anna;100' -> (Namen, {Name: Vorgabe})."""
    names, handicaps = [], {}
    for line in lines:
        if not line or not line.strip():
            continue
        name, sep, rest = line.partition(";")
        name = name.strip()
        hc = 0
        if sep and rest.strip():
            try:
                hc = int(rest.strip())
            except ValueError:
                raise TournamentError(f"Ungültige Vorgabe bei '{name}': '{rest.strip()}' (bitte eine ganze Zahl).")
            if not (0 <= hc <= MAX_HANDICAP):
                raise TournamentError(f"Die Vorgabe bei '{name}' muss zwischen 0 und {MAX_HANDICAP} liegen.")
        names.append(name)
        handicaps[name] = hc
    return names, handicaps


def clean_players(players):
    names = [p.strip() for p in players if p and p.strip()]
    if not (MIN_PLAYERS <= len(names) <= MAX_PLAYERS):
        raise TournamentError(
            f"Ein Turnier braucht {MIN_PLAYERS} bis {MAX_PLAYERS} Spieler (aktuell {len(names)})."
        )
    if any(n.upper() == BYE for n in names):
        raise TournamentError(f"'{BYE}' ist als Spielername nicht erlaubt.")
    seen = set()
    for n in names:
        if n.casefold() in seen:
            raise TournamentError(f"Der Name '{n}' kommt mehrfach vor - Namen müssen eindeutig sein.")
        seen.add(n.casefold())
    return names


# --------------------------------------------------------------------------
# Turnier
# --------------------------------------------------------------------------

GROUP_NAMES = "ABCDEFGHIJKLMNOP"
MAX_GROUPS = len(GROUP_NAMES)
MODE_KO = "ko"
MODE_GROUPS = "groups_ko"


def _round_robin(names):
    """Jeder gegen jeden (Kreismethode); liefert pro Spieltag eine Liste von Paarungen."""
    players = list(names)
    if len(players) % 2:
        players.append(None)
    n = len(players)
    rounds = []
    for _ in range(n - 1):
        pairs = [(players[i], players[n - 1 - i]) for i in range(n // 2)]
        rounds.append([(a, b) for a, b in pairs if a is not None and b is not None])
        players = [players[0]] + [players[-1]] + players[1:-1]
    return rounds


class Tournament:
    def __init__(self, name, players, start_score=501, double_out=True,
                 legs_to_win=2, final_legs_to_win=3, stations=6, shuffle=True,
                 mode=MODE_KO, groups=0, advance=2, group_legs_to_win=2, handicaps=None):
        names = clean_players(players)
        handicaps = {n: int((handicaps or {}).get(n, 0)) for n in names}
        check_start_scores(int(start_score), list(handicaps.values()))
        if mode not in (MODE_KO, MODE_GROUPS):
            raise TournamentError("Unbekannter Turniermodus.")
        if mode == MODE_GROUPS:
            if not (1 <= groups <= MAX_GROUPS):
                raise TournamentError(f"Die Anzahl der Gruppen muss zwischen 1 und {MAX_GROUPS} liegen.")
            if len(names) < 2 * groups:
                raise TournamentError(
                    f"Für {groups} Gruppen werden mindestens {2 * groups} Spieler benötigt "
                    f"(jede Gruppe braucht mindestens 2).")
            min_size = len(names) // groups
            if not (1 <= advance <= min_size):
                raise TournamentError(
                    f"Pro Gruppe können 1 bis {min_size} Spieler in die KO-Runde kommen.")
            if groups * advance < 2:
                raise TournamentError("Für die KO-Runde müssen mindestens 2 Spieler weiterkommen.")
        if shuffle:
            names = random.sample(names, len(names))

        self.name = name.strip() or "Dart-Turnier"
        self.start_score = int(start_score)
        self.double_out = bool(double_out)
        self.legs_to_win = max(1, int(legs_to_win))
        self.final_legs_to_win = max(1, int(final_legs_to_win))
        self.group_legs_to_win = max(1, int(group_legs_to_win))
        self.stations = max(1, int(stations))
        self.players = names
        self.handicaps = handicaps
        self.mode = mode
        self.group_count = int(groups) if mode == MODE_GROUPS else 0
        self.advance = int(advance) if mode == MODE_GROUPS else 0
        self._init_runtime()
        self._build()

    def _init_runtime(self):
        self.lock = threading.RLock()
        self.version = 0
        self.seen = {}          # station -> letzter Kontakt (time.time())
        self.on_change = None   # Callback ohne Argumente, z.B. zum Speichern

    # ---------------- Aufbau ----------------

    def _new_match(self, mid, stage, **extra):
        m = {
            "id": mid,
            "stage": stage,        # "group" oder "ko"
            "group": None,         # Gruppenindex (nur Gruppenspiele)
            "round": None,         # KO-Runde (nur KO)
            "index": None,
            "p": [None, None],
            "winner": None,
            "legs": None,
            "avg": None,
            "station": None,       # läuft gerade an dieser Station
            "done_station": None,  # wurde an dieser Station gespielt
            "walkover": False,
        }
        m.update(extra)
        return m

    def _build(self):
        self.matches = []
        self.groups = []
        if self.mode == MODE_GROUPS:
            g = self.group_count
            self.groups = [[] for _ in range(g)]
            for idx, name in enumerate(self.players):      # Schlangenverteilung
                row, col = divmod(idx, g)
                self.groups[col if row % 2 == 0 else g - 1 - col].append(name)
            schedule = []
            for gi, members in enumerate(self.groups):
                for day, pairs in enumerate(_round_robin(members)):
                    for a, b in pairs:
                        schedule.append((day, gi, a, b))
            schedule.sort(key=lambda x: (x[0], x[1]))
            counters = {}
            for day, gi, a, b in schedule:
                k = counters.get(gi, 0)
                counters[gi] = k + 1
                self.matches.append(self._new_match(f"g{gi}m{k}", "group", group=gi, index=k, round=day, p=[a, b]))
            n_ko = self.group_count * self.advance
        else:
            n_ko = len(self.players)
        self._build_ko(n_ko)

    def _build_ko(self, n):
        size = 1
        while size < n:
            size *= 2
        self.ko_size = size
        self.ko_players = n
        self.rounds = size.bit_length() - 1
        order = seed_order(size)
        for r in range(self.rounds):
            for i in range(size >> (r + 1)):
                m = self._new_match(f"r{r}m{i}", "ko", round=r, index=i)
                if r == 0:
                    m["seeds"] = [order[2 * i], order[2 * i + 1]]
                    m["p"] = [BYE if sd > n else None for sd in m["seeds"]]
                self.matches.append(m)
        self.ko_filled = False
        if self.mode == MODE_KO:
            self._place_ko([self.players[sd - 1] if sd <= n else BYE for sd in order])

    def _place_ko(self, slots):
        for i in range(self.ko_size // 2):
            self.match_at(0, i)["p"] = [slots[2 * i], slots[2 * i + 1]]
        for m in self.ko_matches():
            if m["round"] == 0 and BYE in m["p"]:
                m["winner"] = m["p"][0] if m["p"][1] == BYE else m["p"][1]
                m["walkover"] = True
                self._advance(m)
        self.ko_filled = True

    # ---------------- Zugriff ----------------

    def ko_matches(self):
        return [m for m in self.matches if m["stage"] == "ko"]

    def group_matches(self, gi=None):
        return [m for m in self.matches
                if m["stage"] == "group" and (gi is None or m["group"] == gi)]

    def match_at(self, rnd, idx):
        for m in self.matches:
            if m["stage"] == "ko" and m["round"] == rnd and m["index"] == idx:
                return m
        return None

    def get_match(self, match_id):
        for m in self.matches:
            if m["id"] == match_id:
                return m
        raise TournamentError(f"Unbekanntes Match '{match_id}'.")

    def _next(self, m):
        if m["stage"] != "ko" or m["round"] >= self.rounds - 1:
            return None
        return self.match_at(m["round"] + 1, m["index"] // 2)

    def _status(self, m):
        if m["winner"]:
            return "done"
        if m["station"]:
            return "running"
        if all(p and p != BYE for p in m["p"]):
            return "ready"
        return "waiting"

    def legs_needed(self, m):
        if m["stage"] == "group":
            return self.group_legs_to_win
        return self.final_legs_to_win if m["round"] == self.rounds - 1 else self.legs_to_win

    def label(self, m):
        if m["stage"] == "group":
            return f"Gruppe {GROUP_NAMES[m['group']]} - Spieltag {m['round'] + 1}"
        name = round_name(m["round"], self.rounds)
        if m["round"] == self.rounds - 1:
            return name
        return f"{name} - Match {m['index'] + 1}"

    def champion(self):
        final = self.match_at(self.rounds - 1, 0)
        return final["winner"] if final else None

    def groups_done(self):
        gm = self.group_matches()
        return bool(gm) and all(m["winner"] for m in gm)

    def stage(self):
        if self.champion():
            return "done"
        if self.mode == MODE_GROUPS and not self.ko_filled:
            return "groups"
        return "ko"

    def _changed(self):
        self.version += 1
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _advance(self, m):
        nxt = self._next(m)
        if nxt:
            nxt["p"][m["index"] % 2] = m["winner"]

    def _unadvance(self, m):
        nxt = self._next(m)
        if nxt:
            if nxt["winner"] or nxt["station"]:
                raise TournamentError(
                    "Das Folge-Match läuft bereits oder ist beendet - das Ergebnis lässt sich nicht mehr ändern."
                )
            nxt["p"][m["index"] % 2] = None

    # ---------------- Gruppenphase ----------------

    def group_table(self, gi):
        """Tabelle einer Gruppe: Punkte (Sieg = 2), Leg-Differenz, gewonnene Legs, direkter Vergleich."""
        rows = {n: {"name": n, "played": 0, "wins": 0, "losses": 0,
                    "legs_for": 0, "legs_against": 0, "points": 0} for n in self.groups[gi]}
        h2h = {}
        for m in self.group_matches(gi):
            if not m["winner"]:
                continue
            a, b = m["p"]
            win = m["winner"]
            lose = b if win == a else a
            la, lb = m["legs"] if m["legs"] else ((1, 0) if win == a else (0, 1))
            rows[a]["legs_for"] += la
            rows[a]["legs_against"] += lb
            rows[b]["legs_for"] += lb
            rows[b]["legs_against"] += la
            rows[win]["wins"] += 1
            rows[win]["points"] += 2
            rows[lose]["losses"] += 1
            for n in (a, b):
                rows[n]["played"] += 1
            h2h[frozenset((a, b))] = win

        def key(r):
            return (-r["points"], -(r["legs_for"] - r["legs_against"]), -r["legs_for"], r["name"].casefold())

        table = sorted(rows.values(), key=key)
        # Direkter Vergleich bei genau zwei punkt- und legsgleichen Spielern
        i = 0
        while i < len(table) - 1:
            if key(table[i])[:3] == key(table[i + 1])[:3] and (
                    i + 2 >= len(table) or key(table[i + 2])[:3] != key(table[i])[:3]):
                w = h2h.get(frozenset((table[i]["name"], table[i + 1]["name"])))
                if w == table[i + 1]["name"]:
                    table[i], table[i + 1] = table[i + 1], table[i]
                i += 2
            else:
                i += 1
        for pos, r in enumerate(table, start=1):
            r["rank"] = pos
        return table

    def _unfill_ko(self):
        """Nimmt die Auslosung der KO-Runde zurück (nur solange dort noch nichts gespielt wurde)."""
        if not self.ko_filled or self.mode != MODE_GROUPS:
            return
        for m in self.ko_matches():
            if (m["winner"] and not m["walkover"]) or m["station"]:
                raise TournamentError(
                    "Die KO-Runde hat bereits begonnen - Gruppenergebnisse lassen sich nicht mehr ändern.")
        for m in self.ko_matches():
            m["winner"] = m["legs"] = m["avg"] = m["done_station"] = None
            m["walkover"] = False
            if m["round"] == 0:
                m["p"] = [BYE if sd > self.ko_players else None for sd in m["seeds"]]
            else:
                m["p"] = [None, None]
        self.ko_filled = False

    def _after_group_change(self):
        if self.mode == MODE_GROUPS and not self.ko_filled and self.groups_done():
            self._fill_ko_from_groups()

    def _fill_ko_from_groups(self):
        tables = [self.group_table(gi) for gi in range(self.group_count)]
        group_of = {n: gi for gi, members in enumerate(self.groups) for n in members}
        place_of = {}
        seeds = []
        for place in range(self.advance):
            level = [(gi, tables[gi][place]) for gi in range(self.group_count)]
            level.sort(key=lambda x: (-x[1]["points"], -(x[1]["legs_for"] - x[1]["legs_against"]),
                                      -x[1]["legs_for"], x[0]))
            for gi, row in level:
                seeds.append(row["name"])
                place_of[row["name"]] = place
        n = len(seeds)
        slots = [seeds[sd - 1] if sd <= n else BYE for sd in seed_order(self.ko_size)]
        self._avoid_clashes(slots, group_of, place_of)
        self._place_ko(slots)

    @staticmethod
    def _avoid_clashes(slots, group_of, place_of):
        """Tauscht Spieler gleicher Platzierung, damit in Runde 1 möglichst keine Gruppenkollegen aufeinandertreffen."""
        pairs = len(slots) // 2
        for p in range(pairs):
            a, b = slots[2 * p], slots[2 * p + 1]
            if BYE in (a, b) or group_of[a] != group_of[b]:
                continue
            done = False
            for q in range(pairs):
                if q == p or done:
                    continue
                for pos in (0, 1):
                    z, w = slots[2 * q + pos], slots[2 * q + 1 - pos]
                    if z == BYE or place_of[z] != place_of[b] or group_of[z] == group_of[a]:
                        continue
                    if w != BYE and group_of[w] == group_of[b]:
                        continue
                    slots[2 * p + 1], slots[2 * q + pos] = z, b
                    done = True
                    break

    # ---------------- Aktionen der Stationen ----------------

    def touch(self, station):
        with self.lock:
            self.seen[station] = time.time()

    def _check_station(self, station):
        if not (1 <= station <= self.stations):
            raise TournamentError(f"Station {station} gibt es nicht (1-{self.stations}).")

    def _busy_player(self, m):
        """Name eines Spielers dieses Matches, der gerade an einem anderen Match spielt (sonst None)."""
        for other in self.matches:
            if other is m or not other["station"] or other["winner"]:
                continue
            for name in m["p"]:
                if name and name != BYE and name in other["p"]:
                    return name, other["station"]
        return None

    def match_starts(self, m):
        """Startwerte der beiden Spieler (mit Handicap) oder None, solange das Match nicht feststeht."""
        if not all(p and p != BYE for p in m["p"]):
            return None
        return start_scores(self.start_score, [self.handicaps.get(p, 0) for p in m["p"]])

    def match_info(self, m):
        return {
            "match_id": m["id"],
            "label": self.label(m),
            "players": list(m["p"]),
            "starts": self.match_starts(m),
            "start_score": self.start_score,
            "double_out": self.double_out,
            "legs_to_win": self.legs_needed(m),
        }

    def claim(self, match_id, station):
        with self.lock:
            self._check_station(station)
            m = self.get_match(match_id)
            if m["winner"]:
                raise TournamentError("Dieses Match ist bereits beendet.")
            if m["station"] == station:
                return self.match_info(m)  # erneutes Abholen (z.B. nach Absturz) ist ok
            if m["station"]:
                raise TournamentError(f"Dieses Match läuft schon an Station {m['station']}.")
            if self._status(m) != "ready":
                raise TournamentError("Dieses Match ist noch nicht spielbereit.")
            busy = self._busy_player(m)
            if busy:
                raise TournamentError(f"{busy[0]} spielt gerade an Station {busy[1]}.")
            for other in self.matches:
                if other["station"] == station and not other["winner"]:
                    raise TournamentError(
                        f"Station {station} spielt bereits ein anderes Match ({self.label(other)})."
                    )
            m["station"] = station
            self._changed()
            return self.match_info(m)

    def release(self, match_id, station=None):
        with self.lock:
            m = self.get_match(match_id)
            if not m["station"]:
                return
            if station is not None and m["station"] != station:
                raise TournamentError(f"Das Match läuft an Station {m['station']}.")
            m["station"] = None
            self._changed()

    def report(self, match_id, station, winner, legs, avg=None):
        with self.lock:
            m = self.get_match(match_id)
            if m["winner"]:
                raise TournamentError("Für dieses Match wurde schon ein Ergebnis eingetragen.")
            if m["station"] != station:
                raise TournamentError("Dieses Match ist dieser Station nicht zugewiesen.")
            self._finish(m, winner, legs, avg)
            m["done_station"] = station
            self._after_group_change()
            self._changed()

    # ---------------- Aktionen des Turnierleiters ----------------

    def _finish(self, m, winner, legs, avg):
        if winner not in m["p"] or winner == BYE:
            raise TournamentError("Der Sieger muss einer der beiden Spieler des Matches sein.")
        m["winner"] = winner
        m["legs"] = [int(x) for x in legs] if legs else None
        m["avg"] = [round(float(x), 2) for x in avg] if avg else None
        m["station"] = None
        self._advance(m)

    def set_result(self, match_id, winner, legs=None):
        """Ergebnis manuell eintragen oder ein bestehendes korrigieren."""
        with self.lock:
            m = self.get_match(match_id)
            if m["walkover"]:
                raise TournamentError("Freilos-Matches können nicht geändert werden.")
            if self._status(m) == "waiting":
                raise TournamentError("Das Match hat noch nicht beide Spieler.")
            if winner not in m["p"] or winner == BYE:
                raise TournamentError("Der Sieger muss einer der beiden Spieler des Matches sein.")
            if m["stage"] == "group":
                self._unfill_ko()
            if m["winner"]:
                self._unadvance(m)
                m["winner"] = None
            self._finish(m, winner, legs, None)
            if m["stage"] == "group":
                self._after_group_change()
            self._changed()

    def reset_result(self, match_id):
        with self.lock:
            m = self.get_match(match_id)
            if m["walkover"]:
                raise TournamentError("Freilos-Matches können nicht zurückgesetzt werden.")
            if not m["winner"]:
                raise TournamentError("Für dieses Match gibt es kein Ergebnis.")
            if m["stage"] == "group":
                self._unfill_ko()
            self._unadvance(m)
            m["winner"] = m["legs"] = m["avg"] = m["done_station"] = None
            self._changed()

    # ---------------- Snapshot / Speichern ----------------

    def snapshot(self):
        with self.lock:
            now = time.time()
            matches = []
            for m in self.matches:
                c = copy.deepcopy(m)
                c["status"] = self._status(m)
                c["legs_to_win"] = self.legs_needed(m)
                c["label"] = self.label(m)
                c["starts"] = self.match_starts(m)
                busy = self._busy_player(m) if c["status"] == "ready" else None
                c["busy"] = f"{busy[0]} (Station {busy[1]})" if busy else None
                matches.append(c)
            groups = []
            for gi, members in enumerate(self.groups):
                gm = self.group_matches(gi)
                groups.append({
                    "name": GROUP_NAMES[gi],
                    "players": list(members),
                    "table": self.group_table(gi),
                    "done": all(m["winner"] for m in gm),
                })
            return {
                "name": self.name,
                "mode": self.mode,
                "stage": self.stage(),
                "start_score": self.start_score,
                "double_out": self.double_out,
                "stations": self.stations,
                "advance": self.advance,
                "groups": groups,
                "ko_filled": self.ko_filled,
                "handicaps": dict(self.handicaps),
                "rounds": self.rounds,
                "round_names": [round_name(r, self.rounds) for r in range(self.rounds)],
                "champion": self.champion(),
                "version": self.version,
                "matches": matches,
                "seen_ago": {s: now - t for s, t in self.seen.items()},
            }

    def to_dict(self):
        with self.lock:
            return {
                "name": self.name,
                "mode": self.mode,
                "start_score": self.start_score,
                "double_out": self.double_out,
                "legs_to_win": self.legs_to_win,
                "final_legs_to_win": self.final_legs_to_win,
                "group_legs_to_win": self.group_legs_to_win,
                "group_count": self.group_count,
                "advance": self.advance,
                "stations": self.stations,
                "players": self.players,
                "handicaps": self.handicaps,
                "groups": self.groups,
                "rounds": self.rounds,
                "ko_size": self.ko_size,
                "ko_players": self.ko_players,
                "ko_filled": self.ko_filled,
                "matches": copy.deepcopy(self.matches),
            }

    @classmethod
    def from_dict(cls, d):
        t = cls.__new__(cls)
        t.name = d["name"]
        t.mode = d.get("mode", MODE_KO)
        t.start_score = d["start_score"]
        t.double_out = d["double_out"]
        t.legs_to_win = d["legs_to_win"]
        t.final_legs_to_win = d["final_legs_to_win"]
        t.group_legs_to_win = d.get("group_legs_to_win", d["legs_to_win"])
        t.group_count = d.get("group_count", 0)
        t.advance = d.get("advance", 0)
        t.stations = d["stations"]
        t.players = d["players"]
        t.handicaps = d.get("handicaps") or {n: 0 for n in t.players}
        t.groups = d.get("groups", [])
        t.rounds = d["rounds"]
        t.ko_size = d.get("ko_size", 1 << d["rounds"])
        t.ko_players = d.get("ko_players", len(t.players))
        t.ko_filled = d.get("ko_filled", True)
        t.matches = d["matches"]
        for m in t.matches:  # ältere Speicherstände kannten noch keine Gruppen
            m.setdefault("stage", "ko")
            m.setdefault("group", None)
        t._init_runtime()
        return t

    def save(self, path=TOURNAMENT_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path=TOURNAMENT_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (OSError, ValueError, KeyError) as e:
            raise TournamentError(f"Turnier konnte nicht geladen werden: {e}")


# --------------------------------------------------------------------------
# HTTP-Server (läuft im Hintergrund-Thread des Turnierleiter-Rechners)
# --------------------------------------------------------------------------

def _make_handler(t):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/ping":
                return self._send(200, {"dartcounter": 1, "name": t.name, "stations": t.stations})
            if url.path != "/api/state":
                return self._send(404, {"error": "not found"})
            station = parse_qs(url.query).get("station")
            if station:
                try:
                    t.touch(int(station[0]))
                except ValueError:
                    pass
            self._send(200, t.snapshot())

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 65536:
                return self._send(413, {"error": "Anfrage zu groß"})
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                path = urlparse(self.path).path
                if path == "/api/claim":
                    info = t.claim(data["match_id"], int(data["station"]))
                    t.touch(int(data["station"]))
                    return self._send(200, {"ok": True, "match": info})
                if path == "/api/release":
                    t.release(data["match_id"], int(data["station"]))
                    return self._send(200, {"ok": True})
                if path == "/api/result":
                    t.report(data["match_id"], int(data["station"]), data["winner"],
                             data["legs"], data.get("avg"))
                    return self._send(200, {"ok": True})
                return self._send(404, {"error": "not found"})
            except TournamentError as e:
                self._send(409, {"error": str(e)})
            except (ValueError, KeyError, TypeError):
                self._send(400, {"error": "Ungültige Anfrage"})

    return Handler


class TournamentServer:
    def __init__(self, tournament, port=DEFAULT_PORT, host="0.0.0.0"):
        self.tournament = tournament
        self.port = port
        self._httpd = ThreadingHTTPServer((host, port), _make_handler(tournament))
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._stop_discovery = threading.Event()
        self._udp = None

    def start(self):
        self._thread.start()
        self._start_discovery()

    def _start_discovery(self):
        """Beantwortet UDP-Suchanfragen der Stationen (optional - ohne klappt die manuelle Eingabe weiter)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(0.5)
        except OSError:
            return
        self._udp = sock
        threading.Thread(target=self._discovery_loop, daemon=True).start()

    def _discovery_loop(self):
        t = self.tournament
        while not self._stop_discovery.is_set():
            try:
                data, addr = self._udp.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                return
            if data == DISCOVERY_MAGIC:
                reply = json.dumps({"dartcounter": 1, "name": t.name, "port": self.port,
                                    "stations": t.stations}).encode("utf-8")
                try:
                    self._udp.sendto(reply, addr)
                except OSError:
                    pass

    def stop(self):
        self._stop_discovery.set()
        if self._udp:
            self._udp.close()
        self._httpd.shutdown()
        self._httpd.server_close()


# --------------------------------------------------------------------------
# Automatische Suche nach dem Turnierleiter
# --------------------------------------------------------------------------

def _probe_http(host, port, timeout=0.5):
    try:
        with urlrequest.urlopen(f"http://{host}:{port}/api/ping", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("dartcounter"):
            return {"host": host, "port": port, "name": data.get("name", ""), "stations": data.get("stations")}
    except (urlerror.URLError, OSError, ValueError):
        pass
    return None


def _udp_search(hosts, wait=0.8):
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        for h in hosts:
            try:
                sock.sendto(DISCOVERY_MAGIC, (h, DISCOVERY_PORT))
            except OSError:
                pass
        end = time.time() + wait
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(1024)
                info = json.loads(data.decode("utf-8"))
                if info.get("dartcounter"):
                    found.append({"host": addr[0], "port": int(info["port"]),
                                  "name": info.get("name", ""), "stations": info.get("stations")})
            except socket.timeout:
                continue
            except (OSError, ValueError, KeyError):
                continue
    finally:
        sock.close()
    return found


def discover(ports=(DEFAULT_PORT,), udp_wait=0.8):
    """Sucht Turnier-Server im lokalen Netz.

    1. UDP-Broadcast (findet den Server auch bei abweichendem Port)
    2. Zusätzlich Scan des lokalen /24-Netzes (und dieses Rechners) auf den angegebenen TCP-Ports -
       klappt auch dort, wo Broadcasts gefiltert werden.
    Liefert eine Liste von {host, port, name, stations}.
    """
    ip = local_ip()
    targets = ["127.0.0.1"]
    broadcast = ["255.255.255.255", "127.0.0.1"]
    if not ip.startswith("127."):
        prefix = ip.rsplit(".", 1)[0]
        targets += [f"{prefix}.{i}" for i in range(1, 255)]
        broadcast.append(f"{prefix}.255")

    results = {(r["host"], r["port"]): r for r in _udp_search(broadcast, udp_wait)}
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = [pool.submit(_probe_http, h, p) for h in targets for p in ports]
        for f in futures:
            r = f.result()
            if r:
                results.setdefault((r["host"], r["port"]), r)
    # Eigener Rechner: lieber die echte LAN-Adresse als 127.0.0.1 anzeigen, wenn beides gefunden wurde
    for (host, port) in list(results):
        if host == "127.0.0.1" and (ip, port) in results:
            del results[(host, port)]
    return sorted(results.values(), key=lambda r: (r["host"], r["port"]))


# --------------------------------------------------------------------------
# Client (Station)
# --------------------------------------------------------------------------

class TournamentClient:
    def __init__(self, host, port, station, timeout=3):
        self.base = f"http://{host}:{int(port)}"
        self.station = int(station)
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urlrequest.Request(self.base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", str(e))
            except (ValueError, OSError):
                msg = str(e)
            raise TournamentError(msg)
        except (urlerror.URLError, OSError, ValueError) as e:
            raise TournamentError(f"Turnier-Server nicht erreichbar ({e})")

    def state(self):
        return self._call("GET", f"/api/state?station={self.station}")

    def claim(self, match_id):
        return self._call("POST", "/api/claim",
                          {"match_id": match_id, "station": self.station})["match"]

    def release(self, match_id):
        self._call("POST", "/api/release", {"match_id": match_id, "station": self.station})

    def report(self, match_id, winner, legs, avg):
        self._call("POST", "/api/result", {
            "match_id": match_id, "station": self.station,
            "winner": winner, "legs": legs, "avg": avg,
        })
