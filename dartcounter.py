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
- Turniermodus (KO-Baum): ein Rechner ist Turnierleiter + Server, beliebig viele
  Stationen (z.B. 6 Rechner) holen sich Matches und melden Ergebnisse automatisch
- Einstellungen werden unter ~/.config/dartcounter/config.json gespeichert

Start:
    python3 dartcounter.py

Benötigt:
    sudo apt install python3-tk   (falls tkinter noch nicht installiert ist)
"""

import json
import os
from functools import lru_cache
import tkinter as tk
from tkinter import ttk, messagebox

from tournament import TOURNAMENT_PATH, DEFAULT_PORT, Tournament, TournamentClient, \
    TournamentError, TournamentServer
import tournament_ui

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
    def __init__(self, name):
        self.name = name
        self.score = 501
        self.legs_won = 0
        self.turn_scores = []  # alle Turn-Scores dieses Legs (für Average)
        self.all_scores = []   # alle Turn-Scores des ganzen Spiels/Matches

    def reset_leg(self, start_score):
        self.score = start_score
        self.turn_scores = []

    @property
    def average(self):
        if not self.turn_scores:
            return 0.0
        return sum(self.turn_scores) / len(self.turn_scores)

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
        self.grab_set()

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

        ttk.Label(frm, text="Startpunktzahl:").grid(row=2, column=0, sticky="w", **pad)
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
        ttk.Button(btns, text="Spiel starten", command=self._on_start).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

        self.bind("<Return>", lambda e: self._on_start())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_name_fields(self):
        for child in self.name_frame.winfo_children():
            child.destroy()
        self.name_vars = []
        n = self.num_players.get()
        defaults = ["Spieler 1", "Spieler 2", "Spieler 3", "Spieler 4"]
        for i in range(n):
            ttk.Label(self.name_frame, text=f"Name Spieler {i + 1}:").grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=defaults[i])
            entry = ttk.Entry(self.name_frame, textvariable=var, width=22)
            entry.grid(row=i, column=1, sticky="w", padx=8, pady=2)
            if i == 0:
                entry.focus_set()
                entry.selection_range(0, tk.END)
            self.name_vars.append(var)

    def _update_name_fields(self):
        self._build_name_fields()

    def _on_start(self):
        names = [v.get().strip() or f"Spieler {i+1}" for i, v in enumerate(self.name_vars)]
        self.result = {
            "names": names,
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
        self.grab_set()

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
        ttk.Button(btns, text="Speichern", command=self._save).pack(side="left", padx=5)
        ttk.Button(btns, text="Zurücksetzen", command=self._reset_defaults).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

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
# Hauptanwendung
# --------------------------------------------------------------------------

class DartCounterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dartcounter")
        self.root.geometry("980x640")
        self.root.minsize(860, 560)

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

        # Direkt beim Start ein neues Spiel anbieten
        self.root.after(150, self.new_game)

    # ---------------- Menü ----------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        game_menu = tk.Menu(menubar, tearoff=0)
        game_menu.add_command(label="Neues Spiel...", command=self.new_game)
        game_menu.add_command(label="Leg neu starten", command=self.restart_leg)
        game_menu.add_separator()
        game_menu.add_command(label="Beenden", command=self.root.quit)
        menubar.add_cascade(label="Spiel", menu=game_menu)

        tourn_menu = tk.Menu(menubar, tearoff=0)
        tourn_menu.add_command(label="Neues Turnier erstellen (Turnierleiter)...", command=self.new_tournament)
        tourn_menu.add_command(label="Gespeichertes Turnier fortsetzen", command=self.resume_tournament)
        tourn_menu.add_command(label="Turnierleiter-Fenster anzeigen", command=self.show_master)
        tourn_menu.add_separator()
        tourn_menu.add_command(label="Als Station verbinden...", command=self.connect_station)
        tourn_menu.add_command(label="Station-Fenster anzeigen", command=self.show_station_panel)
        menubar.add_cascade(label="Turnier", menu=tourn_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="F1-F12 bearbeiten...", command=self.open_settings)
        menubar.add_cascade(label="Einstellungen", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Tastenkürzel", command=self.show_help)
        menubar.add_cascade(label="Hilfe", menu=help_menu)

        self.root.config(menu=menubar)

    def show_help(self):
        messagebox.showinfo(
            "Tastenkürzel",
            "F1-F12: schnellen Turn-Score für aktuellen Spieler eintragen\n"
            "Enter: eingegebenen Zahlenwert bestätigen\n"
            "Strg+Z: letzte Eingabe rückgängig machen\n"
            "Backspace/Entf im Zahlenfeld: löscht die Eingabe",
        )

    # ---------------- Layout ----------------

    def _build_layout(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Player.TFrame", background="#1e1e1e")
        style.configure("PlayerActive.TFrame", background="#2d5a2d")

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # Kopfzeile: Spielinfo
        self.info_var = tk.StringVar(value="")
        info_label = ttk.Label(outer, textvariable=self.info_var, font=("", 13, "bold"))
        info_label.pack(fill="x", pady=(0, 10))

        # Spieler-Panels
        self.players_container = ttk.Frame(outer)
        self.players_container.pack(fill="x", pady=(0, 10))
        self.player_widgets = []  # list of dicts mit Referenzen auf Labels je Panel

        # Checkout-Vorschlag
        self.checkout_var = tk.StringVar(value="")
        checkout_label = ttk.Label(
            outer, textvariable=self.checkout_var, font=("", 16, "bold"), foreground="#2a7a2a"
        )
        checkout_label.pack(pady=(5, 10))

        # Eingabebereich
        input_frame = ttk.LabelFrame(outer, text="Score eingeben", padding=10)
        input_frame.pack(fill="x", pady=(0, 10))

        top_row = ttk.Frame(input_frame)
        top_row.pack(fill="x", pady=(0, 8))
        ttk.Label(top_row, text="Turn-Score (0-180):").pack(side="left")
        self.entry_var = tk.StringVar()
        self.entry = ttk.Entry(top_row, textvariable=self.entry_var, width=8, font=("", 12))
        self.entry.pack(side="left", padx=8)
        ttk.Button(top_row, text="Bestätigen (Enter)", command=self.submit_manual).pack(side="left", padx=4)
        ttk.Button(top_row, text="Undo (Strg+Z)", command=self.undo).pack(side="left", padx=4)

        self.fkey_buttons_frame = ttk.Frame(input_frame)
        self.fkey_buttons_frame.pack(fill="x")
        self._build_fkey_buttons()

        self.log_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.log_var, foreground="#666").pack(fill="x")

        # Turnier-Leiste (nur sichtbar, solange an dieser Station ein Turnier-Match läuft)
        self.tourn_bar = ttk.LabelFrame(outer, text="Turnier-Match", padding=8)
        self.tourn_var = tk.StringVar(value="")
        ttk.Label(self.tourn_bar, textvariable=self.tourn_var, font=("", 11, "bold")).pack(side="left")
        ttk.Button(self.tourn_bar, text="Match abbrechen", command=self.abort_tournament_match).pack(
            side="right", padx=4)
        self.send_btn = ttk.Button(self.tourn_bar, text="Ergebnis senden", command=self.send_tournament_result,
                                   state="disabled")
        self.send_btn.pack(side="right", padx=4)

        # Key-Bindings
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
                self.fkey_buttons_frame, text=f"F{i+1}: {val}",
                command=lambda idx=i: self.submit_fkey(idx), width=10
            )
            row, col = divmod(i, 6)
            btn.grid(row=row, column=col, padx=4, pady=4)
            self.fkey_btns.append(btn)

    def _rebuild_player_panels(self):
        for child in self.players_container.winfo_children():
            child.destroy()
        self.player_widgets = []
        n = len(self.players)
        for i, p in enumerate(self.players):
            self.players_container.columnconfigure(i, weight=1)
            frame = tk.Frame(self.players_container, bd=2, relief="ridge", padx=10, pady=8)
            frame.grid(row=0, column=i, sticky="nsew", padx=5)

            name_lbl = tk.Label(frame, text=p.name, font=("", 13, "bold"))
            name_lbl.pack()
            score_lbl = tk.Label(frame, text=str(p.score), font=("", 34, "bold"))
            score_lbl.pack()
            sub_lbl = tk.Label(frame, text="", font=("", 10))
            sub_lbl.pack()

            self.player_widgets.append({
                "frame": frame, "name": name_lbl, "score": score_lbl, "sub": sub_lbl
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

        self.players = [Player(name) for name in dlg2_result["names"]]
        for p in self.players:
            p.reset_leg(self.start_score)
        self.current_idx = 0
        self.leg_starter_idx = 0
        self.history = []
        self.match_over = False

        self._rebuild_player_panels()
        self.refresh()
        self.entry.focus_set()

    def restart_leg(self):
        if not self.players or self.match_over:
            return
        for p in self.players:
            p.reset_leg(self.start_score)
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
                p.reset_leg(self.start_score)
            self.current_idx = self.leg_starter_idx
            self.history = []

    def _advance_player(self):
        self.current_idx = (self.current_idx + 1) % len(self.players)

    def undo(self):
        if not self.history:
            return
        last = self.history.pop()
        player = self.players[last["player_idx"]]
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
        self.info_var.set(
            f"Start: {self.start_score}  |  {mode}  |  First to {self.legs_to_win} Leg(s)"
        )

        for i, p in enumerate(self.players):
            w = self.player_widgets[i]
            active = (i == self.current_idx) and not self.match_over
            bg = "#2d5a2d" if active else "#f0f0f0"
            fg = "white" if active else "black"
            w["frame"].configure(bg=bg)
            w["name"].configure(bg=bg, fg=fg, text=("▶ " if active else "") + p.name)
            w["score"].configure(bg=bg, fg=fg, text=str(p.score))
            w["sub"].configure(
                bg=bg, fg=fg,
                text=f"Legs: {p.legs_won}   Ø {p.average:.1f}"
            )

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
        if self._master_running():
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
        try:
            t = Tournament(r["name"], r["players"], r["start_score"], r["double_out"],
                           r["legs_to_win"], r["final_legs_to_win"], r["stations"], r["shuffle"])
        except TournamentError as e:
            messagebox.showerror("Turnier", str(e))
            return
        self._open_master(t, r["port"])

    def resume_tournament(self):
        if self._master_running():
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
    root = tk.Tk()
    app = DartCounterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
