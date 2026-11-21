"""Minispiele - reine Spiellogik (ohne Oberfläche, daher auch ohne Tk testbar).

Jedes Spiel stellt dieselbe Schnittstelle bereit, die die Oberfläche (minigame_ui.py) nutzt:

    game.actions()   -> Liste der gerade möglichen Eingaben (Beschriftung, Tasten, Stil)
    game.act(id)     -> Eingabe ausführen (True, wenn sich der Stand geändert hat)
    game.undo()      -> letzte Eingabe zurücknehmen
    game.view()      -> was angezeigt werden soll (Kopfzeile, Felder, Spielerkarten, ggf. Tabelle)
    game.ranking()   -> Endstand
    game.finished    -> Spiel beendet?
"""

import copy
import random

from engine import IMPOSSIBLE_TURN_SCORES, MAX_TURN_SCORE, finish_options, solve_checkout


def action(aid, label, keys=(), style="", pad=None, enabled=True):
    return {"id": aid, "label": label, "keys": tuple(keys), "style": style, "pad": pad, "enabled": enabled}


def rank_list(keys):
    """Sortierschlüssel je Spieler (größer = besser) -> [(Spielerindex, Platz)], gleiche Schlüssel = gleicher Platz."""
    order = sorted(range(len(keys)), key=lambda i: keys[i], reverse=True)
    out, rank, prev = [], 0, None
    for pos, i in enumerate(order):
        if keys[i] != prev:
            rank, prev = pos + 1, keys[i]
        out.append((i, rank))
    return out


class MiniGame:
    key = ""
    title = ""
    summary = ""
    rules = ""
    hint = ""
    options_spec = []        # [{"key", "label", "choices": [(Text, Wert)], "default": Wert}]
    number_input = None      # (min, max), wenn das Spiel eine Zahleneingabe braucht

    def __init__(self, names, options=None):
        self.names = list(names)
        self.n = len(self.names)
        self.options = {o["key"]: o["default"] for o in self.options_spec}
        self.options.update(options or {})
        self.current = 0
        self.finished = False
        self.message = ""
        self._undo = []
        self.setup()

    # ---- von den Spielen zu überschreiben
    def setup(self):
        pass

    def do(self, aid, value=None):
        return False

    def actions(self):
        return []

    def view(self):
        return {}

    def result_keys(self):
        """Sortierschlüssel je Spieler für den Endstand (größer = besser)."""
        return [0] * self.n

    def result_text(self, i):
        return ""

    # ---- gemeinsame Logik
    def act(self, aid, value=None):
        if self.finished:
            return False
        snapshot = copy.deepcopy({k: v for k, v in self.__dict__.items() if k != "_undo"})
        self.message = ""
        changed = self.do(aid, value)
        if changed:
            self._undo.append(snapshot)
        return changed

    def undo(self):
        if not self._undo:
            return False
        self.__dict__.update(self._undo.pop())
        return True

    def ranking(self):
        keys = self.result_keys()
        return [{"rank": rank, "index": i, "name": self.names[i], "text": self.result_text(i)}
                for i, rank in rank_list(keys)]

    def next_player(self, skip=lambda i: False):
        """Zum nächsten Spieler wechseln, der noch mitspielt. False, wenn keiner mehr übrig ist."""
        for step in range(1, self.n + 1):
            cand = (self.current + step) % self.n
            if not skip(cand):
                self.current = cand
                return True
        return False


# --------------------------------------------------------------------------
# Random Checkout
# --------------------------------------------------------------------------

DIFFICULTIES = [("Leicht (2-60)", (2, 60)), ("Mittel (2-100)", (2, 100)),
                ("Schwer (2-170)", (2, 170)), ("Profi (100-170)", (100, 170))]


class RandomCheckout(MiniGame):
    key = "random_checkout"
    title = "Random Checkout"
    summary = "Zufälliges Finish in drei Darts auschecken"
    rules = ("Für jede Runde wird ein zufälliges Finish ausgewürfelt - alle Spieler bekommen dieselbe Zahl. "
             "Du hast drei Darts, um sie mit einem Doppel auszuchecken. Eingabe: geschafft mit 1, 2 oder 3 Darts "
             "oder nicht geschafft. Wer die meisten Finishes trifft, gewinnt.")
    hint = "1 / 2 / 3: geschafft mit so vielen Darts   ·   0 oder N: nicht geschafft   ·   Strg+Z: zurück"
    options_spec = [
        {"key": "rounds", "label": "Runden", "choices": [("5", 5), ("10", 10), ("15", 15), ("20", 20)],
         "default": 10},
        {"key": "level", "label": "Schwierigkeit", "choices": DIFFICULTIES, "default": (2, 100)},
    ]

    def setup(self):
        self.hits = [0] * self.n
        self.played = [0] * self.n
        self.dart_sum = [0] * self.n
        self.round = 1
        self.target = self._new_target()

    def _new_target(self):
        lo, hi = self.options["level"]
        return random.choice([s for s in range(lo, hi + 1) if finish_options(s, True)])

    def actions(self):
        possible = finish_options(self.target, True)
        acts = [action(f"done{d}", f"Geschafft mit {d} Dart{'s' if d > 1 else ''}", (str(d),), "good",
                       enabled=d in possible) for d in (1, 2, 3)]
        acts.append(action("fail", "Nicht geschafft", ("0", "n"), "bad"))
        return acts

    def do(self, aid, value=None):
        p = self.current
        if aid.startswith("done"):
            d = int(aid[4:])
            if d not in finish_options(self.target, True):
                self.message = f"{self.target} lässt sich nicht mit {d} Dart{'s' if d > 1 else ''} auschecken."
                return False
            self.hits[p] += 1
            self.dart_sum[p] += d
        elif aid != "fail":
            return False
        self.played[p] += 1
        self.current += 1
        if self.current >= self.n:
            self.current = 0
            self.round += 1
            if self.round > self.options["rounds"]:
                self.finished = True
                return True
            self.target = self._new_target()
        return True

    def view(self):
        route = solve_checkout(self.target, 3, True) or ()
        return {
            "headline": str(self.target),
            "subline": f"Runde {self.round}/{self.options['rounds']}   ·   {self.names[self.current]} ist dran",
            "chips": list(route),
            "cards": [{
                "name": self.names[i], "big": f"{self.hits[i]}/{self.played[i]}",
                "lines": [f"Quote {self.hits[i] * 100 // self.played[i]} %" if self.played[i] else "Quote -",
                          f"Ø {self.dart_sum[i] / self.hits[i]:.1f} Darts" if self.hits[i] else "Ø - Darts"],
                "active": i == self.current and not self.finished} for i in range(self.n)],
        }

    def result_keys(self):
        return [(self.hits[i], -(self.dart_sum[i] / self.hits[i]) if self.hits[i] else 0) for i in range(self.n)]

    def result_text(self, i):
        return f"{self.hits[i]} von {self.played[i]} Finishes" + (
            f"  (Ø {self.dart_sum[i] / self.hits[i]:.1f} Darts)" if self.hits[i] else "")


# --------------------------------------------------------------------------
# 121
# --------------------------------------------------------------------------

class Game121(MiniGame):
    key = "121"
    title = "121"
    summary = "Finish-Training: Ziel steigt mit jedem Erfolg"
    rules = ("Startziel ist 121. Du hast neun Darts (drei Aufnahmen), um das Ziel mit einem Doppel auszuchecken. "
             "Geschafft: das Ziel steigt um 1. Nicht geschafft: du verlierst ein Leben und versuchst dasselbe Ziel "
             "noch einmal. Wer am Ende das höchste Ziel erreicht hat, gewinnt.")
    hint = "J oder 1: geschafft   ·   N oder 0: nicht geschafft   ·   Strg+Z: zurück"
    options_spec = [
        {"key": "lives", "label": "Leben", "choices": [("1 Leben", 1), ("3 Leben", 3), ("5 Leben", 5)],
         "default": 3},
    ]
    START, MAX_TARGET = 121, 170

    def setup(self):
        self.target = [self.START] * self.n
        self.lives = [self.options["lives"]] * self.n
        self.best = [0] * self.n          # höchstes geschafftes Ziel
        self.out = [False] * self.n

    def actions(self):
        return [action("ok", "Geschafft", ("j", "1"), "good"), action("fail", "Nicht geschafft", ("n", "0"), "bad")]

    def do(self, aid, value=None):
        p = self.current
        if aid == "ok":
            self.best[p] = self.target[p]
            self.target[p] += 1
            if self.target[p] > self.MAX_TARGET:
                self.out[p] = True                 # alle Ziele geschafft
        elif aid == "fail":
            self.lives[p] -= 1
            if self.lives[p] <= 0:
                self.out[p] = True
        else:
            return False
        if not self.next_player(lambda i: self.out[i]):
            self.finished = True
        return True

    def view(self):
        p = self.current
        route = solve_checkout(self.target[p], 3, True) or ()
        sub = f"{self.names[p]}   ·   9 Darts (3 Aufnahmen)   ·   Leben: {'♥' * self.lives[p]}"
        if not route and not self.finished:
            sub += "   ·   mehrere Aufnahmen nötig"
        return {
            "headline": str(self.target[p]) if not self.finished else "Ende",
            "subline": sub, "chips": list(route),
            "cards": [{
                "name": self.names[i], "big": str(self.target[i] if not self.out[i] else (self.best[i] or "-")),
                "lines": ["♥" * self.lives[i] if self.lives[i] > 0 else "keine Leben",
                          f"Bestes Ziel: {self.best[i] or '-'}"],
                "active": i == self.current and not self.finished, "out": self.out[i]} for i in range(self.n)],
        }

    def result_keys(self):
        return list(self.best)

    def result_text(self, i):
        return f"Ziel {self.best[i]} geschafft" if self.best[i] else "kein Ziel geschafft"


# --------------------------------------------------------------------------
# Cricket
# --------------------------------------------------------------------------

CRICKET_FIELDS = [20, 19, 18, 17, 16, 15, 25]
CRICKET_LABELS = ["20", "19", "18", "17", "16", "15", "Bull"]


class Cricket(MiniGame):
    key = "cricket"
    title = "Cricket"
    summary = "20 bis 15 und Bull schließen, Punkte sammeln"
    rules = ("Ziel sind die Felder 20, 19, 18, 17, 16, 15 und Bull. Jeder Treffer ist eine Markierung (Double = 2, "
             "Triple = 3). Mit drei Markierungen ist ein Feld geschlossen. Triffst du ein Feld, das du geschlossen "
             "hast und ein Gegner noch nicht, bekommst du dessen Punkte. Gewonnen hat, wer alle Felder geschlossen "
             "hat und mindestens so viele Punkte wie alle Gegner. Allein gespielt: alle Felder schließen.")
    hint = ("Feld wählen: 1=20  2=19  3=18  4=17  5=16  6=15  7=Bull, dann S / D / T (z. B. 1 T = Triple 20)   ·   "
            "0 oder M: Fehlwurf   ·   N: Aufnahme beenden   ·   Strg+Z: zurück")

    def setup(self):
        self.marks = [[0] * 7 for _ in range(self.n)]
        self.points = [0] * self.n
        self.mark_total = [0] * self.n
        self.turns = [0] * self.n
        self.darts = 0
        self.round = 1
        self.winner = None

    def actions(self):
        acts = []
        for fi, label in enumerate(CRICKET_LABELS):
            for col, (code, name) in enumerate((("S", "Single"), ("D", "Double"), ("T", "Triple"))):
                if fi == 6 and code == "T":
                    continue                     # es gibt kein Triple-Bull
                acts.append(action(f"{code}{fi}", f"{code[0]} {label}", (f"{fi + 1}{code.lower()}",),
                                   "triple" if code == "T" else ("double" if code == "D" else ""), pad=(fi, col)))
        acts.append(action("miss", "Fehlwurf", ("0", "m"), "bad", pad=(7, 0)))
        acts.append(action("next", "Aufnahme beenden", ("n",), "", pad=(7, 1)))
        return acts

    def _end_turn(self):
        self.turns[self.current] += 1
        self.darts = 0
        self.current = (self.current + 1) % self.n
        if self.current == 0:
            self.round += 1

    def do(self, aid, value=None):
        p = self.current
        if aid == "next":
            self._end_turn()
            return True
        if aid == "miss":
            self.darts += 1
        else:
            try:
                mult, fi = {"S": 1, "D": 2, "T": 3}[aid[0]], int(aid[1:])
                field = CRICKET_FIELDS[fi]
            except (KeyError, ValueError, IndexError):
                return False
            if fi == 6 and mult == 3:
                return False
            for _ in range(mult):
                self.mark_total[p] += 1
                if self.marks[p][fi] < 3:
                    self.marks[p][fi] += 1
                elif any(self.marks[o][fi] < 3 for o in range(self.n) if o != p):
                    self.points[p] += field
            self.darts += 1
            if all(m >= 3 for m in self.marks[p]) and (
                    self.n == 1 or self.points[p] >= max(self.points[o] for o in range(self.n) if o != p)):
                self.winner = p
                self.finished = True
                return True
        if self.darts >= 3:
            self._end_turn()
        return True

    def view(self):
        sym = {0: "", 1: "/", 2: "X", 3: "⊗"}
        rows = [(CRICKET_LABELS[fi], [sym[self.marks[p][fi]] for p in range(self.n)],
                 [self.marks[p][fi] >= 3 for p in range(self.n)]) for fi in range(7)]
        cards = []
        for i in range(self.n):
            closed = sum(1 for m in self.marks[i] if m >= 3)
            mpr = f"MPR {self.mark_total[i] / self.turns[i]:.2f}" if self.turns[i] else "MPR -"
            cards.append({"name": self.names[i], "big": str(self.points[i]),
                          "lines": [f"Geschlossen {closed}/7", mpr],
                          "active": i == self.current and not self.finished})
        return {
            "headline": "Cricket", "chips": [],
            "subline": f"{self.names[self.current]}   ·   Dart {min(self.darts + 1, 3)}/3   ·   Runde {self.round}",
            "table": {"players": list(self.names), "rows": rows, "current": self.current},
            "cards": cards,
        }

    def result_keys(self):
        return [(i == self.winner, sum(1 for m in self.marks[i] if m >= 3), self.points[i]) for i in range(self.n)]

    def result_text(self, i):
        closed = sum(1 for m in self.marks[i] if m >= 3)
        return f"{self.points[i]} Punkte, {closed}/7 Felder geschlossen" + ("  -  GEWONNEN" if i == self.winner else "")


# --------------------------------------------------------------------------
# Around the Clock
# --------------------------------------------------------------------------

class AroundTheClock(MiniGame):
    key = "clock"
    title = "Around the Clock"
    summary = "1 bis 20 und Bull der Reihe nach treffen"
    rules = ("Triff der Reihe nach die Felder 1, 2, 3 ... bis 20 und zuletzt das Bull. Jeder Spieler hat drei Darts "
             "pro Aufnahme. Wer das Bull zuerst trifft, gewinnt. Variante mit Sprung: Ein Double zählt als zwei, "
             "ein Triple als drei Felder.")
    hint = "1 oder H: Treffer   ·   2: Double (+2)   ·   3: Triple (+3)   ·   0 oder M: Fehlwurf   ·   Strg+Z: zurück"
    options_spec = [
        {"key": "variant", "label": "Variante",
         "choices": [("Klassisch (jeder Treffer = 1 Feld)", "classic"), ("Mit Sprung (Double +2, Triple +3)", "jump")],
         "default": "classic"},
    ]
    BULL = 21

    def setup(self):
        self.pos = [1] * self.n          # aktuelles Ziel: 1..20, 21 = Bull
        self.darts_total = [0] * self.n
        self.darts = 0
        self.winner = None

    @staticmethod
    def label(pos):
        return "Bull" if pos == AroundTheClock.BULL else str(pos)

    def actions(self):
        acts = [action("hit", "Treffer", ("1", "h"), "good")]
        if self.options["variant"] == "jump":
            acts += [action("double", "Double  (+2)", ("2",), "double"), action("triple", "Triple  (+3)", ("3",), "triple")]
        acts.append(action("miss", "Fehlwurf", ("0", "m"), "bad"))
        return acts

    def do(self, aid, value=None):
        p = self.current
        steps = {"hit": 1, "double": 2, "triple": 3}
        if aid in steps:
            if aid != "hit" and self.options["variant"] != "jump":
                return False
            self.pos[p] += steps[aid]
        elif aid != "miss":
            return False
        self.darts_total[p] += 1
        self.darts += 1
        if self.pos[p] > self.BULL:
            self.winner = p
            self.finished = True
            return True
        if self.darts >= 3:
            self.darts = 0
            self.current = (self.current + 1) % self.n
        return True

    def view(self):
        p = self.current
        return {
            "headline": self.label(self.pos[p]) if not self.finished else "Geschafft!",
            "subline": f"{self.names[p]}   ·   Dart {min(self.darts + 1, 3)}/3", "chips": [],
            "cards": [{"name": self.names[i], "big": self.label(min(self.pos[i], self.BULL)),
                       "lines": [f"{self.darts_total[i]} Darts", f"{min(self.pos[i] - 1, self.BULL)}/{self.BULL} Felder"],
                       "active": i == self.current and not self.finished} for i in range(self.n)],
        }

    def result_keys(self):
        return [(i == self.winner, self.pos[i], -self.darts_total[i]) for i in range(self.n)]

    def result_text(self, i):
        if i == self.winner:
            return f"Bull getroffen mit {self.darts_total[i]} Darts"
        return f"bis Feld {self.label(min(self.pos[i], self.BULL))} ({self.darts_total[i]} Darts)"


# --------------------------------------------------------------------------
# Shanghai
# --------------------------------------------------------------------------

class Shanghai(MiniGame):
    key = "shanghai"
    title = "Shanghai"
    summary = "Runde für Runde ein Zielfeld, Single + Double + Triple = Sieg"
    rules = ("In Runde 1 zählt nur die 1, in Runde 2 nur die 2 und so weiter. Single zählt einfach, Double doppelt, "
             "Triple dreifach. Wer in einer Aufnahme Single, Double und Triple des Zielfelds trifft (ein Shanghai), "
             "gewinnt sofort. Sonst gewinnt, wer nach der letzten Runde die meisten Punkte hat.")
    hint = "1: Single   ·   2: Double   ·   3: Triple   ·   0 oder M: Fehlwurf   ·   Strg+Z: zurück"
    options_spec = [
        {"key": "rounds", "label": "Runden", "choices": [("7 Runden (1-7)", 7), ("20 Runden (1-20)", 20)],
         "default": 7},
    ]

    def setup(self):
        self.score = [0] * self.n
        self.round = 1
        self.darts = 0
        self.hit = [set() for _ in range(self.n)]      # in dieser Aufnahme getroffen: 1 / 2 / 3
        self.winner = None
        self.shanghai = False

    def actions(self):
        return [action("S", "Single", ("1",), ""), action("D", "Double", ("2",), "double"),
                action("T", "Triple", ("3",), "triple"), action("miss", "Fehlwurf", ("0", "m"), "bad")]

    def do(self, aid, value=None):
        p = self.current
        if aid in ("S", "D", "T"):
            mult = {"S": 1, "D": 2, "T": 3}[aid]
            self.score[p] += mult * self.round
            self.hit[p].add(mult)
            if self.hit[p] >= {1, 2, 3}:
                self.winner, self.shanghai, self.finished = p, True, True
                self.darts += 1
                return True
        elif aid != "miss":
            return False
        self.darts += 1
        if self.darts >= 3:
            self.darts = 0
            self.hit[p] = set()
            self.current += 1
            if self.current >= self.n:
                self.current = 0
                self.round += 1
                if self.round > self.options["rounds"]:
                    self.finished = True
        return True

    def view(self):
        r = min(self.round, self.options["rounds"])
        p = self.current
        done = "".join({1: "S", 2: "D", 3: "T"}[m] + " " for m in sorted(self.hit[p])).strip()
        return {
            "headline": f"Ziel: {r}",
            "subline": f"Runde {r}/{self.options['rounds']}   ·   {self.names[p]}   ·   Dart {min(self.darts + 1, 3)}/3"
                       + (f"   ·   getroffen: {done}" if done else ""),
            "chips": [f"S{r}", f"D{r}", f"T{r}"],
            "cards": [{"name": self.names[i], "big": str(self.score[i]),
                       "lines": [f"Ziel {r}"], "active": i == self.current and not self.finished}
                      for i in range(self.n)],
        }

    def result_keys(self):
        return [(i == self.winner, self.score[i]) for i in range(self.n)]

    def result_text(self, i):
        return f"{self.score[i]} Punkte" + ("  -  SHANGHAI!" if i == self.winner and self.shanghai else "")


# --------------------------------------------------------------------------
# Bob's 27
# --------------------------------------------------------------------------

BOB_TARGETS = list(range(1, 21)) + [25]


class Bobs27(MiniGame):
    key = "bobs27"
    title = "Bob's 27"
    summary = "Doubles-Training: D1 bis D20 und Bull"
    rules = ("Du startest mit 27 Punkten und wirfst nacheinander auf D1, D2 ... D20 und zuletzt das Bull. Pro Ziel "
             "gibst du die Zahl der Treffer aus drei Darts ein (0-3). Jeder Treffer bringt den Wert des Doubles "
             "(D5 = 10 Punkte), ohne Treffer verlierst du diesen Wert. Wer unter 1 Punkt fällt, scheidet aus. "
             "Wer am Ende die meisten Punkte hat, gewinnt.")
    hint = "0 / 1 / 2 / 3: Treffer aus drei Darts   ·   Strg+Z: zurück"

    def setup(self):
        self.score = [27] * self.n
        self.idx = [0] * self.n
        self.out = [False] * self.n
        self.done = [False] * self.n

    @staticmethod
    def value(target):
        return 50 if target == 25 else 2 * target

    @staticmethod
    def label(target):
        return "Bull" if target == 25 else f"D{target}"

    def actions(self):
        return [action(f"h{h}", f"{h} Treffer", (str(h),), "bad" if h == 0 else "good") for h in range(4)]

    def _inactive(self, i):
        return self.out[i] or self.done[i]

    def do(self, aid, value=None):
        p = self.current
        if not (aid.startswith("h") and aid[1:].isdigit() and 0 <= int(aid[1:]) <= 3):
            return False
        hits = int(aid[1:])
        val = self.value(BOB_TARGETS[self.idx[p]])
        if hits:
            self.score[p] += hits * val
        else:
            self.score[p] -= val
        if self.score[p] <= 0:
            self.out[p] = True
        else:
            self.idx[p] += 1
            if self.idx[p] >= len(BOB_TARGETS):
                self.done[p] = True
        if not self.next_player(self._inactive):
            self.finished = True
        return True

    def view(self):
        p = self.current
        t = BOB_TARGETS[min(self.idx[p], len(BOB_TARGETS) - 1)]
        return {
            "headline": self.label(t) if not self.finished else "Ende",
            "subline": f"{self.names[p]}   ·   Treffer aus drei Darts eingeben   ·   Punkte: {self.score[p]}",
            "chips": [self.label(t)],
            "cards": [{"name": self.names[i], "big": str(max(self.score[i], 0)),
                       "lines": ["ausgeschieden" if self.out[i] else (
                           "geschafft!" if self.done[i] else f"Ziel {self.idx[i] + 1}/{len(BOB_TARGETS)}")],
                       "active": i == self.current and not self.finished, "out": self.out[i]}
                      for i in range(self.n)],
        }

    def result_keys(self):
        return [(not self.out[i], self.score[i] if not self.out[i] else self.idx[i]) for i in range(self.n)]

    def result_text(self, i):
        if self.out[i]:
            return f"ausgeschieden bei {self.label(BOB_TARGETS[self.idx[i]])}"
        return f"{self.score[i]} Punkte" + (" (alle Ziele geschafft)" if self.done[i] else "")


# --------------------------------------------------------------------------
# Highscore (Count-Up)
# --------------------------------------------------------------------------

class Highscore(MiniGame):
    key = "highscore"
    title = "Highscore"
    summary = "Möglichst viele Punkte in einer festen Rundenzahl"
    rules = ("Jeder Spieler wirft in jeder Runde drei Darts und gibt die Punkte der Aufnahme ein (0-180). Alle "
             "Punkte werden addiert. Wer nach der letzten Runde die meisten Punkte hat, gewinnt.")
    hint = "Punkte der Aufnahme tippen und Enter   ·   F1-F8: Schnell-Scores   ·   Strg+Z: zurück"
    number_input = (0, MAX_TURN_SCORE)
    options_spec = [
        {"key": "rounds", "label": "Runden", "choices": [("5", 5), ("8", 8), ("10", 10), ("15", 15)], "default": 8},
    ]

    def setup(self):
        self.total = [0] * self.n
        self.turns = [[] for _ in range(self.n)]
        self.round = 1

    def do(self, aid, value=None):
        if aid != "score" or value is None:
            return False
        value = int(value)
        if not 0 <= value <= MAX_TURN_SCORE:
            self.message = f"Eine Aufnahme hat 0 bis {MAX_TURN_SCORE} Punkte."
            return False
        if value in IMPOSSIBLE_TURN_SCORES:
            self.message = f"{value} Punkte lassen sich mit drei Darts nicht werfen."
            return False
        p = self.current
        self.total[p] += value
        self.turns[p].append(value)
        self.current += 1
        if self.current >= self.n:
            self.current = 0
            self.round += 1
            if self.round > self.options["rounds"]:
                self.finished = True
        return True

    def view(self):
        r = min(self.round, self.options["rounds"])
        return {
            "headline": f"Runde {r}/{self.options['rounds']}",
            "subline": f"{self.names[self.current]} ist dran   ·   Punkte der Aufnahme eingeben", "chips": [],
            "cards": [{"name": self.names[i], "big": str(self.total[i]),
                       "lines": [f"Letzte: {self.turns[i][-1]}" if self.turns[i] else "Letzte: -",
                                 f"Ø {self.total[i] / len(self.turns[i]):.1f}" if self.turns[i] else "Ø -"],
                       "active": i == self.current and not self.finished} for i in range(self.n)],
        }

    def result_keys(self):
        return list(self.total)

    def result_text(self, i):
        avg = self.total[i] / len(self.turns[i]) if self.turns[i] else 0.0
        return f"{self.total[i]} Punkte  (Ø {avg:.1f} pro Aufnahme)"


GAMES = [RandomCheckout, Game121, Cricket, AroundTheClock, Shanghai, Bobs27, Highscore]
GAME_BY_KEY = {g.key: g for g in GAMES}


def create_game(key, names, options=None):
    return GAME_BY_KEY[key](names, options)
