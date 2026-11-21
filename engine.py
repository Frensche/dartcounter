"""Spiellogik ohne Oberfläche: Checkout-Solver, Spieler, Statistik (daher auch ohne Tk testbar)."""

from functools import lru_cache

# --------------------------------------------------------------------------
# Checkout-Solver
# --------------------------------------------------------------------------
# Erzeugt alle möglichen Einzelwürfe (Single/Double/Triple/Bull) und sucht
# rekursiv die (in der Praxis übliche) Route mit möglichst wenigen Darts,
# die exakt auf 0 endet - bei Double-Out muss der letzte Wurf ein Double sein.


def _build_throws():
    throws = []
    for n in range(1, 21):
        throws.append((str(n), n, False))          # Single
        throws.append((f"D{n}", n * 2, True))       # Double
        throws.append((f"T{n}", n * 3, False))      # Triple
    throws.append(("25", 25, False))                # Bull außen (Single)
    throws.append(("Bull", 50, True))                # Bull innen (zählt als Double)
    return throws


ALL_THROWS = _build_throws()
THROWS_DESC = sorted(ALL_THROWS, key=lambda t: -t[1])
DOUBLES_DESC = sorted([t for t in ALL_THROWS if t[2]], key=lambda t: -t[1])

# Beim Suchen nach einer Route wird zuerst mit den "großen Fünf" probiert
# (T20, S20, D20, Bull, 25) - so werfen auch echte Spieler bzw. so sind
# klassische Checkout-Tabellen aufgebaut.
_BIG_FIVE_LABELS = ["T20", "20", "D20", "Bull", "25"]
_by_label = {label: (label, val, is_double) for label, val, is_double in ALL_THROWS}
PRIORITY_THROWS = [_by_label[l] for l in _BIG_FIVE_LABELS] + [
    t for t in THROWS_DESC if t[0] not in _BIG_FIVE_LABELS
]


def _solve_exact(score, n, double_out):
    """Route mit genau n Würfen, letzter Wurf gültiges Finish, oder None."""
    if n == 1:
        candidates = DOUBLES_DESC if double_out else THROWS_DESC
        for label, val, is_double in candidates:
            if val == score:
                return (label,)
        return None
    for label, val, is_double in PRIORITY_THROWS:
        rem = score - val
        if rem <= 0:
            continue
        sub = _solve_exact(rem, n - 1, double_out)
        if sub:
            return (label,) + sub
    return None


@lru_cache(maxsize=None)
def solve_checkout(score, darts_left, double_out=True):
    """Liefert ein Tupel von Wurf-Labels für einen Checkout-Vorschlag oder None."""
    if darts_left <= 0 or score <= 0:
        return None
    if double_out and score < 2:
        return None
    for n in range(1, darts_left + 1):
        route = _solve_exact(score, n, double_out)
        if route:
            return route
    return None


def finish_options(score, double_out=True):
    """Mit wie vielen Darts (1-3) ist ein Finish von `score` überhaupt möglich?"""
    return [d for d in (1, 2, 3) if solve_checkout(score, d, double_out)]


# Diese Aufnahmen (Summe dreier Darts) lassen sich mit keiner Dart-Kombination werfen.
IMPOSSIBLE_TURN_SCORES = frozenset({163, 166, 169, 172, 173, 175, 176, 178, 179})
MAX_TURN_SCORE = 180


def chip_kind(label):
    """'triple' | 'double' | 'single' - für die farbige Darstellung der Finish-Wege."""
    if label.startswith("T"):
        return "triple"
    if label.startswith("D") or label == "Bull":
        return "double"
    return "single"


# --------------------------------------------------------------------------
# Spieler + Statistik
# --------------------------------------------------------------------------

class Player:
    def __init__(self, name, start_score=501):
        self.name = name
        self.start_score = start_score  # individueller Startwert (Handicap)
        self.score = start_score
        self.legs_won = 0
        self.turns = []  # alle Aufnahmen des ganzen Spiels (über alle Legs)

    def reset_leg(self):
        self.score = self.start_score

    # ---- Aufnahmen
    def add_turn(self, leg, score, darts, bust, rest_before, raw=None, finish=False):
        self.turns.append({
            "leg": leg, "score": 0 if bust else score, "raw": score if raw is None else raw,
            "darts": darts, "bust": bust, "rest_before": rest_before, "finish": finish,
        })

    def pop_turn(self):
        return self.turns.pop() if self.turns else None

    def drop_leg_turns(self, leg):
        self.turns = [t for t in self.turns if t["leg"] != leg]

    def leg_turns(self, leg):
        return [t for t in self.turns if t["leg"] == leg]

    def recent_text(self, leg, n=6):
        """Letzte Aufnahmen dieses Legs, neueste zuerst, z.B. '100 · 60 · BUST (45)'."""
        turns = self.leg_turns(leg)
        if not turns:
            return "-"
        parts = [f"BUST ({t['raw']})" if t["bust"] else str(t["score"]) for t in reversed(turns[-n:])]
        return "  ·  ".join(parts)

    # ---- Kennzahlen
    @property
    def average(self):
        """3-Dart-Average über das ganze Spiel (Punkte pro Dart x 3)."""
        darts = sum(t["darts"] for t in self.turns)
        return sum(t["score"] for t in self.turns) / darts * 3 if darts else 0.0

    match_average = average

    def stats(self):
        turns = self.turns
        darts = sum(t["darts"] for t in turns)
        points = sum(t["score"] for t in turns)
        legs = sorted({t["leg"] for t in turns})

        first9_pts = first9_darts = 0
        best_leg = None
        for leg in legs:
            lt = self.leg_turns(leg)
            for t in lt[:3]:
                first9_pts += t["score"]
                first9_darts += t["darts"]
            if any(t["finish"] for t in lt):
                d = sum(t["darts"] for t in lt)
                best_leg = d if best_leg is None else min(best_leg, d)

        scores = [t["score"] for t in turns if not t["bust"]]
        finishes = [t["rest_before"] for t in turns if t["finish"]]
        return {
            "legs_won": self.legs_won,
            "darts": darts,
            "points": points,
            "avg": points / darts * 3 if darts else 0.0,
            "first9": first9_pts / first9_darts * 3 if first9_darts else 0.0,
            "highest": max(scores) if scores else 0,
            "n180": sum(1 for s in scores if s == 180),
            "n140": sum(1 for s in scores if 140 <= s < 180),
            "n100": sum(1 for s in scores if 100 <= s < 140),
            "best_finish": max(finishes) if finishes else None,
            "best_leg": best_leg,
            "busts": sum(1 for t in turns if t["bust"]),
        }
