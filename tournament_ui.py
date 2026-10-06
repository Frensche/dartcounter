"""
Oberfläche für den Turniermodus (tkinter):

- NewTournamentDialog: Turnier anlegen (Name, Spieler, KO oder Gruppenphase + KO)
- MasterWindow:        Turnierleiter - Gruppentabellen, Turnierbaum, Stationen, Ergebnisse korrigieren
- ConnectDialog:       Verbindung zum Turnier-Server herstellen
- StationPanel:        Station - offene Matches ansehen und eins zum Spielen auswählen
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import theme
from tournament import (BYE, DEFAULT_PORT, GROUP_NAMES, MAX_PLAYERS, MIN_PLAYERS, MODE_GROUPS, MODE_KO,
                        ONLINE_SECONDS, Tournament, TournamentError, clean_players, local_ip)


def run_async(widget, func, callback):
    """Führt func() in einem Thread aus, damit die Oberfläche nicht einfriert.

    callback(result, error) wird anschließend im Tk-Hauptthread aufgerufen.
    """
    q = queue.Queue()
    root = widget.nametowidget(".")

    def worker():
        try:
            q.put((func(), None))
        except Exception as e:  # noqa: BLE001 - jede Fehlerart soll im UI landen
            q.put((None, e))

    def poll():
        try:
            result, err = q.get_nowait()
        except queue.Empty:
            root.after(60, poll)
            return
        try:
            callback(result, err)
        except tk.TclError:
            pass  # Fenster wurde inzwischen geschlossen

    threading.Thread(target=worker, daemon=True).start()
    root.after(60, poll)


def _bring_to_front(win):
    """Hilft im Kiosk-Modus (Vollbild-Hauptfenster), dass Zusatzfenster sichtbar bleiben."""
    try:
        win.lift()
        win.focus_force()
    except tk.TclError:
        pass


def _header(parent, title):
    bar = ttk.Frame(parent, padding=(14, 10))
    logo = theme.load_image("logo_small.png")
    if logo:
        ttk.Label(bar, image=logo).pack(side="left", padx=(0, 12))
    ttk.Label(bar, text=title, style="Title.TLabel").pack(side="left")
    return bar


# --------------------------------------------------------------------------
# Neues Turnier
# --------------------------------------------------------------------------

class NewTournamentDialog(tk.Toplevel):
    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("Neues Turnier")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)

        outer = ttk.Frame(self, padding=18)
        outer.pack()
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n", padx=(0, 24))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="n")

        # ---- links: Name + Spieler
        ttk.Label(left, text="Turniername").pack(anchor="w")
        self.name_var = tk.StringVar(value="Dart-Turnier")
        ttk.Entry(left, textvariable=self.name_var, width=32).pack(anchor="w", pady=(2, 10))
        ttk.Label(left, text="Spieler (einer pro Zeile)").pack(anchor="w")
        txt_frame = ttk.Frame(left)
        txt_frame.pack(anchor="w", pady=(2, 0))
        self.txt = tk.Text(txt_frame, width=30, height=16, relief="flat", highlightthickness=1,
                           highlightbackground=theme.LINE, font=("", 11))
        sb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left")
        sb.pack(side="left", fill="y")
        self.count_var = tk.StringVar()
        ttk.Label(left, textvariable=self.count_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        self.txt.bind("<KeyRelease>", lambda e: self._update_summary())

        # ---- rechts: Modus
        mode_box = ttk.LabelFrame(right, text="Turniermodus", padding=10)
        mode_box.pack(fill="x")
        self.mode = tk.StringVar(value=MODE_GROUPS)
        ttk.Radiobutton(mode_box, text="Nur KO-Runde", value=MODE_KO, variable=self.mode,
                        command=self._mode_changed).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(mode_box, text="Gruppenphase + KO-Runde", value=MODE_GROUPS, variable=self.mode,
                        command=self._mode_changed).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 6))

        self.groups = tk.IntVar(value=2)
        self.advance = tk.IntVar(value=2)
        self.group_legs = tk.IntVar(value=2)
        self.group_widgets = []
        for r, (label, var, lo, hi) in enumerate((
                ("Anzahl Gruppen", self.groups, 1, 16),
                ("Weiter pro Gruppe", self.advance, 1, 8),
                ("Legs zum Sieg (Gruppe)", self.group_legs, 1, 21))):
            lbl = ttk.Label(mode_box, text=label)
            lbl.grid(row=2 + r, column=0, sticky="w", padx=(18, 8), pady=2)
            sp = ttk.Spinbox(mode_box, from_=lo, to=hi, textvariable=var, width=5, command=self._update_summary)
            sp.grid(row=2 + r, column=1, sticky="w", pady=2)
            sp.bind("<KeyRelease>", lambda e: self._update_summary())
            self.group_widgets += [lbl, sp]
        self.summary_var = tk.StringVar()
        ttk.Label(mode_box, textvariable=self.summary_var, style="Muted.TLabel", wraplength=300,
                  justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ---- rechts: Spielregeln
        rules = ttk.LabelFrame(right, text="Spielregeln", padding=10)
        rules.pack(fill="x", pady=(10, 0))
        ttk.Label(rules, text="Startpunktzahl").grid(row=0, column=0, sticky="w", pady=2)
        self.start_score = tk.IntVar(value=cfg.get("start_score", 501))
        sf = ttk.Frame(rules)
        sf.grid(row=0, column=1, sticky="w")
        for sc in (301, 501, 701):
            ttk.Radiobutton(sf, text=str(sc), value=sc, variable=self.start_score).pack(side="left", padx=4)
        self.double_out = tk.BooleanVar(value=cfg.get("double_out", True))
        ttk.Checkbutton(rules, text="Double-Out", variable=self.double_out).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(rules, text="Legs zum Sieg (KO-Runde)").grid(row=2, column=0, sticky="w", pady=2)
        self.legs = tk.IntVar(value=2)
        ttk.Spinbox(rules, from_=1, to=21, textvariable=self.legs, width=5).grid(row=2, column=1, sticky="w")
        ttk.Label(rules, text="Legs zum Sieg (Finale)").grid(row=3, column=0, sticky="w", pady=2)
        self.final_legs = tk.IntVar(value=3)
        ttk.Spinbox(rules, from_=1, to=21, textvariable=self.final_legs, width=5).grid(row=3, column=1, sticky="w")

        # ---- rechts: Netzwerk
        net = ttk.LabelFrame(right, text="Netzwerk", padding=10)
        net.pack(fill="x", pady=(10, 0))
        ttk.Label(net, text="Anzahl Stationen").grid(row=0, column=0, sticky="w", pady=2)
        self.stations = tk.IntVar(value=6)
        ttk.Spinbox(net, from_=1, to=16, textvariable=self.stations, width=5).grid(row=0, column=1, sticky="w")
        ttk.Label(net, text="Server-Port").grid(row=1, column=0, sticky="w", pady=2, padx=(0, 20))
        self.port = tk.IntVar(value=cfg.get("tournament_port", 8765))
        ttk.Spinbox(net, from_=1024, to=65535, textvariable=self.port, width=7).grid(row=1, column=1, sticky="w")

        self.shuffle = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Spieler zufällig auslosen\n(sonst gilt die Reihenfolge als Setzliste)",
                        variable=self.shuffle).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(outer)
        btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Turnier starten", style="Accent.TButton", command=self._on_ok).pack(side="right")

        self._mode_changed()
        theme.modal(self)
        self.txt.focus_set()

    def _players(self):
        return [line for line in self.txt.get("1.0", "end").splitlines() if line.strip()]

    def _mode_changed(self):
        state = "normal" if self.mode.get() == MODE_GROUPS else "disabled"
        for w in self.group_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self._update_summary()

    def _update_summary(self):
        n = len(self._players())
        self.count_var.set(f"{n} Spieler (erlaubt: {MIN_PLAYERS}-{MAX_PLAYERS})")
        if self.mode.get() != MODE_GROUPS:
            ko = n
            self.summary_var.set(f"KO-Runde mit {ko} Spielern." if n >= 2 else "")
            return
        try:
            g, adv = self.groups.get(), self.advance.get()
        except tk.TclError:
            return
        if n < 2 or g < 1:
            self.summary_var.set("")
        elif n < 2 * g:
            self.summary_var.set(f"Zu wenige Spieler für {g} Gruppen (mindestens {2 * g}).")
        else:
            base, extra = divmod(n, g)
            sizes = str(base) if extra == 0 else f"{base}-{base + 1}"
            self.summary_var.set(
                f"{g} Gruppen mit je {sizes} Spielern, {g * adv} Spieler kommen in die KO-Runde.")

    def _on_ok(self):
        try:
            players = clean_players(self._players())
            grouped = self.mode.get() == MODE_GROUPS
            t = Tournament(
                self.name_var.get(), players,
                start_score=self.start_score.get(), double_out=self.double_out.get(),
                legs_to_win=self.legs.get(), final_legs_to_win=self.final_legs.get(),
                stations=self.stations.get(), shuffle=self.shuffle.get(),
                mode=self.mode.get(),
                groups=self.groups.get() if grouped else 0,
                advance=self.advance.get() if grouped else 0,
                group_legs_to_win=self.group_legs.get(),
            )
            port = self.port.get()
        except (TournamentError, tk.TclError) as e:
            messagebox.showerror("Turnier", str(e) if isinstance(e, TournamentError)
                                 else "Bitte nur gültige Zahlen eingeben.", parent=self)
            return
        self.result = {"tournament": t, "port": port}
        self.destroy()


# --------------------------------------------------------------------------
# Ergebnis manuell eintragen
# --------------------------------------------------------------------------

class ResultDialog(tk.Toplevel):
    def __init__(self, master, match):
        super().__init__(master)
        self.title("Ergebnis eintragen")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=18)
        frm.grid()
        ttk.Label(frm, text=match["label"], font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(frm, text="Sieger", style="Muted.TLabel").grid(row=1, column=0)
        ttk.Label(frm, text="Spieler", style="Muted.TLabel").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(frm, text="Legs", style="Muted.TLabel").grid(row=1, column=2)

        self.winner = tk.StringVar(value=match["winner"] or "")
        self.legs_vars = []
        old = match.get("legs") or [0, 0]
        for i, name in enumerate(match["p"]):
            ttk.Radiobutton(frm, value=name, variable=self.winner).grid(row=2 + i, column=0)
            ttk.Label(frm, text=name, width=22, font=("", 11)).grid(row=2 + i, column=1, sticky="w", padx=6)
            var = tk.IntVar(value=old[i])
            ttk.Spinbox(frm, from_=0, to=99, textvariable=var, width=4).grid(row=2 + i, column=2, pady=4)
            self.legs_vars.append(var)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, pady=(14, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Speichern", style="Accent.TButton", command=self._ok).pack(side="right")
        theme.modal(self)

    def _ok(self):
        if not self.winner.get():
            messagebox.showerror("Ergebnis", "Bitte den Sieger auswählen.", parent=self)
            return
        try:
            legs = [v.get() for v in self.legs_vars]
        except tk.TclError:
            messagebox.showerror("Ergebnis", "Bitte gültige Leg-Zahlen eingeben.", parent=self)
            return
        self.result = (self.winner.get(), legs)
        self.destroy()


# --------------------------------------------------------------------------
# Turnierleiter-Fenster
# --------------------------------------------------------------------------

STATUS_COLORS = {
    "waiting": ("#ececec", "#aaaaaa"),
    "ready": ("#fff3c4", "#d4a017"),
    "running": ("#cfe8ff", "#2a7fd4"),
    "done": ("#ffffff", "#888888"),
}
STATUS_TEXT = {"waiting": "wartet", "ready": "bereit", "done": "beendet"}

BOX_W, ROW_H, GAP_X, V_GAP, LEFT, TOP = 210, 24, 56, 26, 20, 46


class MasterWindow(tk.Toplevel):
    def __init__(self, master, tournament, server, on_close):
        super().__init__(master)
        self.t = tournament
        self.server = server
        self.on_close = on_close
        self.selected = None
        self._last_version = None
        self._last_stage = None
        self._after = None
        self._refilling = False
        self._pos = {}
        self.group_trees = {}   # Gruppenindex -> (Tabelle, Spiele)

        self.title(f"Turnierleiter - {tournament.name}")
        self.geometry("1280x760")
        self.transient(master)
        theme.set_window_icon(self)

        header = _header(self, tournament.name)
        header.pack(fill="x")
        self.phase_var = tk.StringVar()
        ttk.Label(header, textvariable=self.phase_var, style="Muted.TLabel", font=("", 12)).pack(side="left", padx=16)
        self.champion_var = tk.StringVar()
        ttk.Label(header, textvariable=self.champion_var, style="Good.TLabel").pack(side="left", padx=10)
        addr = f"{local_ip()}:{server.port}"
        ttk.Label(header, text=f"Stationen verbinden sich mit:  {addr}", font=("", 11, "bold")).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Seitenleiste (zuerst packen, damit sie rechts bleibt)
        side = ttk.Frame(body, padding=12, width=310)
        side.pack(side="right", fill="y")

        # Notebook mit Gruppen- und KO-Ansicht
        self.nb = ttk.Notebook(body)
        self.nb.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        self.groups_tab = None
        if tournament.mode == MODE_GROUPS:
            self.groups_tab = ttk.Frame(self.nb)
            self.nb.add(self.groups_tab, text="  Gruppenphase  ")
            self._build_groups_tab()
        self.ko_tab = ttk.Frame(self.nb)
        self.nb.add(self.ko_tab, text="  KO-Runde  ")
        self._build_ko_tab()

        st_frame = ttk.LabelFrame(side, text="Stationen", padding=8)
        st_frame.pack(fill="x")
        self.station_labels = []
        for n in range(1, tournament.stations + 1):
            lbl = tk.Label(st_frame, text="", justify="left", anchor="w", wraplength=280, bg=theme.BG)
            lbl.pack(fill="x", pady=2)
            self.station_labels.append(lbl)

        sel_frame = ttk.LabelFrame(side, text="Ausgewähltes Match", padding=8)
        sel_frame.pack(fill="x", pady=(12, 0))
        self.sel_var = tk.StringVar(value="Match anklicken")
        ttk.Label(sel_frame, textvariable=self.sel_var, wraplength=280, justify="left").pack(fill="x", pady=(0, 8))
        self.btn_result = ttk.Button(sel_frame, text="Ergebnis eintragen / korrigieren...",
                                     command=self.edit_result, state="disabled")
        self.btn_result.pack(fill="x", pady=2)
        self.btn_release = ttk.Button(sel_frame, text="Match an Station freigeben",
                                      command=self.release_match, state="disabled")
        self.btn_release.pack(fill="x", pady=2)
        self.btn_reset = ttk.Button(sel_frame, text="Ergebnis zurücksetzen",
                                    command=self.reset_match, state="disabled")
        self.btn_reset.pack(fill="x", pady=2)

        ttk.Label(side, style="Muted.TLabel", wraplength=280, justify="left",
                  text="Ergebnisse von den Stationen erscheinen automatisch. "
                       "Der Turnierstand wird laufend gespeichert.").pack(fill="x", pady=(12, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)
        _bring_to_front(self)
        self._tick()

    # ---------------- Aufbau der Ansichten ----------------

    def _build_ko_tab(self):
        self.canvas = tk.Canvas(self.ko_tab, bg="#f4f4f4", highlightthickness=0)
        xsb = ttk.Scrollbar(self.ko_tab, orient="horizontal", command=self.canvas.xview)
        ysb = ttk.Scrollbar(self.ko_tab, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        xsb.pack(side="bottom", fill="x")
        ysb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

    def _build_groups_tab(self):
        canvas = tk.Canvas(self.groups_tab, bg=theme.BG, highlightthickness=0)
        ysb = ttk.Scrollbar(self.groups_tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=8)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        for c in (canvas, inner):
            c.bind("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
            c.bind("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

        inner.columnconfigure(0, weight=1, uniform="g")
        inner.columnconfigure(1, weight=1, uniform="g")
        for gi, members in enumerate(self.t.groups):
            box = ttk.LabelFrame(inner, text=f"  Gruppe {GROUP_NAMES[gi]}  ", padding=8)
            box.grid(row=gi // 2, column=gi % 2, sticky="nsew", padx=6, pady=6)
            table = ttk.Treeview(box, columns=("rank", "name", "played", "wins", "losses", "legs", "points"),
                                 show="headings", height=len(members), selectmode="none")
            for col, text, width in (("rank", "#", 34), ("name", "Spieler", 170), ("played", "Sp", 38),
                                     ("wins", "S", 34), ("losses", "N", 34), ("legs", "Legs", 62),
                                     ("points", "Pkt", 42)):
                table.heading(col, text=text)
                table.column(col, width=width, anchor="w" if col == "name" else "center", stretch=(col == "name"))
            table.tag_configure("adv", background="#d9f2d9")
            table.pack(fill="x")

            n_matches = len(self.t.group_matches(gi))
            games = ttk.Treeview(box, columns=("day", "match", "result", "status"), show="headings",
                                 height=n_matches, selectmode="browse")
            for col, text, width in (("day", "Tag", 40), ("match", "Spiel", 190), ("result", "Ergebnis", 70),
                                     ("status", "Status", 120)):
                games.heading(col, text=text)
                games.column(col, width=width, anchor="center" if col != "match" else "w",
                             stretch=(col == "match"))
            for status, (bg, _) in STATUS_COLORS.items():
                games.tag_configure(status, background=bg)
            games.pack(fill="x", pady=(8, 0))
            games.bind("<<TreeviewSelect>>", lambda e, tree=games: self._on_group_select(tree))
            games.bind("<Double-Button-1>", lambda e: self.edit_result())
            self.group_trees[gi] = (table, games)

    def _on_group_select(self, tree):
        if self._refilling:
            return
        sel = tree.selection()
        if not sel:
            return
        for _, other in self.group_trees.values():
            if other is not tree and other.selection():
                other.selection_remove(*other.selection())
        self.selected = sel[0]
        self._last_version = None  # Markierung im KO-Baum nachziehen
        self._update_selection(self.t.snapshot())

    # ---------------- Aktualisierung ----------------

    def destroy(self):
        if self._after:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        super().destroy()

    def _tick(self):
        snap = self.t.snapshot()
        if snap["version"] != self._last_version:
            self._last_version = snap["version"]
            self._draw(snap)
            if self.groups_tab:
                self._fill_groups(snap)
        if self.groups_tab and snap["stage"] != self._last_stage:
            self.nb.select(self.groups_tab if snap["stage"] == "groups" else self.ko_tab)
        self._last_stage = snap["stage"]
        self._update_stations(snap)
        self._update_selection(snap)
        phase = {"groups": "Phase: Gruppenphase", "ko": "Phase: KO-Runde", "done": "Turnier beendet"}[snap["stage"]]
        self.phase_var.set(phase)
        champ = snap["champion"]
        self.champion_var.set(f"🏆 Turniersieger: {champ}" if champ else "")
        self._after = self.after(1000, self._tick)

    def _update_stations(self, snap):
        for n, lbl in enumerate(self.station_labels, start=1):
            seen = snap["seen_ago"].get(n)
            online = seen is not None and seen < ONLINE_SECONDS
            running = next((m for m in snap["matches"] if m["station"] == n), None)
            line1 = f"Station {n}   {'● online' if online else '○ nicht verbunden'}"
            if running:
                line2 = f"\nspielt: {running['p'][0]} - {running['p'][1]}\n({running['label']})"
            else:
                line2 = "\nfrei" if online else ""
            lbl.configure(text=line1 + line2, fg=theme.GREEN if online else "#777777")

    def _update_selection(self, snap):
        m = next((x for x in snap["matches"] if x["id"] == self.selected), None)
        if not m:
            self.sel_var.set("Match anklicken")
            for b in (self.btn_result, self.btn_release, self.btn_reset):
                b.configure(state="disabled")
            return
        status = {"waiting": "wartet auf Vorrunde", "ready": "spielbereit",
                  "running": f"läuft an Station {m['station']}", "done": "beendet"}[m["status"]]
        if m["status"] == "ready" and m["busy"]:
            status += f" (wartet: {m['busy']})"
        players = " - ".join(p if p else "?" for p in m["p"])
        extra = ""
        if m["status"] == "done" and m["legs"]:
            extra = f"\nErgebnis: {m['legs'][0]}:{m['legs'][1]}, Sieger {m['winner']}"
            if m["avg"]:
                extra += f"\nØ {m['avg'][0]} / {m['avg'][1]}"
        self.sel_var.set(f"{m['label']}\n{players}\nStatus: {status}\nFirst to {m['legs_to_win']}{extra}")
        can_edit = m["status"] in ("ready", "running", "done") and not m["walkover"]
        self.btn_result.configure(state="normal" if can_edit else "disabled")
        self.btn_release.configure(state="normal" if m["status"] == "running" else "disabled")
        self.btn_reset.configure(state="normal" if m["status"] == "done" and not m["walkover"] else "disabled")

    # ---------------- Gruppenphase ----------------

    def _fill_groups(self, snap):
        self._refilling = True
        try:
            for gi, (table, games) in self.group_trees.items():
                g = snap["groups"][gi]
                table.delete(*table.get_children())
                for r in g["table"]:
                    diff = f"{r['legs_for']}:{r['legs_against']}"
                    tag = ("adv",) if r["rank"] <= snap["advance"] else ()
                    table.insert("", "end", values=(r["rank"], r["name"], r["played"], r["wins"], r["losses"],
                                                    diff, r["points"]), tags=tag)
                games.delete(*games.get_children())
                gm = sorted((m for m in snap["matches"] if m["stage"] == "group" and m["group"] == gi),
                            key=lambda m: (m["round"], m["index"]))
                for m in gm:
                    result = f"{m['legs'][0]}:{m['legs'][1]}" if m["legs"] else ("✓" if m["winner"] else "")
                    if m["status"] == "running":
                        status = f"▶ Station {m['station']}"
                    elif m["status"] == "done":
                        status = f"Sieger: {m['winner']}"
                    elif m["status"] == "ready" and m["busy"]:
                        status = "bereit (Spieler belegt)"
                    else:
                        status = STATUS_TEXT[m["status"]]
                    games.insert("", "end", iid=m["id"], tags=(m["status"],),
                                 values=(m["round"] + 1, f"{m['p'][0]} - {m['p'][1]}", result, status))
                if self.selected in games.get_children():
                    games.selection_set(self.selected)
        finally:
            self._refilling = False

    # ---------------- KO-Baum zeichnen ----------------

    def _draw(self, snap):
        c = self.canvas
        c.delete("all")
        self._pos = {}
        matches = [m for m in snap["matches"] if m["stage"] == "ko"]
        by = {(m["round"], m["index"]): m for m in matches}
        rounds = snap["rounds"]
        n0 = sum(1 for m in matches if m["round"] == 0)
        unit = 2 * ROW_H + V_GAP

        centers = {(0, i): TOP + unit * (i + 0.5) for i in range(n0)}
        for r in range(1, rounds):
            for i in range(n0 >> r):
                centers[(r, i)] = (centers[(r - 1, 2 * i)] + centers[(r - 1, 2 * i + 1)]) / 2

        def x_of(r):
            return LEFT + r * (BOX_W + GAP_X)

        # Verbindungslinien
        for (r, i), yc in centers.items():
            if r == 0:
                continue
            xp = x_of(r)
            xm = xp - GAP_X / 2
            for child in (2 * i, 2 * i + 1):
                yc_child = centers[(r - 1, child)]
                c.create_line(x_of(r - 1) + BOX_W, yc_child, xm, yc_child, xm, yc, xp, yc, fill="#999999")

        # Rundenüberschriften
        for r in range(rounds):
            c.create_text(x_of(r) + BOX_W / 2, 22, text=snap["round_names"][r], font=("", 11, "bold"))

        # Matches
        for (r, i), yc in centers.items():
            m = by[(r, i)]
            x = x_of(r)
            self._pos[m["id"]] = (x, yc)
            fill, outline = STATUS_COLORS[m["status"]]
            tag = m["id"]
            c.create_rectangle(x, yc - ROW_H, x + BOX_W, yc + ROW_H, fill=fill, outline=outline, width=2,
                               tags=(tag,))
            c.create_line(x, yc, x + BOX_W, yc, fill=outline, tags=(tag,))
            for row in (0, 1):
                name = m["p"][row]
                ry = yc - ROW_H / 2 if row == 0 else yc + ROW_H / 2
                is_winner = m["winner"] is not None and name == m["winner"]
                if is_winner:
                    top = yc - ROW_H if row == 0 else yc
                    c.create_rectangle(x + 2, top + 2, x + BOX_W - 2, top + ROW_H - 2,
                                       fill="#d4f0d4", outline="", tags=(tag,))
                if name == BYE:
                    text, font, color = "Freilos", ("", 10, "italic"), "#888888"
                elif name is None:
                    text, font, color = "...", ("", 10), "#999999"
                else:
                    text, font, color = name, ("", 10, "bold" if is_winner else "normal"), "#111111"
                c.create_text(x + 8, ry, text=text, anchor="w", font=font, fill=color, tags=(tag,))
                if m["legs"] and name not in (None, BYE):
                    c.create_text(x + BOX_W - 8, ry, text=str(m["legs"][row]), anchor="e",
                                  font=("", 10, "bold"), fill="#111111", tags=(tag,))
            if m["status"] == "running":
                c.create_text(x, yc - ROW_H - 3, text=f"▶ Station {m['station']}", anchor="sw",
                              font=("", 8, "bold"), fill="#2a7fd4")
            elif m["status"] == "ready":
                c.create_text(x, yc - ROW_H - 3, text="bereit", anchor="sw",
                              font=("", 8, "bold"), fill="#b07800")
            elif m["status"] == "done" and m["done_station"]:
                c.create_text(x, yc - ROW_H - 3, text=f"Station {m['done_station']}", anchor="sw",
                              font=("", 8), fill="#777777")
            if m["id"] == self.selected:
                c.create_rectangle(x - 3, yc - ROW_H - 3, x + BOX_W + 3, yc + ROW_H + 3,
                                   outline="#d62728", width=3)
            c.tag_bind(tag, "<Button-1>", lambda e, mid=m["id"]: self.select(mid))
            c.tag_bind(tag, "<Double-Button-1>", lambda e, mid=m["id"]: self._double(mid))

        if snap["mode"] == MODE_GROUPS and not snap["ko_filled"]:
            c.create_text(LEFT, 4, anchor="nw", fill=theme.MUTED, font=("", 10, "italic"),
                          text="Die Paarungen stehen fest, sobald die Gruppenphase beendet ist.")

        width = x_of(rounds - 1) + BOX_W + LEFT
        height = TOP + unit * n0 + 20
        c.configure(scrollregion=(0, 0, width, height))

    def select(self, match_id):
        self.selected = match_id
        self._last_version = None  # Neuzeichnen erzwingen (Markierung)
        self._tick_now()

    def _tick_now(self):
        if self._after:
            self.after_cancel(self._after)
        self._tick()

    def _double(self, match_id):
        self.selected = match_id
        self.edit_result()

    # ---------------- Aktionen ----------------

    def _selected_snapshot(self):
        snap = self.t.snapshot()
        return next((x for x in snap["matches"] if x["id"] == self.selected), None)

    def edit_result(self):
        m = self._selected_snapshot()
        if not m or m["walkover"] or m["status"] == "waiting":
            return
        dlg = ResultDialog(self, m)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            self.t.set_result(m["id"], dlg.result[0], dlg.result[1])
        except TournamentError as e:
            messagebox.showerror("Ergebnis", str(e), parent=self)
        self._tick_now()

    def release_match(self):
        m = self._selected_snapshot()
        if not m or m["status"] != "running":
            return
        if messagebox.askyesno("Match freigeben",
                               f"Station {m['station']} verliert dieses Match; es kann danach von "
                               "einer beliebigen Station neu gestartet werden.\n\nFreigeben?", parent=self):
            self.t.release(m["id"])
            self._tick_now()

    def reset_match(self):
        m = self._selected_snapshot()
        if not m or m["status"] != "done":
            return
        if messagebox.askyesno("Ergebnis zurücksetzen",
                               "Das Ergebnis wird gelöscht und das Match muss neu gespielt werden.\n\n"
                               "Zurücksetzen?", parent=self):
            try:
                self.t.reset_result(m["id"])
            except TournamentError as e:
                messagebox.showerror("Ergebnis", str(e), parent=self)
            self._tick_now()

    def _close(self):
        snap = self.t.snapshot()
        running = [m for m in snap["matches"] if m["status"] == "running"]
        msg = "Der Turnier-Server wird beendet, die Stationen verlieren die Verbindung."
        if running:
            msg += f"\n\nAchtung: {len(running)} Match(es) laufen noch!"
        msg += "\n\nDer Turnierstand bleibt gespeichert und kann später fortgesetzt werden.\n\nBeenden?"
        if messagebox.askyesno("Turnierleiter beenden", msg, parent=self):
            self.on_close()
            self.destroy()


# --------------------------------------------------------------------------
# Station: Verbindung
# --------------------------------------------------------------------------

class ConnectDialog(tk.Toplevel):
    def __init__(self, master, cfg):
        super().__init__(master)
        self.title("Als Station verbinden")
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=18)
        frm.grid()
        pad = {"padx": 8, "pady": 6}
        ttk.Label(frm, text="IP-Adresse des Turnierleiters:").grid(row=0, column=0, sticky="w", **pad)
        self.host = tk.StringVar(value=cfg.get("tournament_host", ""))
        e = ttk.Entry(frm, textvariable=self.host, width=22, font=("", 11))
        e.grid(row=0, column=1, **pad)
        ttk.Label(frm, text="Port:").grid(row=1, column=0, sticky="w", **pad)
        self.port = tk.IntVar(value=cfg.get("tournament_port", DEFAULT_PORT))
        ttk.Spinbox(frm, from_=1024, to=65535, textvariable=self.port, width=7).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Diese Station (Nr.):").grid(row=2, column=0, sticky="w", **pad)
        self.station = tk.IntVar(value=cfg.get("tournament_station", 1))
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self.station, width=5).grid(row=2, column=1, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(14, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Verbinden", style="Accent.TButton", command=self._ok).pack(side="right")
        self.bind("<Return>", lambda ev: self._ok())
        theme.modal(self)
        e.focus_set()

    def _ok(self):
        host = self.host.get().strip()
        if not host:
            messagebox.showerror("Verbindung", "Bitte die IP-Adresse des Turnierleiters eingeben.", parent=self)
            return
        try:
            self.result = {"host": host, "port": self.port.get(), "station": self.station.get()}
        except tk.TclError:
            messagebox.showerror("Verbindung", "Port und Station müssen Zahlen sein.", parent=self)
            return
        self.destroy()


# --------------------------------------------------------------------------
# Station: Match-Auswahl
# --------------------------------------------------------------------------

class StationPanel(tk.Toplevel):
    POLL_MS = 2000

    def __init__(self, master, app, client, state):
        super().__init__(master)
        self.app = app
        self.client = client
        self._after = None
        self._busy = False
        self._dead = False
        self._matches = {}

        self.title(f"Turnier-Station {client.station}")
        self.geometry("700x520")
        self.transient(master)
        theme.set_window_icon(self)

        header = _header(self, "Turnier-Station")
        header.pack(fill="x")
        self.head_var = tk.StringVar()
        ttk.Label(header, textvariable=self.head_var, style="Muted.TLabel", font=("", 12)).pack(side="left", padx=14)
        self.status_var = tk.StringVar()
        self.status_lbl = tk.Label(self, textvariable=self.status_var, anchor="w", padx=14, bg=theme.BG)
        self.status_lbl.pack(fill="x")

        ttk.Label(self, text="Spielbereite Matches - eins auswählen und hier spielen:",
                  padding=(14, 10, 14, 4)).pack(fill="x")
        tree_frame = ttk.Frame(self, padding=(14, 0))
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("round", "players", "status"), show="headings",
                                 selectmode="browse", height=10)
        self.tree.heading("round", text="Runde")
        self.tree.heading("players", text="Spieler")
        self.tree.heading("status", text="Status")
        self.tree.column("round", width=190)
        self.tree.column("players", width=260)
        self.tree.column("status", width=170)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="left", fill="y")
        self.tree.tag_configure("mine", background="#cfe8ff")
        self.tree.tag_configure("busy", foreground="#888888")
        self.tree.bind("<Double-Button-1>", lambda e: self.play_selected())

        btns = ttk.Frame(self, padding=14)
        btns.pack(fill="x")
        self.play_btn = ttk.Button(btns, text="Ausgewähltes Match hier spielen", style="Accent.TButton",
                                   command=self.play_selected)
        self.play_btn.pack(side="left")
        ttk.Button(btns, text="Aktualisieren", command=self.refresh_now).pack(side="left", padx=8)
        ttk.Button(btns, text="Trennen", command=self.destroy).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_state(state)
        self._schedule()
        _bring_to_front(self)

    # ---------------- Aktualisierung ----------------

    def destroy(self):
        self._dead = True
        if self._after:
            try:
                self.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        super().destroy()

    def _close(self):
        if self.app.tourn:
            self.withdraw()  # Verbindung bleibt bestehen, solange hier gespielt wird
        else:
            self.destroy()

    def _schedule(self):
        if not self._dead:
            self._after = self.after(self.POLL_MS, self._poll)

    def _poll(self):
        self._after = None
        if self._busy:
            self._schedule()
            return
        self._busy = True
        run_async(self, self.client.state, self._on_state)

    def refresh_now(self):
        if self._dead:
            return
        if self._after:
            self.after_cancel(self._after)
            self._after = None
        if not self._busy:
            self._busy = True
            run_async(self, self.client.state, self._on_state)

    def _on_state(self, state, err):
        self._busy = False
        if self._dead:
            return
        if err:
            self.status_var.set(f"Keine Verbindung: {err}")
            self.status_lbl.configure(fg="#b00020")
        else:
            self._apply_state(state)
        if self._after is None:
            self._schedule()

    def _apply_state(self, state):
        n = self.client.station
        self.head_var.set(f"{state['name']}  -  Station {n}")
        self.status_var.set("● verbunden")
        self.status_lbl.configure(fg=theme.GREEN)

        mine, ready, blocked, other = [], [], [], []
        for m in state["matches"]:
            if m["status"] == "running" and m["station"] == n:
                mine.append(m)
            elif m["status"] == "ready" and not m.get("busy"):
                ready.append(m)
            elif m["status"] == "ready":
                blocked.append(m)
            elif m["status"] == "running":
                other.append(m)
        ready.sort(key=lambda m: (m["stage"] != "group", m["round"] or 0, m["index"] or 0))

        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self._matches = {}
        for group in (mine, ready, blocked, other):
            for m in group:
                if group is mine:
                    status, tags = "läuft hier (fortsetzen)", ("mine",)
                elif group is ready:
                    status, tags = "bereit", ()
                elif group is blocked:
                    status, tags = f"wartet - {m['busy']} spielt", ("busy",)
                else:
                    status, tags = f"läuft an Station {m['station']}", ("busy",)
                self.tree.insert("", "end", iid=m["id"], tags=tags,
                                 values=(m["label"], f"{m['p'][0]} - {m['p'][1]}", status))
                self._matches[m["id"]] = m
        if selected and selected[0] in self._matches:
            self.tree.selection_set(selected[0])
        elif mine:
            self.tree.selection_set(mine[0]["id"])

        if state.get("champion"):
            self.status_var.set(f"🏆 Turnier beendet - Sieger: {state['champion']}")

    # ---------------- Match starten ----------------

    def play_selected(self):
        if self.app.tourn:
            messagebox.showinfo("Match läuft", "An dieser Station läuft bereits ein Match.", parent=self)
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Match wählen", "Bitte zuerst ein Match auswählen.", parent=self)
            return
        m = self._matches.get(sel[0])
        if not m or (m["status"] == "running" and m["station"] != self.client.station):
            messagebox.showinfo("Match nicht verfügbar",
                                "Dieses Match läuft schon an einer anderen Station.", parent=self)
            return
        if m["status"] == "ready" and m.get("busy"):
            messagebox.showinfo("Spieler belegt",
                                f"{m['busy']} spielt gerade ein anderes Match. Bitte kurz warten.", parent=self)
            return
        self.play_btn.configure(state="disabled")

        def done(info, err):
            self.play_btn.configure(state="normal")
            if err:
                messagebox.showerror("Match konnte nicht gestartet werden", str(err), parent=self)
                self.refresh_now()
                return
            self.withdraw()
            self.app.start_tournament_match(self.client, info)

        run_async(self, lambda: self.client.claim(m["id"]), done)
