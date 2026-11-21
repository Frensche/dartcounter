"""Tests der Spiellogik (ohne Tk):  python3 tests/test_engine.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config
from engine import (ALL_THROWS, IMPOSSIBLE_TURN_SCORES, Player, chip_kind, finish_options, solve_checkout)


def test_solver():
    assert solve_checkout(170, 3) == ("T20", "T20", "Bull")
    assert solve_checkout(100, 3) == ("T20", "D20")
    assert solve_checkout(60, 3) == ("20", "D20")
    assert solve_checkout(169, 3) is None and solve_checkout(1, 3) is None
    assert finish_options(40) == [1, 2, 3] and finish_options(170) == [3] and finish_options(100) == [2, 3]
    assert finish_options(169) == [] and finish_options(50) == [1, 2, 3]
    assert chip_kind("T20") == "triple" and chip_kind("D16") == "double" and chip_kind("Bull") == "double"
    assert chip_kind("20") == "single" and chip_kind("25") == "single"


def test_impossible_scores():
    vals = [0] + [v for _, v, _ in ALL_THROWS]
    possible = {a + b + c for a in vals for b in vals for c in vals}
    assert {s for s in range(181) if s not in possible} == set(IMPOSSIBLE_TURN_SCORES)


def test_config_migration():
    assert config.migrate_fkeys(config.OLD_DEFAULT_FKEYS) == config.DEFAULT_FKEYS
    assert config.migrate_fkeys(list(range(12))) == list(range(8))
    assert config.migrate_fkeys(None) == config.DEFAULT_FKEYS
    assert config.DEFAULT_FKEYS == [0, 26, 41, 45, 60, 81, 85, 100]


def test_stats():
    p = Player("A", 501)
    p.add_turn(1, 100, 3, False, 501)
    p.add_turn(1, 180, 3, False, 401)
    p.add_turn(1, 0, 3, True, 221, raw=300)
    p.add_turn(1, 140, 3, False, 221)
    p.add_turn(1, 81, 2, False, 81, finish=True)
    p.legs_won = 1
    s = p.stats()
    assert s["darts"] == 14 and s["points"] == 501 and abs(s["avg"] - 501 / 14 * 3) < 1e-9
    assert (s["highest"], s["n180"], s["n140"], s["n100"], s["busts"]) == (180, 1, 1, 1, 1)
    assert s["best_finish"] == 81 and s["best_leg"] == 14
    assert p.recent_text(1) == "81  ·  140  ·  BUST (300)  ·  180  ·  100"
    p.pop_turn()
    assert len(p.turns) == 4
    p.drop_leg_turns(1)
    assert p.turns == [] and p.stats()["avg"] == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("ALLE TESTS OK")
