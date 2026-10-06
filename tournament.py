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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

BYE = "BYE"
DEFAULT_PORT = 8765
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

class Tournament:
    def __init__(self, name, players, start_score=501, double_out=True,
                 legs_to_win=2, final_legs_to_win=3, stations=6, shuffle=True):
        names = clean_players(players)
        if shuffle:
            names = random.sample(names, len(names))

        self.name = name.strip() or "Dart-Turnier"
        self.start_score = int(start_score)
        self.double_out = bool(double_out)
        self.legs_to_win = max(1, int(legs_to_win))
        self.final_legs_to_win = max(1, int(final_legs_to_win))
        self.stations = max(1, int(stations))
        self.players = names
        self._init_runtime()
        self._build()

    def _init_runtime(self):
        self.lock = threading.RLock()
        self.version = 0
        self.seen = {}          # station -> letzter Kontakt (time.time())
        self.on_change = None   # Callback ohne Argumente, z.B. zum Speichern

    # ---------------- Aufbau ----------------

    def _build(self):
        n = len(self.players)
        size = 1
        while size < n:
            size *= 2
        self.rounds = size.bit_length() - 1

        self.matches = []
        for r in range(self.rounds):
            for i in range(size >> (r + 1)):
                self.matches.append({
                    "id": f"r{r}m{i}",
                    "round": r,
                    "index": i,
                    "p": [None, None],
                    "winner": None,
                    "legs": None,
                    "avg": None,
                    "station": None,       # läuft gerade an dieser Station
                    "done_station": None,  # wurde an dieser Station gespielt
                    "walkover": False,
                })

        slots = [self.players[s - 1] if s <= n else BYE for s in seed_order(size)]
        for i in range(size // 2):
            self.match_at(0, i)["p"] = [slots[2 * i], slots[2 * i + 1]]

        for m in self.matches:
            if m["round"] == 0 and BYE in m["p"]:
                m["winner"] = m["p"][0] if m["p"][1] == BYE else m["p"][1]
                m["walkover"] = True
                self._advance(m)

    # ---------------- Zugriff ----------------

    def match_at(self, rnd, idx):
        for m in self.matches:
            if m["round"] == rnd and m["index"] == idx:
                return m
        return None

    def get_match(self, match_id):
        for m in self.matches:
            if m["id"] == match_id:
                return m
        raise TournamentError(f"Unbekanntes Match '{match_id}'.")

    def _next(self, m):
        if m["round"] >= self.rounds - 1:
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
        return self.final_legs_to_win if m["round"] == self.rounds - 1 else self.legs_to_win

    def label(self, m):
        name = round_name(m["round"], self.rounds)
        if m["round"] == self.rounds - 1:
            return name
        return f"{name} - Match {m['index'] + 1}"

    def champion(self):
        final = self.match_at(self.rounds - 1, 0)
        return final["winner"] if final else None

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

    # ---------------- Aktionen der Stationen ----------------

    def touch(self, station):
        with self.lock:
            self.seen[station] = time.time()

    def _check_station(self, station):
        if not (1 <= station <= self.stations):
            raise TournamentError(f"Station {station} gibt es nicht (1-{self.stations}).")

    def match_info(self, m):
        return {
            "match_id": m["id"],
            "label": self.label(m),
            "players": list(m["p"]),
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
            if m["winner"]:
                self._unadvance(m)
                m["winner"] = None
            self._finish(m, winner, legs, None)
            self._changed()

    def reset_result(self, match_id):
        with self.lock:
            m = self.get_match(match_id)
            if m["walkover"]:
                raise TournamentError("Freilos-Matches können nicht zurückgesetzt werden.")
            if not m["winner"]:
                raise TournamentError("Für dieses Match gibt es kein Ergebnis.")
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
                matches.append(c)
            return {
                "name": self.name,
                "start_score": self.start_score,
                "double_out": self.double_out,
                "stations": self.stations,
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
                "start_score": self.start_score,
                "double_out": self.double_out,
                "legs_to_win": self.legs_to_win,
                "final_legs_to_win": self.final_legs_to_win,
                "stations": self.stations,
                "players": self.players,
                "rounds": self.rounds,
                "matches": copy.deepcopy(self.matches),
            }

    @classmethod
    def from_dict(cls, d):
        t = cls.__new__(cls)
        t.name = d["name"]
        t.start_score = d["start_score"]
        t.double_out = d["double_out"]
        t.legs_to_win = d["legs_to_win"]
        t.final_legs_to_win = d["final_legs_to_win"]
        t.stations = d["stations"]
        t.players = d["players"]
        t.rounds = d["rounds"]
        t.matches = d["matches"]
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

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()


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
