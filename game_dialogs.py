"""Dialoge des Spiels: neues Spiel, Einstellungen, Wer beginnt, Hauptmenü, Dart-Abfrage, Statistik."""

import math
import random
import tkinter as tk
from tkinter import ttk, messagebox

import theme
import config
from config import DEFAULT_FKEYS, SCORE_KEYS
from tournament import MAX_HANDICAP, TournamentError, check_start_scores, start_scores

MAX_PLAYERS = 4


# --------------------------------------------------------------------------
# Dialog: Neues Spiel konfigurieren
# --------------------------------------------------------------------------

class NewGameDialog(tk.Toplevel):
    """Neues Spiel. Namen und Handicaps des letzten Spiels bleiben vorausgefüllt."""

    HANDICAP_HELP = (
        "So funktioniert das Handicap: Ein schwächerer Spieler bekommt eine Vorgabe in Punkten und muss "
        "dadurch weniger Punkte werfen. Wer die kleinste Vorgabe hat, startet mit der vollen Punktzahl - "
        "alle anderen starten um den Unterschied niedriger.\n"
        "Beispiel: Startpunktzahl 501, Anna 0 und Ben 100  ->  Anna startet mit 501, Ben mit 401."
    )

    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("Neues Spiel")
        self.cfg = cfg
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)

        names = list(cfg.get("last_names") or [])
        hcs = list(cfg.get("last_handicaps") or [])
        count = cfg.get("last_players") or len(names) or 2
        count = max(1, min(MAX_PLAYERS, int(count)))

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=18)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="Wie viele Spieler?", font=("", 11, "bold")).grid(row=0, column=0, sticky="w", **pad)
        self.num_players = tk.IntVar(value=count)
        num_frame = ttk.Frame(frm)
        num_frame.grid(row=0, column=1, sticky="w", **pad)
        for n in range(1, MAX_PLAYERS + 1):
            ttk.Radiobutton(num_frame, text=str(n), value=n, variable=self.num_players,
                            command=self._players_changed).pack(side="left", padx=6)

        # ---- Spielerzeilen (alle vier werden einmal gebaut; ausgeblendet bleiben ihre Eingaben erhalten)
        self.players_frame = ttk.Frame(frm)
        self.players_frame.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        self.name_vars = [tk.StringVar(value=names[i] if i < len(names) and names[i] else f"Spieler {i + 1}")
                          for i in range(MAX_PLAYERS)]
        self.hc_vars = [tk.IntVar(value=int(hcs[i]) if i < len(hcs) else 0) for i in range(MAX_PLAYERS)]
        self.use_hc = tk.BooleanVar(value=any(int(h) > 0 for h in hcs[:count]))
        self.rows = []
        self.hc_head = [
            ttk.Label(self.players_frame, text="Vorgabe in Punkten", style="Muted.TLabel"),
            ttk.Label(self.players_frame, text="Das ergibt", style="Muted.TLabel"),
        ]
        for i in range(MAX_PLAYERS):
            label = ttk.Label(self.players_frame, text=f"Spieler {i + 1}:")
            entry = ttk.Entry(self.players_frame, textvariable=self.name_vars[i], width=22, font=("", 11))
            spin = theme.num_spinbox(self.players_frame, self.hc_vars[i], 0, MAX_HANDICAP, width=5, increment=10)
            spin.configure(command=self._update_preview)
            spin.bind("<KeyRelease>", lambda e: self._update_preview())
            preview = ttk.Label(self.players_frame, text="", font=("", 10, "bold"))
            self.rows.append((label, entry, spin, preview))

        ttk.Label(frm, text="Startpunktzahl:", font=("", 11, "bold")).grid(row=2, column=0, sticky="w", **pad)
        self.start_score = tk.IntVar(value=cfg.get("start_score", 501))
        score_frame = ttk.Frame(frm)
        score_frame.grid(row=2, column=1, sticky="w", **pad)
        for s in (301, 501, 701):
            ttk.Radiobutton(score_frame, text=str(s), value=s, variable=self.start_score,
                            command=self._update_preview).pack(side="left", padx=6)

        self.double_out = tk.BooleanVar(value=cfg.get("double_out", True))
        ttk.Checkbutton(frm, text="Double-Out (das Finish muss mit einem Doppel erfolgen)",
                        variable=self.double_out).grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(frm, text="Legs zum Sieg (First to):", font=("", 11, "bold")).grid(row=4, column=0, sticky="w", **pad)
        self.legs_to_win = tk.IntVar(value=cfg.get("legs_to_win", 1))
        theme.num_spinbox(frm, self.legs_to_win, 1, 21).grid(row=4, column=1, sticky="w", **pad)

        # ---- Handicap
        ttk.Checkbutton(frm, text="Mit Handicap spielen (Vorgabe für schwächere Spieler)",
                        variable=self.use_hc, command=self._handicap_toggled).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad)
        self.help_lbl = ttk.Label(frm, text=self.HANDICAP_HELP, style="Muted.TLabel", wraplength=560, justify="left")
        self.help_lbl.grid(row=6, column=0, columnspan=2, sticky="w", padx=28, pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=2, pady=(14, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Spiel starten", style="Accent.TButton", command=self._on_start).pack(side="right")

        theme.bind_dialog_keys(self, ok=self._on_start)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._layout_rows()
        theme.place_dialog(self)
        theme.modal(self)
        self.rows[0][1].focus_set()
        self.rows[0][1].selection_range(0, tk.END)

    # ---------------- Anzeige ----------------

    def _layout_rows(self):
        n = self.num_players.get()
        hc = self.use_hc.get()
        self.hc_head[0].grid_remove()
        self.hc_head[1].grid_remove()
        if hc:
            self.hc_head[0].grid(row=0, column=2, sticky="w", padx=(16, 4))
            self.hc_head[1].grid(row=0, column=3, sticky="w", padx=(10, 0))
        for i, (label, entry, spin, preview) in enumerate(self.rows):
            if i < n:
                label.grid(row=i + 1, column=0, sticky="w", pady=3)
                entry.grid(row=i + 1, column=1, sticky="w", padx=8, pady=3)
                if hc:
                    spin.grid(row=i + 1, column=2, sticky="w", padx=(16, 4), pady=3)
                    preview.grid(row=i + 1, column=3, sticky="w", padx=(10, 0))
                else:
                    spin.grid_remove()
                    preview.grid_remove()
            else:
                for w in (label, entry, spin, preview):
                    w.grid_remove()
        if hc:
            self.help_lbl.grid()
        else:
            self.help_lbl.grid_remove()
        self._update_preview()

    def _players_changed(self):
        self._layout_rows()
        theme.place_dialog(self)   # Fenster an die neue Zahl der Spielerzeilen anpassen

    def _handicap_toggled(self):
        self._layout_rows()
        theme.place_dialog(self)

    def _handicaps(self):
        n = self.num_players.get()
        if not self.use_hc.get():
            return [0] * n
        return [theme.get_int(self.hc_vars[i], 0, 0, MAX_HANDICAP) for i in range(n)]

    def _update_preview(self):
        base = theme.get_int(self.start_score, 501)
        hcs = self._handicaps()
        starts = start_scores(base, hcs)
        for i, (_, _, _, preview) in enumerate(self.rows[:len(hcs)]):
            if starts[i] < 2:
                preview.configure(text="zu hoch!", foreground="#b00020")
            else:
                preview.configure(text=f"startet mit {starts[i]}", foreground=theme.GREEN)

    # ---------------- Start ----------------

    def _on_start(self):
        n = self.num_players.get()
        names = [self.name_vars[i].get().strip() or f"Spieler {i + 1}" for i in range(n)]
        if len({x.casefold() for x in names}) < n:
            messagebox.showerror("Namen", "Jeder Spieler braucht einen eigenen Namen.", parent=self)
            return
        handicaps = self._handicaps()
        base = theme.get_int(self.start_score, 501)
        try:
            check_start_scores(base, handicaps)
        except TournamentError as e:
            messagebox.showerror("Vorgabe", str(e), parent=self)
            return
        self.result = {
            "names": names,
            "handicaps": handicaps,
            "start_score": base,
            "double_out": self.double_out.get(),
            "legs_to_win": theme.get_int(self.legs_to_win, 1, 1, 21),
        }
        self.destroy()


# --------------------------------------------------------------------------
# Dialog: F-Tasten-Belegung bearbeiten
# --------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    def __init__(self, master, cfg, on_saved):
        super().__init__(master)
        self.title("Einstellungen - Schnell-Scores (F1 bis F8)")
        self.cfg = cfg
        self.on_saved = on_saved
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=18)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Schnell-Scores für F1 bis F8 (Punkte einer Aufnahme, 0-180):",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        self.vars = []
        fkeys = cfg.get("fkeys", list(DEFAULT_FKEYS))
        for i in range(SCORE_KEYS):
            cell = ttk.Frame(frm)
            cell.grid(row=1 + i // 4, column=i % 4, padx=8, pady=6, sticky="w")
            ttk.Label(cell, text=f"F{i + 1}:", font=("", 11, "bold")).pack(side="left")
            var = tk.StringVar(value=str(fkeys[i]))
            theme.digits_only(ttk.Entry(cell, textvariable=var, width=6, font=("", 12)), maxlen=3).pack(
                side="left", padx=4)
            self.vars.append(var)

        ttk.Label(frm, style="Muted.TLabel", justify="left", wraplength=520, text=(
            "Fest belegt (nicht änderbar):\n"
            "F9 oder R  =  Rest (Restpunktzahl statt der geworfenen Punkte eingeben)\n"
            "F10 / F11 / F12 oder Strg+1 / Strg+2 / Strg+3  =  Finish mit 1 / 2 / 3 Darts")).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=4, pady=(15, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Zurücksetzen", command=self._reset_defaults).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Speichern", style="Accent.TButton", command=self._save).pack(side="right")
        theme.bind_dialog_keys(self, ok=self._save)
        theme.place_dialog(self)
        theme.modal(self)

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
                messagebox.showerror("Ungültiger Wert", "Bitte nur Zahlen zwischen 0 und 180 eingeben.", parent=self)
                return
            values.append(v)
        self.cfg["fkeys"] = values
        config.save_config(self.cfg)
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
        theme.place_dialog(self)
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
        theme.place_dialog(self)
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
# Abfrage: Mit wie vielen Darts wurde ausgecheckt?
# --------------------------------------------------------------------------

class DartsDialog(tk.Toplevel):
    def __init__(self, master, name, score, options):
        super().__init__(master)
        self.title("Finish")
        self.result = None
        self.options = list(options)
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=24)
        frm.pack()
        ttk.Label(frm, text=f"{name} checkt {score} aus!", style="Title.TLabel").pack()
        ttk.Label(frm, text="Mit wie vielen Darts?", font=("", 14)).pack(pady=(4, 14))
        row = ttk.Frame(frm)
        row.pack()
        self.buttons = {}
        for d in (1, 2, 3):
            b = ttk.Button(row, text=f"{d} Dart{'s' if d > 1 else ''}\n[ {d} ]", style="Finish.TButton",
                           command=lambda d=d: self._choose(d), width=11,
                           state="normal" if d in self.options else "disabled")
            b.pack(side="left", padx=8)
            self.buttons[d] = b
        ttk.Label(frm, text="1 / 2 / 3: Anzahl wählen   ·   Esc: Eingabe abbrechen", style="Muted.TLabel").pack(
            pady=(14, 0))

        for d in (1, 2, 3):
            for key in (str(d), f"KP_{d}"):
                self.bind(f"<KeyPress-{key}>", lambda e, d=d: (self._choose(d), "break")[1])
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        theme.place_dialog(self)
        theme.modal(self)
        first = next((self.buttons[d] for d in (1, 2, 3) if d in self.options), None)
        if first:
            first.focus_set()

    def _choose(self, d):
        if d in self.options:
            self.result = d
            self.destroy()


# --------------------------------------------------------------------------
# Übersicht nach dem Spiel
# --------------------------------------------------------------------------

STAT_ROWS = [
    ("Legs gewonnen", lambda s: str(s["legs_won"])),
    ("Ø 3-Dart-Average", lambda s: f"{s['avg']:.2f}"),
    ("Ø erste 9 Darts", lambda s: f"{s['first9']:.2f}"),
    ("Darts geworfen", lambda s: str(s["darts"])),
    ("Höchste Aufnahme", lambda s: str(s["highest"])),
    ("180er", lambda s: str(s["n180"])),
    ("140+ (140-179)", lambda s: str(s["n140"])),
    ("100+ (100-139)", lambda s: str(s["n100"])),
    ("Höchstes Finish", lambda s: str(s["best_finish"]) if s["best_finish"] else "-"),
    ("Bestes Leg (Darts)", lambda s: str(s["best_leg"]) if s["best_leg"] else "-"),
    ("Busts", lambda s: str(s["busts"])),
]


class StatsDialog(tk.Toplevel):
    """Statistik nach dem Spiel. result: 'rematch' | 'new' | 'close'."""

    def __init__(self, master, players, winner, tournament=False):
        super().__init__(master)
        self.title("Spielende - Statistik")
        self.result = "close"
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=20)
        frm.pack()
        ttk.Label(frm, text=f"🏆  {winner.name} gewinnt!", style="Title.TLabel").pack(anchor="w")
        score = "  :  ".join(str(p.legs_won) for p in players)
        ttk.Label(frm, text=f"Endstand (Legs):  {score}", font=("", 12), style="Muted.TLabel").pack(
            anchor="w", pady=(2, 10))

        cols = ["stat"] + [f"p{i}" for i in range(len(players))]
        tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="none", height=len(STAT_ROWS),
                            style="Stats.Treeview")
        tree.heading("stat", text="")
        tree.column("stat", width=210, anchor="w")
        for i, p in enumerate(players):
            tree.heading(f"p{i}", text=("🏆 " if p is winner else "") + p.name)
            tree.column(f"p{i}", width=150, anchor="center")
        stats = [p.stats() for p in players]
        for label, fmt in STAT_ROWS:
            tree.insert("", "end", values=[label] + [fmt(s) for s in stats])
        tree.pack()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(16, 0))
        if tournament:
            ttk.Label(btns, text="Mit 'Ergebnis senden' wird das Match in den Turnierbaum eingetragen.",
                      style="Muted.TLabel").pack(side="left")
            self.main_btn = ttk.Button(btns, text="Weiter  [Enter]", style="Accent.TButton",
                                       command=lambda: self._finish("close"))
            self.main_btn.pack(side="right")
            theme.bind_dialog_keys(self, ok=lambda: self._finish("close"), cancel=lambda: self._finish("close"))
        else:
            ttk.Button(btns, text="Schließen  [Esc]", command=lambda: self._finish("close")).pack(side="right")
            ttk.Button(btns, text="Neues Spiel...  [N]", command=lambda: self._finish("new")).pack(
                side="right", padx=8)
            self.main_btn = ttk.Button(btns, text="Revanche  [R / Enter]", style="Accent.TButton",
                                       command=lambda: self._finish("rematch"))
            self.main_btn.pack(side="right")
            ttk.Label(frm, text="Revanche = gleiche Spieler und Einstellungen, neues Spiel.   "
                                "Neues Spiel = Namen und Handicap bleiben zum Ändern stehen.",
                      style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
            theme.bind_dialog_keys(self, ok=lambda: self._finish("rematch"), cancel=lambda: self._finish("close"))
            for k in ("r", "R"):
                self.bind(f"<KeyPress-{k}>", lambda e: (self._finish("rematch"), "break")[1])
            for k in ("n", "N"):
                self.bind(f"<KeyPress-{k}>", lambda e: (self._finish("new"), "break")[1])
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish("close"))
        theme.place_dialog(self)
        theme.modal(self)
        self.main_btn.focus_set()

    def _finish(self, result):
        self.result = result
        self.destroy()
