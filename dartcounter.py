#!/usr/bin/env python3
"""
Dartcounter - ein einfacher, aber vollständiger Dart-Scorer für Linux.

Features:
- 1-4 Spieler mit Namenseingabe
- Startpunktzahl 301 / 501 / 701 (Standard: 501)
- Double-Out (Standard an) oder Straight-Out
- F1-F12 als frei editierbare Schnelleingabe-Buttons für häufige 3-Darts-Scores
- Manuelle Eingabe eines beliebigen Turn-Scores (0-180)
- Automatische Checkout-Vorschläge
- Bust-Erkennung (Double-Out: <0 oder ==1 ist Bust)
- Undo der letzten Eingabe
- Legs (First to X), 3-Darts-Average je Spieler
- Turniermodus: KO-Baum oder Gruppenphase + KO-Runde. Ein Rechner ist Turnierleiter
  + Server (passwortgeschützt), beliebig viele Stationen (z.B. 6 Rechner) holen sich
  Matches und melden Ergebnisse automatisch
- Anzeige der letzten Aufnahmen je Spieler, Vereinslogo, Kiosk-Modus (Vollbild)
- Einstellungen werden unter ~/.config/dartcounter/config.json gespeichert

Start:
    python3 dartcounter.py               (Kiosk-Modus / Vollbild)
    python3 dartcounter.py --windowed    (normales Fenster, z.B. zum Testen)

Benötigt:
    sudo apt install python3-tk   (falls tkinter noch nicht installiert ist)
"""

import json
import math
import os
import random
import sys
from functools import lru_cache
import tkinter as tk
from tkinter import ttk, messagebox

from tournament import TOURNAMENT_PATH, DEFAULT_PORT, MAX_HANDICAP, Tournament, TournamentClient, \
    TournamentError, TournamentServer, check_start_scores, start_scores
import tournament_ui
import lock
import theme

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "dartcounter")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Standard-Belegung der F-Tasten: die 12 gängigsten 3-Darts-Turnscores
DEFAULT_FKEYS = [26, 41, 45, 60, 81, 85, 95, 100, 110, 120, 140, 180]

DEFAULT_CONFIG = {
    "fkeys": DEFAULT_FKEYS,
    "start_score": 501,
    "double_out": True,
    "legs_to_win": 1,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg.update(data)
            if not isinstance(cfg.get("fkeys"), list) or len(cfg["fkeys"]) != 12:
                cfg["fkeys"] = list(DEFAULT_FKEYS)
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


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
# klassische Checkout-Tabellen aufgebaut. Erst wenn damit kein Weg gefunden
# wird, weichen wir auf die restlichen Felder aus.
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
    """Liefert ein Tupel von Wurf-Labels für einen Checkout-Vorschlag oder None.

    Es wird immer die Route mit den wenigsten Darts gesucht (so wie auf
    klassischen Checkout-Tabellen), bevorzugt über T20 / S20 / D20 / Bull.
    """
    if darts_left <= 0 or score <= 0:
        return None
    if double_out and score < 2:
        return None
    for n in range(1, darts_left + 1):
        route = _solve_exact(score, n, double_out)
        if route:
            return route
    return None


# --------------------------------------------------------------------------
# Spieler-Datenmodell
# --------------------------------------------------------------------------

class Player:
    def __init__(self, name, start_score=501):
        self.name = name
        self.start_score = start_score  # individueller Startwert (Handicap)
        self.score = start_score
        self.legs_won = 0
        self.turn_scores = []  # alle Turn-Scores dieses Legs (für Average)
        self.all_scores = []   # alle Turn-Scores des ganzen Spiels/Matches
        self.throws = []       # alle Aufnahmen dieses Legs als (Score, Bust) - für die Anzeige

    def reset_leg(self):
        self.score = self.start_score
        self.turn_scores = []
        self.throws = []

    @property
    def average(self):
        if not self.turn_scores:
            return 0.0
        return sum(self.turn_scores) / len(self.turn_scores)

    def recent_text(self, n=6):
        """Letzte Aufnahmen, neueste zuerst, z.B. '100 · 60 · BUST (45)'."""
        if not self.throws:
            return "-"
        parts = [f"BUST ({sc})" if bust else str(sc) for sc, bust in reversed(self.throws[-n:])]
        return "  ·  ".join(parts)

    @property
    def match_average(self):
        if not self.all_scores:
            return 0.0
        return sum(self.all_scores) / len(self.all_scores)


# --------------------------------------------------------------------------
# Dialog: Neues Spiel konfigurieren
# --------------------------------------------------------------------------

class NewGameDialog(tk.Toplevel):
    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("Neues Spiel")
        self.resizable(False, False)
        self.cfg = cfg
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)
        theme.modal(self)

        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self, padding=15)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="Anzahl Spieler:").grid(row=0, column=0, sticky="w", **pad)
        self.num_players = tk.IntVar(value=2)
        num_frame = ttk.Frame(frm)
        num_frame.grid(row=0, column=1, sticky="w", **pad)
        for n in (1, 2, 3, 4):
            ttk.Radiobutton(
                num_frame, text=str(n), value=n, variable=self.num_players,
                command=self._update_name_fields
            ).pack(side="left", padx=4)

        self.name_frame = ttk.Frame(frm)
        self.name_frame.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        self.name_vars = []
        self._build_name_fields()

        ttk.Label(frm, text="Startpunktzahl:").grid(row=2, column=0, sticky="w", **pad)  # Basiswert
        self.start_score = tk.IntVar(value=cfg.get("start_score", 501))
        score_frame = ttk.Frame(frm)
        score_frame.grid(row=2, column=1, sticky="w", **pad)
        for s in (301, 501, 701):
            ttk.Radiobutton(score_frame, text=str(s), value=s, variable=self.start_score).pack(side="left", padx=4)

        self.double_out = tk.BooleanVar(value=cfg.get("double_out", True))
        ttk.Checkbutton(
            frm, text="Double-Out (Finish muss ein Doppel sein)", variable=self.double_out
        ).grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(frm, text="Legs zum Sieg (First to):").grid(row=4, column=0, sticky="w", **pad)
        self.legs_to_win = tk.IntVar(value=cfg.get("legs_to_win", 1))
        ttk.Spinbox(frm, from_=1, to=21, textvariable=self.legs_to_win, width=5).grid(
            row=4, column=1, sticky="w", **pad
        )

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=(15, 0))
        ttk.Button(btns, text="Spiel starten", style="Accent.TButton", command=self._on_start).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

        theme.bind_dialog_keys(self, ok=self._on_start)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_name_fields(self):
        for child in self.name_frame.winfo_children():
            child.destroy()
        self.name_vars = []
        self.hc_vars = []
        n = self.num_players.get()
        defaults = ["Spieler 1", "Spieler 2", "Spieler 3", "Spieler 4"]
        ttk.Label(self.name_frame, text="Vorgabe (Handicap)", style="Muted.TLabel").grid(
            row=0, column=2, columnspan=2, sticky="w", padx=(12, 0))
        for i in range(n):
            ttk.Label(self.name_frame, text=f"Name Spieler {i + 1}:").grid(row=i + 1, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=defaults[i])
            entry = ttk.Entry(self.name_frame, textvariable=var, width=22)
            entry.grid(row=i + 1, column=1, sticky="w", padx=8, pady=2)
            if i == 0:
                entry.focus_set()
                entry.selection_range(0, tk.END)
            self.name_vars.append(var)
            hc = tk.IntVar(value=0)
            ttk.Spinbox(self.name_frame, from_=0, to=MAX_HANDICAP, increment=10, textvariable=hc,
                        width=5).grid(row=i + 1, column=2, sticky="w", padx=(12, 4), pady=2)
            ttk.Label(self.name_frame, text="Punkte").grid(row=i + 1, column=3, sticky="w")
            self.hc_vars.append(hc)

    def _update_name_fields(self):
        self._build_name_fields()

    def _on_start(self):
        names = [v.get().strip() or f"Spieler {i+1}" for i, v in enumerate(self.name_vars)]
        try:
            handicaps = [max(0, int(v.get())) for v in self.hc_vars]
            check_start_scores(self.start_score.get(), handicaps)
        except (TournamentError, tk.TclError) as e:
            messagebox.showerror("Vorgabe", str(e) if isinstance(e, TournamentError)
                                 else "Bitte bei der Vorgabe eine ganze Zahl eingeben.", parent=self)
            return
        self.result = {
            "names": names,
            "handicaps": handicaps,
            "start_score": self.start_score.get(),
            "double_out": self.double_out.get(),
            "legs_to_win": max(1, self.legs_to_win.get()),
        }
        self.destroy()


# --------------------------------------------------------------------------
# Dialog: F-Tasten-Belegung bearbeiten
# --------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    def __init__(self, master, cfg, on_saved):
        super().__init__(master)
        self.title("Einstellungen - F1 bis F12 bearbeiten")
        self.resizable(False, False)
        self.cfg = cfg
        self.on_saved = on_saved
        self.transient(master)
        theme.set_window_icon(self)
        theme.modal(self)

        frm = ttk.Frame(self, padding=15)
        frm.grid(sticky="nsew")

        ttk.Label(
            frm, text="Belege F1-F12 mit häufig genutzten 3-Darts-Scores (0-180):",
            font=("", 10, "bold")
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        self.vars = []
        fkeys = cfg.get("fkeys", list(DEFAULT_FKEYS))
        for i in range(12):
            row = i // 4
            col = i % 4
            cell = ttk.Frame(frm)
            cell.grid(row=1 + row, column=col, padx=8, pady=6, sticky="w")
            ttk.Label(cell, text=f"F{i+1}:").pack(side="left")
            var = tk.StringVar(value=str(fkeys[i]))
            ttk.Entry(cell, textvariable=var, width=6).pack(side="left", padx=4)
            self.vars.append(var)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=4, pady=(15, 0))
        ttk.Button(btns, text="Speichern", style="Accent.TButton", command=self._save).pack(side="left", padx=5)
        ttk.Button(btns, text="Zurücksetzen", command=self._reset_defaults).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)
        theme.bind_dialog_keys(self, ok=self._save)

    def _reset_defaults(self):
        for var, val in zip(self.vars, DEFAULT_FKEYS):
            var.set(str(val))

    def _save(self):
        values = []
        for var in self.vars:
            try:
                v = int(var.get())
                if not (0 <= v <= 180):
                    raise ValueError
            except ValueError:
                messagebox.showerror("Ungültiger Wert", "Bitte nur Zahlen zwischen 0 und 180 eingeben.")
                return
            values.append(v)
        self.cfg["fkeys"] = values
        save_config(self.cfg)
        self.on_saved()
        self.destroy()


# --------------------------------------------------------------------------
# Dialog: Wer beginnt? (Münzwurf / Ausbullen)
# --------------------------------------------------------------------------

class StartOrderDialog(tk.Toplevel):
    """Vor dem Spiel: virtuelle Münze werfen oder ausbullen - und festlegen, wer mit dem Werfen beginnt."""

    def __init__(self, master, names):
        super().__init__(master)
        self.title("Wer beginnt?")
        self.resizable(False, False)
        self.names = list(names)
        self.result = None
        self.winner = None
        self._after = None
        self._dead = False
        self._tossing = False
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=20)
        frm.pack()
        ttk.Label(frm, text="Wer beginnt?", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        self.coin = tk.Canvas(frm, width=150, height=150, bg=theme.BG, highlightthickness=0)
        self.coin.grid(row=1, column=0, rowspan=3, padx=(0, 20), pady=(10, 0))
        self._draw_coin("🪙", 1.0)

        ttk.Label(frm, text="1. Münze werfen", font=("", 10, "bold")).grid(row=1, column=1, sticky="sw", pady=(10, 0))
        self.coin_btn = ttk.Button(frm, text="Münze werfen", command=self.toss)
        self.coin_btn.grid(row=2, column=1, sticky="w", pady=4)
        self.coin_msg = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.coin_msg, font=("", 11, "bold"), foreground=theme.RED,
                  wraplength=260).grid(row=3, column=1, sticky="nw")

        box = ttk.LabelFrame(frm, text="2. Ausbullen oder Münze entscheiden lassen - wer beginnt mit dem Werfen?",
                             padding=10)
        box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(box, text="Beim Ausbullen werfen alle auf das Bull; den Gewinner bzw. den Spieler, "
                            "der beginnen soll, hier auswählen.", style="Muted.TLabel", wraplength=420).pack(
            anchor="w", pady=(0, 6))
        self.var = tk.IntVar(value=-1)
        for i, name in enumerate(self.names):
            ttk.Radiobutton(box, text=name, value=i, variable=self.var, command=self._selected).pack(anchor="w", pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text=f"Überspringen ({self.names[0]} beginnt)", command=self._skip).pack(
            side="right", padx=(8, 0))
        self.start_btn = ttk.Button(btns, text="Los geht's", style="Accent.TButton", command=self._start,
                                    state="disabled")
        self.start_btn.pack(side="right")

        ttk.Label(frm, text="M: Münze werfen  ·  1-4: Spieler wählen  ·  ↑ ↓: wechseln  ·  Enter: los  ·  Esc: überspringen",
                  style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))
        theme.bind_dialog_keys(self, ok=self._start, cancel=self._skip)
        for k in ("m", "M", "space"):
            self.bind(f"<KeyPress-{k}>", lambda e: (self.toss(), "break")[1])
        for i in range(len(self.names)):
            self.bind(f"<KeyPress-{i + 1}>", lambda e, idx=i: self._pick(idx))
        self.protocol("WM_DELETE_WINDOW", self._skip)
        theme.modal(self)
        self.coin_btn.focus_set()

    # ---------------- Münzwurf ----------------

    def _draw_coin(self, text, width_factor):
        c = self.coin
        c.delete("all")
        r, cx, cy = 62, 75, 75
        half = max(5, r * width_factor)
        c.create_oval(cx - half, cy - r, cx + half, cy + r, fill="#e0b537", outline="#a67c00", width=4)
        if width_factor > 0.4:
            c.create_text(cx, cy, text=text, font=("", 13, "bold"), fill="#5c4300", width=int(2 * half - 14))

    def toss(self):
        if self._tossing or self._dead:
            return
        self._tossing = True
        self.winner = random.SystemRandom().randrange(len(self.names))
        self.coin_btn.configure(state="disabled")
        self.coin_msg.set("")
        self._step = 0
        self._animate()

    def _animate(self):
        if self._dead:
            return
        total = 18
        i = self._step
        if i >= total:
            self._draw_coin(self.names[self.winner], 1.0)
            self.coin_msg.set(f"{self.names[self.winner]} gewinnt den Münzwurf!")
            self.var.set(self.winner)
            self._tossing = False
            self.coin_btn.configure(state="normal", text="Nochmal werfen")
            self._selected()
            return
        self._draw_coin(self.names[i % len(self.names)], abs(math.cos(i * 0.9)))
        self._step += 1
        try:
            self._after = self.after(40 + i * 8, self._animate)
        except tk.TclError:
            pass

    # ---------------- Auswahl ----------------

    def _pick(self, idx):
        if not self._tossing:
            self.var.set(idx)
            self._selected()
        return "break"

    def _selected(self):
        self.start_btn.configure(state="normal" if self.var.get() >= 0 else "disabled")

    def _start(self):
        idx = self.var.get()
        if idx < 0 or self._tossing:
            return
        self.result = idx
        self.destroy()

    def _skip(self):
        self.result = 0
        self.destroy()

    def destroy(self):
        self._dead = True
        if self._after:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
        super().destroy()


# --------------------------------------------------------------------------
# Hauptmenü per Tastatur
# --------------------------------------------------------------------------

class MainMenuDialog(tk.Toplevel):
    def __init__(self, master, items):
        super().__init__(master)
        self.master_win = master
        self.items = items
        self.title("Menü")
        self.resizable(False, False)
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=16)
        frm.pack()
        ttk.Label(frm, text="Menü", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frm, text="↑ ↓ wählen  ·  Enter ausführen  ·  1-9 direkt  ·  Esc schließen",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.tree = ttk.Treeview(frm, columns=("group", "label", "keys"), show="headings", selectmode="browse",
                                 height=min(len(items), 14), style="Big.Treeview")
        self.tree.heading("group", text="Bereich")
        self.tree.heading("label", text="Aktion")
        self.tree.heading("keys", text="Tastenkürzel")
        self.tree.column("group", width=130)
        self.tree.column("label", width=420)
        self.tree.column("keys", width=170)
        for i, (group, label, keys, _) in enumerate(items):
            self.tree.insert("", "end", iid=str(i), values=(group, f"{i + 1}.  {label}" if i < 9 else label, keys))
        self.tree.pack()
        self.tree.selection_set("0")
        self.tree.focus("0")

        self.tree.bind("<Return>", lambda e: (self._run(), "break")[1])
        self.tree.bind("<Double-Button-1>", lambda e: self._run())
        for i in range(min(len(items), 9)):
            self.bind(f"<KeyPress-{i + 1}>", lambda e, idx=i: self._run(idx))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Menu>", lambda e: self.destroy())
        theme.modal(self)
        self.tree.focus_set()

    def _run(self, idx=None):
        if idx is None:
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
        cmd = self.items[idx][3]
        parent = self.master_win
        self.destroy()
        parent.after(80, cmd)   # erst nach dem Schließen ausführen, damit Dialoge sauber vorne landen


# --------------------------------------------------------------------------
# Hauptanwendung
# --------------------------------------------------------------------------

class DartCounterApp:
    def __init__(self, root, kiosk=True):
        self.root = root
        self.root.title("Dartcounter - TSV Feichten")
        self.root.geometry("1100x760")
        self.root.minsize(900, 640)
        theme.apply_style(self.root)
        theme.set_window_icon(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.request_quit)

        self.cfg = load_config()

        self.players = []
        self.start_score = self.cfg.get("start_score", 501)
        self.double_out = self.cfg.get("double_out", True)
        self.legs_to_win = self.cfg.get("legs_to_win", 1)
        self.current_idx = 0
        self.leg_starter_idx = 0
        self.history = []  # Undo-Stack: (player_idx, prev_score, prev_turn_scores_len)
        self.match_over = False

        # Turniermodus
        self.tourn = None          # laufendes Turnier-Match an dieser Station
        self.tournament = None     # Turnier, das dieser Rechner leitet (Server)
        self.server = None
        self.master_win = None
        self.station_panel = None

        self._build_menu()
        self._build_layout()

        self.fullscreen = False
        if kiosk:
            self._set_fullscreen(True)

        # Direkt beim Start ein neues Spiel anbieten
        self.root.after(150, self.new_game)

    # ---------------- Menü ----------------

    def _menu_structure(self):
        """(Menüname, [(Beschriftung, Tastenkürzel, Funktion) | None für Trennlinie])"""
        return [
            ("Spiel", [
                ("Neues Spiel...", "Strg+N", self.new_game),
                ("Wer beginnt? (Münzwurf / Ausbullen)...", "Strg+W", self.change_starter),
                ("Leg neu starten", "Strg+R", self.restart_leg),
                ("Letzte Eingabe rückgängig (Undo)", "Strg+Z", self.undo),
                None,
                ("Kiosk-Modus (Vollbild) ein/aus  [Passwort]", "Strg+Umschalt+K", self.toggle_kiosk),
                ("Beenden  [Passwort im Kiosk-Modus]", "Strg+Q", self.request_quit),
            ]),
            ("Turnier", [
                ("Neues Turnier erstellen  [Passwort]...", "Strg+Umschalt+N", self.new_tournament),
                ("Gespeichertes Turnier fortsetzen  [Passwort]", "Strg+Umschalt+O", self.resume_tournament),
                ("Turnierleiter-Fenster anzeigen", "Strg+Umschalt+L", self.show_master),
                None,
                ("Als Station verbinden...", "Strg+Umschalt+S", self.connect_station),
                ("Station-Fenster anzeigen", "Strg+Umschalt+P", self.show_station_panel),
            ]),
            ("Einstellungen", [
                ("F1-F12 bearbeiten...", "", self.open_settings),
                ("Turnierleiter-Passwort ändern...", "", self.change_password),
            ]),
            ("Hilfe", [
                ("Tastenkürzel", "", self.show_help),
            ]),
        ]

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        for name, entries in self._menu_structure():
            menu = tk.Menu(menubar, tearoff=0)
            for entry in entries:
                if entry is None:
                    menu.add_separator()
                else:
                    label, keys, cmd = entry
                    menu.add_command(label=label, accelerator=keys, command=cmd)
            menubar.add_cascade(label=name, menu=menu, underline=0)   # Alt+S, Alt+T, Alt+E, Alt+H
        self.root.config(menu=menubar)

    def open_main_menu(self):
        """Hauptmenü zum Durchblättern mit Pfeiltasten (für die Bedienung ohne Maus)."""
        items = [(group, label, keys, cmd) for group, entries in self._menu_structure()
                 for entry in entries if entry for (label, keys, cmd) in [entry]]
        MainMenuDialog(self.root, items)

    def show_help(self):
        messagebox.showinfo(
            "Tastenkürzel",
            "F1-F12: schnellen Turn-Score für aktuellen Spieler eintragen\n"
            "Enter: eingegebenen Zahlenwert bestätigen\n"
            "Strg+Z: letzte Eingabe rückgängig machen\n"
            "Backspace/Entf im Zahlenfeld: löscht die Eingabe\n\n"
            "Ohne Maus bedienbar:\n"
            "Esc: Hauptmenü (mit Pfeiltasten wählen, Enter, Esc)\n"
            "Strg+N: Neues Spiel   Strg+W: Wer beginnt?   Strg+R: Leg neu\n"
            "Strg+Q: Beenden   Strg+Umschalt+K: Kiosk ein/aus\n"
            "Strg+Umschalt+N / O / L: Turnier neu / fortsetzen / Leiter-Fenster\n"
            "Strg+Umschalt+S / P: Station verbinden / Station-Fenster\n"
            "Alt+S, Alt+T, Alt+E, Alt+H: Menüleiste öffnen\n"
            "In Fenstern: Tab / Pfeiltasten wechseln, Enter bestätigt, Esc bricht ab\n\n"
            "Kiosk-Modus: Menü Spiel -> Kiosk-Modus ein/aus (Passwort nötig).\n"
            "Zum Testen im Fenster starten: python3 dartcounter.py --windowed",
        )

    # ---------------- Kiosk / Sperre ----------------

    def _set_fullscreen(self, on):
        self.fullscreen = on
        try:
            self.root.attributes("-fullscreen", on)
        except tk.TclError:
            pass

    def toggle_kiosk(self):
        if self.fullscreen and not lock.ask_password(
                self.root, self.cfg, "Zum Verlassen des Kiosk-Modus ist das Passwort nötig."):
            return
        self._set_fullscreen(not self.fullscreen)

    def request_quit(self):
        if self.fullscreen:
            if not lock.ask_password(self.root, self.cfg, "Zum Beenden des Programms ist das Passwort nötig."):
                return
        elif (self.tourn or (self.master_win and self.master_win.winfo_exists())) and not messagebox.askyesno(
                "Beenden", "Es läuft noch ein Turnier bzw. Turnier-Match.\n\nProgramm trotzdem beenden?"):
            return
        self.root.quit()

    def change_password(self):
        lock.ChangePasswordDialog(self.root, self.cfg, save_config)

    def _unlock_master(self):
        if self.master_win and self.master_win.winfo_exists():
            return True
        return lock.ask_password(self.root, self.cfg, "Der Turnierleiter-Bereich ist passwortgeschützt.")

    # ---------------- Layout ----------------

    def _build_layout(self):
        outer = ttk.Frame(self.root, padding=(16, 12))
        outer.pack(fill="both", expand=True)

        # Kopfzeile: Logo + Spielinfo
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        logo = theme.load_image("logo_small.png")
        if logo:
            ttk.Label(header, image=logo).pack(side="left", padx=(0, 14))
        ttk.Button(header, text="☰  Menü  [Esc]", command=self.open_main_menu).pack(side="right")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="TSV Feichten - Dartcounter", style="Title.TLabel").pack(anchor="w")
        self.info_var = tk.StringVar(value="")
        ttk.Label(titles, textvariable=self.info_var, style="Muted.TLabel", font=("", 11)).pack(anchor="w")

        # Spieler-Panels
        self.players_container = ttk.Frame(outer)
        self.players_container.pack(fill="x", pady=(0, 10))
        self.player_widgets = []  # list of dicts mit Referenzen auf Labels je Panel

        # Checkout-Vorschlag
        self.checkout_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.checkout_var, style="Good.TLabel", font=("", 17, "bold")).pack(
            pady=(2, 10))

        # Eingabebereich
        input_frame = ttk.LabelFrame(outer, text="Score eingeben", padding=12)
        input_frame.pack(fill="x", pady=(0, 8))

        top_row = ttk.Frame(input_frame)
        top_row.pack(fill="x", pady=(0, 10))
        ttk.Label(top_row, text="Turn-Score (0-180):", font=("", 11)).pack(side="left")
        self.entry_var = tk.StringVar()
        self.entry = ttk.Entry(top_row, textvariable=self.entry_var, width=7, font=("", 16, "bold"))
        self.entry.pack(side="left", padx=10)
        ttk.Button(top_row, text="Bestätigen", style="Accent.TButton", command=self.submit_manual).pack(
            side="left", padx=4)
        ttk.Button(top_row, text="Undo  (Strg+Z)", command=self.undo).pack(side="left", padx=4)

        self.fkey_buttons_frame = ttk.Frame(input_frame)
        self.fkey_buttons_frame.pack(fill="x")
        self._build_fkey_buttons()

        self.log_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.log_var, style="Muted.TLabel").pack(fill="x")

        # Turnier-Leiste (nur sichtbar, solange an dieser Station ein Turnier-Match läuft)
        self.tourn_bar = ttk.LabelFrame(outer, text="Turnier-Match", padding=10)
        self.tourn_var = tk.StringVar(value="")
        ttk.Label(self.tourn_bar, textvariable=self.tourn_var, font=("", 12, "bold")).pack(side="left")
        ttk.Button(self.tourn_bar, text="Match abbrechen", style="Danger.TButton",
                   command=self.abort_tournament_match).pack(side="right", padx=4)
        self.send_btn = ttk.Button(self.tourn_bar, text="Ergebnis senden", style="Accent.TButton",
                                   command=self.send_tournament_result, state="disabled")
        self.send_btn.pack(side="right", padx=4)

        # Key-Bindings
        shortcuts = {
            "<Escape>": self.open_main_menu, "<Menu>": self.open_main_menu,
            "<Control-n>": self.new_game, "<Control-w>": self.change_starter, "<Control-r>": self.restart_leg,
            "<Control-q>": self.request_quit, "<Control-K>": self.toggle_kiosk,
            "<Control-N>": self.new_tournament, "<Control-O>": self.resume_tournament,
            "<Control-L>": self.show_master, "<Control-S>": self.connect_station,
            "<Control-P>": self.show_station_panel,
        }
        for seq, fn in shortcuts.items():
            self.root.bind(seq, lambda e, f=fn: (f(), "break")[1])
        self.entry.bind("<Return>", lambda e: self.submit_manual())
        for i in range(1, 13):
            self.root.bind(f"<F{i}>", lambda e, idx=i - 1: self.submit_fkey(idx))
        self.root.bind("<Control-z>", lambda e: self.undo())

    def _build_fkey_buttons(self):
        for child in self.fkey_buttons_frame.winfo_children():
            child.destroy()
        fkeys = self.cfg.get("fkeys", list(DEFAULT_FKEYS))
        self.fkey_btns = []
        for i, val in enumerate(fkeys):
            btn = ttk.Button(
                self.fkey_buttons_frame, text=f"F{i+1}\n{val}", style="Quick.TButton",
                command=lambda idx=i: self.submit_fkey(idx)
            )
            row, col = divmod(i, 6)
            self.fkey_buttons_frame.columnconfigure(col, weight=1, uniform="fkeys")
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self.fkey_btns.append(btn)

    def _rebuild_player_panels(self):
        for child in self.players_container.winfo_children():
            child.destroy()
        self.player_widgets = []
        for i, p in enumerate(self.players):
            self.players_container.columnconfigure(i, weight=1, uniform="players")
            frame = tk.Frame(self.players_container, bd=0, highlightthickness=2, highlightbackground=theme.LINE,
                             padx=12, pady=10)
            frame.grid(row=0, column=i, sticky="nsew", padx=6)

            name_lbl = tk.Label(frame, text=p.name, font=("", 16, "bold"))
            name_lbl.pack()
            score_lbl = tk.Label(frame, text=str(p.score), font=("", 54, "bold"))
            score_lbl.pack()
            sub_lbl = tk.Label(frame, text="", font=("", 11))
            sub_lbl.pack()
            caption = tk.Label(frame, text="LETZTE WÜRFE", font=("", 8, "bold"))
            caption.pack(pady=(8, 0))
            recent_lbl = tk.Label(frame, text="-", font=("", 12, "bold"), wraplength=240, justify="center")
            recent_lbl.pack()

            self.player_widgets.append({
                "frame": frame, "name": name_lbl, "score": score_lbl, "sub": sub_lbl,
                "caption": caption, "recent": recent_lbl,
            })

    # ---------------- Spiel-Steuerung ----------------

    def new_game(self):
        if self.tourn:
            messagebox.showinfo("Turnier-Match läuft",
                                "Solange ein Turnier-Match läuft, kann kein neues Spiel gestartet werden.\n"
                                "Beende oder breche das Match zuerst ab.")
            return
        dlg = NewGameDialog(self.root, self.cfg)
        self.root.wait_window(dlg)
        if not dlg.result:
            if not self.players:
                # kein Spiel konfiguriert und keins läuft -> Standardspiel mit 2 Spielern anlegen
                dlg2_result = {
                    "names": ["Spieler 1", "Spieler 2"],
                    "start_score": self.cfg.get("start_score", 501),
                    "double_out": self.cfg.get("double_out", True),
                    "legs_to_win": self.cfg.get("legs_to_win", 1),
                }
            else:
                return
        else:
            dlg2_result = dlg.result

        self.start_game(dlg2_result)

    def start_game(self, dlg2_result):
        self.start_score = dlg2_result["start_score"]
        self.double_out = dlg2_result["double_out"]
        self.legs_to_win = dlg2_result["legs_to_win"]
        if not self.tourn:
            self.cfg["start_score"] = self.start_score
            self.cfg["double_out"] = self.double_out
            self.cfg["legs_to_win"] = self.legs_to_win
            save_config(self.cfg)

        starts = dlg2_result.get("start_scores") or start_scores(
            self.start_score, dlg2_result.get("handicaps") or [0] * len(dlg2_result["names"]))
        self.players = [Player(name, sc) for name, sc in zip(dlg2_result["names"], starts)]
        for p in self.players:
            p.reset_leg()
        self.current_idx = 0
        self.leg_starter_idx = 0
        self.history = []
        self.match_over = False

        self._rebuild_player_panels()
        self.refresh()
        self.choose_starter()
        self.entry.focus_set()

    def choose_starter(self):
        """Fragt per Münzwurf bzw. Auswahl, wer mit dem Werfen beginnt (bei mehr als einem Spieler)."""
        if len(self.players) < 2:
            return
        dlg = StartOrderDialog(self.root, [p.name for p in self.players])
        self.root.wait_window(dlg)
        starter = dlg.result if dlg.result is not None else 0
        self.current_idx = self.leg_starter_idx = starter
        self.log_var.set(f"{self.players[starter].name} beginnt.")
        self.refresh()

    def change_starter(self):
        if not self.players:
            return
        if self.history:
            messagebox.showinfo("Startspieler", "Der Startspieler lässt sich nur vor dem ersten Wurf "
                                                "eines Legs bestimmen.")
            return
        self.choose_starter()

    def restart_leg(self):
        if not self.players or self.match_over:
            return
        for p in self.players:
            p.reset_leg()
        self.current_idx = self.leg_starter_idx
        self.history = []
        self.match_over = False
        self.refresh()

    def open_settings(self):
        SettingsDialog(self.root, self.cfg, self._build_fkey_buttons)

    # ---------------- Score-Eingabe ----------------

    def submit_fkey(self, idx):
        if self.match_over or not self.players:
            return
        fkeys = self.cfg.get("fkeys", list(DEFAULT_FKEYS))
        if idx >= len(fkeys):
            return
        self._apply_turn(fkeys[idx])

    def submit_manual(self):
        if self.match_over or not self.players:
            return
        raw = self.entry_var.get().strip()
        if raw == "":
            return
        try:
            val = int(raw)
        except ValueError:
            messagebox.showerror("Ungültige Eingabe", "Bitte eine ganze Zahl zwischen 0 und 180 eingeben.")
            return
        if not (0 <= val <= 180):
            messagebox.showerror("Ungültige Eingabe", "Der Turn-Score muss zwischen 0 und 180 liegen.")
            return
        self.entry_var.set("")
        self._apply_turn(val)

    def _apply_turn(self, turn_score):
        player = self.players[self.current_idx]
        prev_score = player.score
        remaining = prev_score - turn_score

        bust = False
        if remaining < 0:
            bust = True
        elif self.double_out and remaining == 1:
            bust = True

        self.history.append({
            "player_idx": self.current_idx,
            "prev_score": prev_score,
            "recorded": not bust,
            "won_leg": False,
        })
        player.throws.append((turn_score, bust))

        if bust:
            self.log_var.set(f"{player.name}: {turn_score} -> BUST! Score bleibt bei {prev_score}.")
        else:
            player.score = remaining
            player.turn_scores.append(turn_score)
            player.all_scores.append(turn_score)
            if remaining == 0:
                self.log_var.set(f"{player.name}: {turn_score} -> CHECKOUT! Leg gewonnen.")
                self._handle_leg_win(player)
                self.refresh()
                return
            else:
                self.log_var.set(f"{player.name}: {turn_score} -> verbleibend {remaining}")

        self._advance_player()
        self.refresh()

    def _handle_leg_win(self, player):
        player.legs_won += 1
        if player.legs_won >= self.legs_to_win:
            self.match_over = True
            self.history[-1]["won_leg"] = True  # Undo muss das Leg wieder abziehen
            if self.tourn:
                messagebox.showinfo(
                    "Match beendet",
                    f"🏆 {player.name} gewinnt das Match mit {player.legs_won} Leg(s)!\n\n"
                    "Mit 'Ergebnis senden' wird es in den Turnierbaum eingetragen "
                    "(vorher ist noch Undo möglich)."
                )
            else:
                messagebox.showinfo(
                    "Spielende",
                    f"🏆 {player.name} gewinnt das Spiel mit {player.legs_won} Leg(s)!"
                )
        else:
            messagebox.showinfo(
                "Leg gewonnen",
                f"🎯 {player.name} gewinnt das Leg!\nStand: " +
                ", ".join(f"{p.name} {p.legs_won}" for p in self.players)
            )
            # nächstes Leg: Startspieler rotiert
            self.leg_starter_idx = (self.leg_starter_idx + 1) % len(self.players)
            for p in self.players:
                p.reset_leg()
            self.current_idx = self.leg_starter_idx
            self.history = []

    def _advance_player(self):
        self.current_idx = (self.current_idx + 1) % len(self.players)

    def undo(self):
        if not self.history:
            return
        last = self.history.pop()
        player = self.players[last["player_idx"]]
        if player.throws:
            player.throws.pop()
        if last["recorded"]:
            player.turn_scores.pop()
            player.all_scores.pop()
        if last.get("won_leg"):
            player.legs_won -= 1
        player.score = last["prev_score"]
        self.current_idx = last["player_idx"]
        self.match_over = False
        self.log_var.set(f"Undo: {player.name} zurück auf {player.score}")
        self.refresh()

    # ---------------- Anzeige ----------------

    def refresh(self):
        if not self.players:
            return
        mode = "Double-Out" if self.double_out else "Straight-Out"
        starts = sorted({p.start_score for p in self.players}, reverse=True)
        start_txt = " / ".join(str(p.start_score) for p in self.players) + " (Handicap)" \
            if len(starts) > 1 else str(self.start_score)
        self.info_var.set(f"Start: {start_txt}  |  {mode}  |  First to {self.legs_to_win} Leg(s)")

        for i, p in enumerate(self.players):
            w = self.player_widgets[i]
            active = (i == self.current_idx) and not self.match_over
            bg = theme.RED if active else theme.CARD
            fg = "white" if active else theme.INK
            muted = "#f6d3d7" if active else theme.MUTED
            w["frame"].configure(bg=bg, highlightbackground=theme.RED if active else theme.LINE)
            w["name"].configure(bg=bg, fg=fg, text=("▶ " if active else "") + p.name)
            w["score"].configure(bg=bg, fg=fg, text=str(p.score))
            handicap = f"     Start {p.start_score}" if len({q.start_score for q in self.players}) > 1 else ""
            w["sub"].configure(bg=bg, fg=fg, text=f"Legs: {p.legs_won}     Ø {p.average:.1f}{handicap}")
            w["caption"].configure(bg=bg, fg=muted)
            w["recent"].configure(bg=bg, fg=fg, text=p.recent_text())

        if self.tourn:
            self.send_btn.configure(state="normal" if self.match_over else "disabled")

        # Checkout-Vorschlag für aktuellen Spieler
        self.checkout_var.set("")
        if not self.match_over:
            cur = self.players[self.current_idx]
            if 2 <= cur.score <= 170 or (not self.double_out and cur.score <= 180):
                route = solve_checkout(cur.score, 3, self.double_out)
                if route:
                    self.checkout_var.set(f"Checkout für {cur.name}: " + " → ".join(route))
                else:
                    self.checkout_var.set("")

    # ---------------- Turniermodus: Turnierleiter (Server) ----------------

    def show_master(self):
        if self.master_win and self.master_win.winfo_exists():
            self.master_win.deiconify()
            self.master_win.lift()
        else:
            messagebox.showinfo("Kein Turnier", "Dieser Rechner leitet gerade kein Turnier.\n"
                                "Erstelle ein neues oder setze ein gespeichertes fort.")

    def _master_running(self):
        if self.master_win and self.master_win.winfo_exists():
            messagebox.showinfo("Turnier läuft bereits",
                                "Auf diesem Rechner läuft schon ein Turnier. Schließe zuerst das "
                                "Turnierleiter-Fenster.")
            self.show_master()
            return True
        return False

    def new_tournament(self):
        if self._master_running() or not self._unlock_master():
            return
        dlg = tournament_ui.NewTournamentDialog(self.root, self.cfg)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        r = dlg.result
        if os.path.exists(TOURNAMENT_PATH) and not messagebox.askyesno(
                "Gespeichertes Turnier überschreiben?",
                "Es existiert noch ein gespeichertes Turnier. Das neue Turnier ersetzt es.\n\nFortfahren?"):
            return
        t = r["tournament"]
        self._open_master(t, r["port"])

    def resume_tournament(self):
        if self._master_running() or not self._unlock_master():
            return
        if not os.path.exists(TOURNAMENT_PATH):
            messagebox.showinfo("Kein gespeichertes Turnier", "Es gibt noch kein gespeichertes Turnier.")
            return
        try:
            t = Tournament.load()
        except TournamentError as e:
            messagebox.showerror("Turnier", str(e))
            return
        self._open_master(t, self.cfg.get("tournament_port", DEFAULT_PORT))

    def _open_master(self, t, port):
        t.on_change = t.save
        try:
            server = TournamentServer(t, port=port)
        except OSError as e:
            messagebox.showerror("Server konnte nicht starten",
                                 f"Port {port} ist nicht nutzbar ({e}).\nIst schon ein Turnier-Server aktiv?")
            return
        server.start()
        t.save()
        self.cfg["tournament_port"] = port
        save_config(self.cfg)
        self.tournament, self.server = t, server
        self.master_win = tournament_ui.MasterWindow(self.root, t, server, self._master_closed)

    def _master_closed(self):
        if self.server:
            self.server.stop()
        self.server = self.tournament = None

    # ---------------- Turniermodus: Station ----------------

    def connect_station(self):
        if self.station_panel and self.station_panel.winfo_exists():
            self.show_station_panel()
            return
        dlg = tournament_ui.ConnectDialog(self.root, self.cfg)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        r = dlg.result
        client = TournamentClient(r["host"], r["port"], r["station"])

        def done(state, err):
            if err:
                messagebox.showerror("Verbindung fehlgeschlagen", str(err))
                return
            self.cfg["tournament_host"] = r["host"]
            self.cfg["tournament_port"] = r["port"]
            self.cfg["tournament_station"] = r["station"]
            save_config(self.cfg)
            self.station_panel = tournament_ui.StationPanel(self.root, self, client, state)

        tournament_ui.run_async(self.root, client.state, done)

    def show_station_panel(self):
        if self.station_panel and self.station_panel.winfo_exists():
            self.station_panel.deiconify()
            self.station_panel.lift()
        else:
            messagebox.showinfo("Keine Verbindung", "Dieser Rechner ist mit keinem Turnier verbunden.")

    def start_tournament_match(self, client, info):
        """Wird vom Station-Fenster aufgerufen, nachdem das Match erfolgreich abgeholt wurde."""
        self.tourn = {"client": client, "info": info, "sending": False}
        self.tourn_var.set(f"{info['label']}  -  Station {client.station}")
        self.tourn_bar.pack(fill="x", pady=(8, 0))
        self.start_game({
            "names": info["players"],
            "start_scores": info.get("starts"),
            "start_score": info["start_score"],
            "double_out": info["double_out"],
            "legs_to_win": info["legs_to_win"],
        })
        self.root.lift()

    def _end_tournament_match(self):
        self.tourn = None
        self.tourn_bar.pack_forget()
        if self.station_panel and self.station_panel.winfo_exists():
            self.station_panel.deiconify()
            self.station_panel.lift()
            self.station_panel.refresh_now()
            self.station_panel.focus_tree()

    def send_tournament_result(self):
        if not self.tourn or not self.match_over or self.tourn["sending"]:
            return
        winner = max(self.players, key=lambda p: p.legs_won)
        legs = [p.legs_won for p in self.players]
        avg = [round(p.match_average, 2) for p in self.players]
        client, info = self.tourn["client"], self.tourn["info"]
        self.tourn["sending"] = True
        self.send_btn.configure(state="disabled")

        def done(_, err):
            if err:
                self.tourn["sending"] = False
                self.send_btn.configure(state="normal")
                messagebox.showerror("Senden fehlgeschlagen",
                                     f"{err}\n\nDas Ergebnis ist noch hier gespeichert - "
                                     "bitte erneut auf 'Ergebnis senden' klicken.")
                return
            messagebox.showinfo("Ergebnis übermittelt",
                                f"{winner.name} wurde als Sieger in den Turnierbaum eingetragen.")
            self._end_tournament_match()

        tournament_ui.run_async(
            self.root, lambda: client.report(info["match_id"], winner.name, legs, avg), done)

    def abort_tournament_match(self):
        if not self.tourn or self.tourn["sending"]:
            return
        if not messagebox.askyesno("Match abbrechen",
                                   "Das Match wird abgebrochen und wieder für alle Stationen freigegeben. "
                                   "Der bisherige Spielstand geht verloren.\n\nWirklich abbrechen?"):
            return
        client, info = self.tourn["client"], self.tourn["info"]

        def done(_, err):
            if err:
                messagebox.showwarning("Server nicht erreichbar",
                                       f"{err}\n\nDas Match ist beim Turnierleiter evtl. noch als 'läuft' "
                                       "markiert - dort kann es manuell freigegeben werden.")
            self._end_tournament_match()

        tournament_ui.run_async(self.root, lambda: client.release(info["match_id"]), done)


def main():
    kiosk = "--windowed" not in sys.argv
    root = tk.Tk()
    DartCounterApp(root, kiosk=kiosk)
    root.mainloop()


if __name__ == "__main__":
    main()
