"""Oberfläche der Minispiele: Auswahl-Dialog, Spielbildschirm und Endstand."""

import tkinter as tk
from tkinter import ttk, messagebox

import theme
from engine import chip_kind
from game_dialogs import MainMenuDialog
from minigames import GAMES, GAME_BY_KEY, create_game

MAX_PLAYERS = 4
STYLE_BY_KIND = {"": "Quick.TButton", "good": "Finish.TButton", "bad": "MiniBad.TButton",
                 "triple": "MiniTriple.TButton", "double": "Rest.TButton"}


def key_hint(keys):
    """Anzeige der Tasten einer Eingabe, z. B. ('1t',) -> '1 T',  ('j', '1') -> 'J / 1'."""
    def one(k):
        return f"{k[0]} {k[1:].upper()}" if len(k) == 2 and k[0].isdigit() else k.upper()
    return " / ".join(one(k) for k in keys)


# --------------------------------------------------------------------------
# Auswahl
# --------------------------------------------------------------------------

class MiniGameSetupDialog(tk.Toplevel):
    """Spiel, Spieler und Optionen wählen. result: {'key', 'names', 'options'} oder None."""

    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("Minispiele")
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)
        self.cfg = cfg

        outer = ttk.Frame(self, padding=18)
        outer.pack()
        ttk.Label(outer, text="Minispiele", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(outer, text="↑ ↓ Spiel wählen  ·  Tab: weiter  ·  Enter: starten  ·  Esc: abbrechen",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # ---- links: Spiele
        self.tree = ttk.Treeview(outer, columns=("title", "summary"), show="headings", selectmode="browse",
                                 height=len(GAMES), style="Stats.Treeview")
        self.tree.heading("title", text="Spiel")
        self.tree.heading("summary", text="Kurzbeschreibung")
        self.tree.column("title", width=170)
        self.tree.column("summary", width=360)
        for g in GAMES:
            self.tree.insert("", "end", iid=g.key, values=(g.title, g.summary))
        self.tree.grid(row=2, column=0, sticky="n", padx=(0, 18))
        start_key = cfg.get("last_minigame") if cfg.get("last_minigame") in GAME_BY_KEY else GAMES[0].key
        self.tree.selection_set(start_key)
        self.tree.focus(start_key)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._game_changed())

        # ---- rechts: Spieler + Optionen
        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="n")
        names = list(cfg.get("last_names") or [])
        count = max(1, min(MAX_PLAYERS, int(cfg.get("last_players") or len(names) or 2)))
        ttk.Label(right, text="Spieler", font=("", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.count = tk.IntVar(value=count)
        cf = ttk.Frame(right)
        cf.grid(row=0, column=1, sticky="w", padx=(10, 0))
        for n in range(1, MAX_PLAYERS + 1):
            ttk.Radiobutton(cf, text=str(n), value=n, variable=self.count, command=self._count_changed).pack(
                side="left", padx=5)
        self.name_vars = [tk.StringVar(value=names[i] if i < len(names) and names[i] else f"Spieler {i + 1}")
                          for i in range(MAX_PLAYERS)]
        self.name_entries = []
        for i in range(MAX_PLAYERS):
            e = ttk.Entry(right, textvariable=self.name_vars[i], width=24, font=("", 11))
            e.grid(row=1 + i, column=0, columnspan=2, sticky="w", pady=3)
            self.name_entries.append(e)
        self.opt_frame = ttk.LabelFrame(right, text="Optionen", padding=8)
        self.opt_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.rules_lbl = ttk.Label(right, text="", style="Muted.TLabel", wraplength=330, justify="left")
        self.rules_lbl.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

        btns = ttk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Abbrechen  [Esc]", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Spiel starten  [Enter]", style="Accent.TButton", command=self._start).pack(side="right")

        theme.bind_dialog_keys(self, ok=self._start)
        self.opt_vars = {}
        self._count_changed()
        self._game_changed()
        theme.modal(self)
        self.tree.focus_set()

    def _selected_class(self):
        sel = self.tree.selection()
        return GAME_BY_KEY[sel[0]] if sel else GAMES[0]

    def _count_changed(self):
        n = self.count.get()
        for i, e in enumerate(self.name_entries):
            if i < n:
                e.grid()
            else:
                e.grid_remove()

    def _game_changed(self):
        cls = self._selected_class()
        for child in self.opt_frame.winfo_children():
            child.destroy()
        self.opt_vars = {}
        for r, spec in enumerate(cls.options_spec):
            ttk.Label(self.opt_frame, text=spec["label"], font=("", 10, "bold")).grid(row=2 * r, column=0,
                                                                                      sticky="w", pady=(4, 0))
            default_idx = next((i for i, (_, v) in enumerate(spec["choices"]) if v == spec["default"]), 0)
            var = tk.IntVar(value=default_idx)
            self.opt_vars[spec["key"]] = var
            row = ttk.Frame(self.opt_frame)
            row.grid(row=2 * r + 1, column=0, sticky="w")
            for i, (text, _) in enumerate(spec["choices"]):
                ttk.Radiobutton(row, text=text, value=i, variable=var).pack(anchor="w")
        if not cls.options_spec:
            ttk.Label(self.opt_frame, text="keine", style="Muted.TLabel").pack(anchor="w")
        self.rules_lbl.configure(text=cls.rules)
        theme.place_dialog(self)

    def _start(self):
        cls = self._selected_class()
        n = self.count.get()
        names = [self.name_vars[i].get().strip() or f"Spieler {i + 1}" for i in range(n)]
        if len({x.casefold() for x in names}) < n:
            messagebox.showerror("Namen", "Jeder Spieler braucht einen eigenen Namen.", parent=self)
            return
        options = {spec["key"]: spec["choices"][self.opt_vars[spec["key"]].get()][1] for spec in cls.options_spec}
        self.result = {"key": cls.key, "names": names, "options": options}
        self.destroy()


# --------------------------------------------------------------------------
# Spielbildschirm (liegt im Hauptfenster über dem X01-Bildschirm)
# --------------------------------------------------------------------------

class MiniGameFrame(tk.Frame):
    CHORD_TIMEOUT_MS = 1500

    def __init__(self, app, game):
        super().__init__(app.root, bg=theme.BG)
        self.app = app
        self.game = game
        self._buf = ""
        self._buf_job = None
        self._finish_job = None
        f = app.fonts

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Kopfzeile
        header = tk.Frame(self, bg=theme.BG)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        logo = theme.load_image("logo_small.png")
        if logo:
            tk.Label(header, image=logo, bg=theme.BG).pack(side="left", padx=(0, 14))
        tk.Label(header, text=f"Minispiel:  {game.title}", font=f["name"], bg=theme.BG, fg=theme.INK).pack(side="left")
        ttk.Button(header, text="☰  Menü  [Esc]", command=self.open_menu).pack(side="right")

        # Hauptbereich: links Anzeige, rechts (nur bei Eingabe-Pad, z. B. Cricket) die Tasten
        self.body = tk.Frame(self, bg=theme.BG)
        self.body.grid(row=1, column=0, sticky="nsew", padx=16)
        self.right = tk.Frame(self.body, bg=theme.BG)
        self.left = tk.Frame(self.body, bg=theme.BG)
        self.left.pack(side="left", fill="both", expand=True)

        # Zahleneingabe (nur Highscore)
        self.entry = None
        self.entry_row = tk.Frame(self, bg=theme.BG)
        if game.number_input:
            tk.Label(self.entry_row, text="Punkte der Aufnahme:", font=f["entrylbl"], bg=theme.BG).pack(side="left")
            self.entry_var = tk.StringVar()
            self.entry = ttk.Entry(self.entry_row, textvariable=self.entry_var, width=5, font=f["entry"],
                                   justify="center")
            theme.digits_only(self.entry, 3)
            self.entry.pack(side="left", padx=12)
            ttk.Button(self.entry_row, text="Bestätigen  [Enter]", style="Accent.TButton",
                       command=self._submit_number).pack(side="left")
            self.entry.bind("<Return>", lambda e: (self._submit_number(), "break")[1])
            self.entry.bind("<KP_Enter>", lambda e: (self._submit_number(), "break")[1])
            self.entry_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(6, 0))

        self.msg_var = tk.StringVar()
        self.msg_lbl = tk.Label(self, textvariable=self.msg_var, font=f["log"], bg=theme.BG, fg="#b00020")
        self.msg_lbl.grid(row=3, column=0, sticky="ew", padx=16)
        tk.Label(self, text=game.hint, font=("", 11), bg=theme.BG, fg=theme.MUTED, wraplength=1500,
                 justify="left").grid(row=4, column=0, sticky="w", padx=16, pady=(0, 8))

        self.render()
        if self.entry:
            self.entry.focus_set()

    # ---------------- Anzeige ----------------

    def render(self):
        g, f = self.game, self.app.fonts
        view = g.view()
        pad_mode = any(a["pad"] for a in g.actions())
        for w in list(self.left.winfo_children()) + list(self.right.winfo_children()):
            w.destroy()
        self.left.pack_forget()
        self.right.pack_forget()
        if pad_mode:
            self.right.pack(side="right", fill="y", padx=(12, 0))   # zuerst packen, damit die Tasten Platz behalten
        self.left.pack(side="left", fill="both", expand=True)

        # --- Kopf der Anzeige: Ziel groß, darunter Hinweiszeile
        stage = tk.Frame(self.left, bg=theme.CARD, highlightthickness=2, highlightbackground=theme.LINE)
        stage.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(stage, text=view.get("headline", ""), font=f["headline"], bg=theme.CARD, fg=theme.INK).pack(
            expand=True, fill="both", pady=(6, 0))
        tk.Label(stage, text=view.get("subline", ""), font=f["sub"], bg=theme.CARD, fg=theme.MUTED).pack()
        chips = tk.Frame(stage, bg=theme.CARD)
        chips.pack(pady=(6, 10))
        for label in view.get("chips", []):
            tk.Label(chips, text=label, font=f["chip"], fg="white", bg=theme.CHIP_COLORS[chip_kind(label)],
                     padx=14, pady=3).pack(side="left", padx=5)
        if view.get("table"):
            self._render_table(stage, view["table"])

        # --- Spielerkarten
        cards = tk.Frame(self.left, bg=theme.BG)
        cards.pack(fill="x", pady=(0, 8))
        for i, c in enumerate(view["cards"]):
            cards.columnconfigure(i, weight=1, uniform="cards")
            active = c.get("active")
            card = tk.Frame(cards, bg=theme.CARD, highlightthickness=7 if active else 3,
                            highlightbackground=theme.RED if active else theme.LINE, padx=8, pady=6)
            card.grid(row=0, column=i, sticky="nsew", padx=5)
            tk.Label(card, text=("▶  " if active else "") + c["name"], font=f["name"], pady=2,
                     bg=theme.RED if active else "#dfe2e6", fg="white" if active else theme.INK).pack(fill="x")
            tk.Label(card, text=c["big"], font=f["score"], bg=theme.CARD,
                     fg=theme.MUTED if c.get("out") else theme.INK).pack()
            for line in c.get("lines", []):
                tk.Label(card, text=line, font=f["sub"], bg=theme.CARD, fg=theme.INK).pack()

        # --- Eingabetasten
        self._render_actions(self.right if pad_mode else self.left, pad_mode)

        self.msg_var.set(g.message)

    def _render_table(self, parent, table):
        f = self.app.fonts
        grid = tk.Frame(parent, bg=theme.CARD)
        grid.pack(pady=(0, 10))
        players = table["players"]
        tk.Label(grid, text="", bg=theme.CARD, width=7).grid(row=0, column=0)
        for c, name in enumerate(players, start=1):
            active = (c - 1) == table["current"]
            tk.Label(grid, text=name, font=f["sub"], width=12, bg=theme.RED if active else "#dfe2e6",
                     fg="white" if active else theme.INK).grid(row=0, column=c, padx=3, pady=2, sticky="nsew")
        for r, (label, marks, closed) in enumerate(table["rows"], start=1):
            tk.Label(grid, text=label, font=f["sub"], bg=theme.CARD, fg=theme.INK, width=7).grid(row=r, column=0)
            for c, (mark, is_closed) in enumerate(zip(marks, closed), start=1):
                tk.Label(grid, text=mark or " ", font=f["recent"], width=8,
                         bg=theme.GREEN if is_closed else "#f0f1f3",
                         fg="white" if is_closed else theme.INK).grid(row=r, column=c, padx=3, pady=1, sticky="nsew")

    def _render_actions(self, parent, pad_mode):
        wrap = tk.Frame(parent, bg=theme.BG)
        wrap.pack(fill="both", expand=True) if not pad_mode else wrap.pack(fill="y")
        acts = self.game.actions()
        for i, a in enumerate(acts):
            row, col = a["pad"] if a["pad"] else (i // 4, i % 4)
            text = f"{a['label']}\n[ {key_hint(a['keys'])} ]" if a["keys"] else a["label"]
            btn = ttk.Button(wrap, text=text, style=STYLE_BY_KIND.get(a["style"], "Quick.TButton"),
                             command=lambda act=a: self.activate(act),
                             state="normal" if a["enabled"] else "disabled")
            btn.grid(row=row, column=col, padx=4, pady=3, sticky="nsew")
        cols = {(a["pad"][1] if a["pad"] else i % 4) for i, a in enumerate(acts)}
        rows = {(a["pad"][0] if a["pad"] else i // 4) for i, a in enumerate(acts)}
        for c in cols:
            wrap.columnconfigure(c, weight=1, uniform="act")
        for r in rows:
            wrap.rowconfigure(r, weight=1, uniform="actr")

    # ---------------- Eingaben ----------------

    def activate(self, a):
        if not a["enabled"]:
            return
        self.game.act(a["id"])
        self._after_act()

    def _after_act(self):
        self.render()
        if self.game.finished and not self._finish_job:
            self._finish_job = self.after(400, self._show_result)

    def _submit_number(self):
        raw = self.entry_var.get().strip()
        if not raw.isdigit():
            return
        self.entry_var.set("")
        self.game.act("score", int(raw))
        self._after_act()
        self.entry.focus_set()

    def on_key(self, ch):
        """Taste aus dem Hauptfenster (Ziffern, Buchstaben). Mehrtastenfolgen wie '1' + 'T' werden gesammelt."""
        ch = ch.lower()
        if not ch or self.game.finished:
            return
        if self.entry and ch.isdigit():
            self.entry.focus_set()
            self.entry.insert("end", ch)
            return
        keys = {}
        for a in self.game.actions():
            for k in a["keys"]:
                keys[k] = a
        self._buf += ch
        while self._buf:
            exact = keys.get(self._buf)
            longer = [k for k in keys if k.startswith(self._buf) and k != self._buf]
            if exact and not longer:
                self._reset_buffer()
                self.activate(exact)
                return
            if longer:
                if self._buf_job:
                    self.after_cancel(self._buf_job)
                self._buf_job = self.after(self.CHORD_TIMEOUT_MS, self._reset_buffer)
                self.msg_var.set(f"{self._buf.upper()} ... (weitere Taste)")
                return
            self._buf = self._buf[1:]      # Taste passt zu nichts: den Anfang verwerfen und neu versuchen

    def _reset_buffer(self):
        if self._buf_job:
            try:
                self.after_cancel(self._buf_job)
            except tk.TclError:
                pass
        self._buf, self._buf_job = "", None
        self.msg_var.set(self.game.message)

    def on_fkey(self, idx):
        if self.game.number_input and idx < len(self.app.cfg.get("fkeys", [])):
            self.game.act("score", self.app.cfg["fkeys"][idx])
            self._after_act()

    def undo(self):
        self._reset_buffer()
        if self.game.undo():
            self.render()

    # ---------------- Menü / Ende ----------------

    def open_menu(self):
        items = [
            ("Minispiel", "Weiterspielen", "Esc", lambda: None),
            ("Minispiel", "Letzte Eingabe rückgängig", "Strg+Z", self.undo),
            ("Minispiel", "Neustart (gleiche Einstellungen)", "", self.restart),
            ("Minispiel", "Anderes Minispiel wählen...", "", self.app.open_minigames),
            ("Minispiel", "Regeln anzeigen", "", self.show_rules),
            ("Minispiel", "Beenden - zurück zum Dartcounter", "", self.app.leave_minigame),
        ]
        MainMenuDialog(self.app.root, items)

    def show_rules(self):
        messagebox.showinfo(self.game.title, self.game.rules)

    def restart(self):
        g = self.game
        self.game = create_game(g.key, g.names, g.options)
        self._finish_job = None
        self._reset_buffer()
        self.render()

    def _show_result(self):
        self._finish_job = None
        dlg = MiniResultDialog(self.app.root, self.game)
        self.app.root.wait_window(dlg)
        if dlg.result == "again":
            self.restart()
        elif dlg.result == "other":
            self.app.open_minigames()
        else:
            self.app.leave_minigame()

    def destroy(self):
        for job in (self._buf_job, self._finish_job):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()


# --------------------------------------------------------------------------
# Endstand
# --------------------------------------------------------------------------

class MiniResultDialog(tk.Toplevel):
    """result: 'again' | 'other' | 'close'"""

    def __init__(self, master, game):
        super().__init__(master)
        self.title("Endstand")
        self.result = "close"
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=22)
        frm.pack()
        ranking = game.ranking()
        winners = [r["name"] for r in ranking if r["rank"] == 1]
        ttk.Label(frm, text=f"{game.title}: Endstand", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frm, text=("🏆  " + (" & ".join(winners) + " gewinnen!" if len(winners) > 1 else winners[0] + " gewinnt!")),
                  font=("", 14, "bold"), foreground=theme.RED).pack(anchor="w", pady=(2, 10))
        tree = ttk.Treeview(frm, columns=("rank", "name", "text"), show="headings", selectmode="none",
                            height=len(ranking), style="Stats.Treeview")
        tree.heading("rank", text="Platz")
        tree.heading("name", text="Spieler")
        tree.heading("text", text="Ergebnis")
        tree.column("rank", width=60, anchor="center")
        tree.column("name", width=160)
        tree.column("text", width=380)
        for r in ranking:
            tree.insert("", "end", values=(r["rank"], r["name"], r["text"]))
        tree.pack()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text="Zurück zum Dartcounter  [Esc]", command=lambda: self._finish("close")).pack(side="right")
        ttk.Button(btns, text="Anderes Minispiel  [N]", command=lambda: self._finish("other")).pack(side="right", padx=8)
        self.main_btn = ttk.Button(btns, text="Nochmal  [R / Enter]", style="Accent.TButton",
                                   command=lambda: self._finish("again"))
        self.main_btn.pack(side="right")
        theme.bind_dialog_keys(self, ok=lambda: self._finish("again"), cancel=lambda: self._finish("close"))
        for k in ("r", "R"):
            self.bind(f"<KeyPress-{k}>", lambda e: (self._finish("again"), "break")[1])
        for k in ("n", "N"):
            self.bind(f"<KeyPress-{k}>", lambda e: (self._finish("other"), "break")[1])
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish("close"))
        theme.place_dialog(self)
        theme.modal(self)
        self.main_btn.focus_set()

    def _finish(self, result):
        self.result = result
        self.destroy()
