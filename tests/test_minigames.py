"""Tests der Minispiel-Logik (ohne Tk):  python3 tests/test_minigames.py"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from engine import finish_options
from minigames import (GAMES, Bobs27, Cricket, AroundTheClock, Game121, Highscore, RandomCheckout, Shanghai,
                       create_game, rank_list)


def test_rank_list():
    assert rank_list([5, 9, 9, 1]) == [(1, 1), (2, 1), (0, 3), (3, 4)]


def test_all_games_generic():
    """Jedes Spiel lässt sich bis zum Ende spielen, Undo stellt jeden Schritt exakt wieder her."""
    random.seed(7)
    for cls in GAMES:
        for n in (1, 2, 4):
            g = create_game(cls.key, [f"P{i}" for i in range(n)])
            steps = 0
            while not g.finished and steps < 4000:
                steps += 1
                if g.number_input:
                    g.act("score", random.choice([0, 26, 60, 100, 180, 45]))
                else:
                    usable = [a for a in g.actions() if a["enabled"]]
                    g.act(random.choice(usable)["id"])
                v = g.view()
                assert v["cards"] and len(v["cards"]) == n and "headline" in v
            assert g.finished, (cls.key, n)
            rk = g.ranking()
            assert len(rk) == n and rk[0]["rank"] == 1 and all(r["text"] for r in rk), (cls.key, rk)
            # Undo bis zum Anfang
            count = 0
            while g.undo():
                count += 1
            assert count > 0 and not g.finished
            fresh = create_game(cls.key, [f"P{i}" for i in range(n)], g.options)
            for k in ("current", "message"):
                assert getattr(g, k) == getattr(fresh, k)
    print("ok  alle Spiele generisch (1/2/4 Spieler, Undo)")


def test_random_checkout():
    g = RandomCheckout(["A", "B"], {"rounds": 2, "level": (2, 60)})
    for _ in range(6):
        assert 2 <= g.target <= 60 and finish_options(g.target)
    t = g.target
    # nicht mögliche Darts-Anzahl wird abgelehnt (z.B. 1 Dart bei Nicht-Double)
    impossible = [d for d in (1, 2, 3) if d not in finish_options(t)]
    for d in impossible:
        assert g.act(f"done{d}") is False and g.message
    assert g.act("done3") and g.hits == [1, 0] and g.current == 1 and g.target == t   # gleiche Zahl für alle
    g.act("fail")
    assert g.round == 2 and g.current == 0
    g.act("fail"); g.act("fail")
    assert g.finished and g.ranking()[0]["name"] == "A"


def test_121():
    g = Game121(["A", "B"], {"lives": 2})
    assert g.target == [121, 121]
    g.act("ok")                          # A: 121 geschafft -> 122
    assert g.best[0] == 121 and g.target[0] == 122 and g.current == 1
    g.act("fail"); g.act("fail")         # B: Leben 1, A: 122 verfehlt -> Leben 1
    assert g.lives == [1, 1]
    g.act("fail")                        # B: Leben 0 -> ausgeschieden (nächster ist A)
    assert g.out == [False, True] and g.current == 0
    g.act("fail")                        # A ohne Leben -> Ende
    assert g.finished and g.ranking()[0]["name"] == "A"
    assert g.ranking()[0]["text"] == "Ziel 121 geschafft" and g.ranking()[1]["text"] == "kein Ziel geschafft"
    # bis 170 durchspielen
    g = Game121(["Solo"], {"lives": 1})
    for _ in range(50):
        g.act("ok")
    assert g.finished and g.best[0] == 170


def test_cricket():
    g = Cricket(["A", "B"])
    ids = {a["id"] for a in g.actions()}
    assert "T0" in ids and "T6" not in ids and "D6" in ids and "S6" in ids
    # A: Triple 20 schließt die 20
    g.act("T0"); assert g.marks[0][0] == 3 and g.points[0] == 0
    g.act("S0"); assert g.points[0] == 20          # B hat 20 noch nicht geschlossen -> Punkte
    g.act("miss"); assert g.current == 1 and g.darts == 0      # 3 Darts -> B ist dran
    g.act("D0"); assert g.marks[1][0] == 2 and g.points[1] == 0
    g.act("S0"); assert g.marks[1][0] == 3 and g.points[1] == 0   # B schließt 20 (3. Markierung)
    g.act("S0"); assert g.points[1] == 0              # jetzt von beiden geschlossen -> keine Punkte mehr
    assert g.current == 0
    g.undo(); g.undo()
    assert g.marks[1][0] == 2 and g.current == 1
    # Sieg: A schließt alles und hat mehr Punkte
    g = Cricket(["A", "B"])
    g.points = [50, 40]
    g.marks[0] = [3, 3, 3, 3, 3, 3, 2]
    g.act("S6")
    assert g.finished and g.winner == 0 and g.ranking()[0]["index"] == 0
    # alle geschlossen, aber weniger Punkte -> kein Sieg
    g = Cricket(["A", "B"]); g.points = [10, 40]; g.marks[0] = [3, 3, 3, 3, 3, 3, 2]
    g.act("S6"); assert not g.finished
    # Allein: Felder schließen
    g = Cricket(["Solo"])
    for fi in range(7):
        g.act(f"T{fi}" if fi < 6 else "D6"); g.act("D6" if False else "miss"); g.act("miss")
    assert g.marks[0][:6] == [3] * 6
    g.act("D6"); g.act("miss"); g.act("miss"); g.act("S6")
    assert g.finished


def test_clock():
    g = AroundTheClock(["A", "B"])
    assert [a["id"] for a in g.actions()] == ["hit", "miss"]
    assert g.act("double") is False
    g.act("hit"); g.act("hit"); g.act("miss")
    assert g.pos[0] == 3 and g.current == 1
    j = AroundTheClock(["A"], {"variant": "jump"})
    assert "double" in [a["id"] for a in j.actions()]
    j.act("triple"); assert j.pos[0] == 4
    # Bull erreichen = Sieg
    j.pos[0] = 21; j.act("hit")
    assert j.finished and j.winner == 0 and "Bull" in j.ranking()[0]["text"]


def test_shanghai():
    g = Shanghai(["A", "B"], {"rounds": 3})
    g.act("S"); g.act("D"); g.act("T")        # Shanghai in Runde 1 -> sofort gewonnen
    assert g.finished and g.winner == 0 and g.score[0] == 1 + 2 + 3 and g.shanghai
    g = Shanghai(["A", "B"], {"rounds": 2})
    for a in ("T", "miss", "miss"):           # A: 3
        g.act(a)
    for a in ("D", "miss", "miss"):           # B: 2
        g.act(a)
    assert g.round == 2 and g.score == [3, 2]
    for a in ("S", "miss", "miss", "miss", "miss", "miss"):   # A: +2, B: 0
        g.act(a)
    assert g.finished and g.winner is None and g.ranking()[0]["name"] == "A" and g.score == [5, 2]


def test_bobs27():
    g = Bobs27(["A"])
    assert g.score == [27]
    g.act("h2"); assert g.score == [27 + 2 * 2] and g.idx == [1]        # D1: 2 Treffer = +4
    g.act("h0"); assert g.score == [31 - 4]                              # D2 verfehlt: -4
    g.undo(); assert g.score == [31]
    g = Bobs27(["A", "B"]); g.score = [3, 27]
    g.act("h0")                                                          # A: D1 verfehlt -> 3-2 = 1
    assert g.out == [False, False]
    g.act("h1"); g.act("h0")                                             # B ok, A: D2 verfehlt -> -3 -> ausgeschieden
    assert g.out[0] and not g.finished
    for _ in range(25):
        if g.finished: break
        g.act("h3")
    assert g.finished and g.ranking()[0]["name"] == "B"


def test_highscore():
    g = Highscore(["A", "B"], {"rounds": 2})
    assert g.act("score", 181) is False and g.message
    assert g.act("score", 179) is False and "nicht werfen" in g.message
    g.act("score", 100); g.act("score", 60); g.act("score", 26); g.act("score", 140)
    assert g.finished and g.total == [126, 200] and g.ranking()[0]["name"] == "B"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("ALLE MINISPIEL-TESTS OK")
