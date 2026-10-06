"""
Oberfläche für den Turniermodus (tkinter):

- NewTournamentDialog: Turnier anlegen (Name, Spieler, Modus)
- MasterWindow:        Turnierleiter - Turnierbaum, Stationen, Ergebnisse korrigieren
- ConnectDialog:       Verbindung zum Turnier-Server herstellen
- StationPanel:        Station - offene Matches ansehen und eins zum Spielen auswählen
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tournament import (BYE, DEFAULT_PORT, MAX_PLAYERS, MIN_PLAYERS, ONLINE_SECONDS,
                        TournamentError, clean_players, local_ip)


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
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.grid(sticky="nsew")
        pad = {"padx": 8, "pady": 5}

        ttk.Label(frm, text="Turniername:").grid(row=0, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value="Dart-Turnier")
        ttk.Entry(frm, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Spieler\n(einer pro Zeile):").grid(row=1, column=0, sticky="nw", **pad)
        txt_frame = ttk.Frame(frm)
        txt_frame.grid(row=1, column=1, sticky="w", **pad)
        self.txt = tk.Text(txt_frame, width=28, height=12)
        sb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left")
        sb.pack(side="left", fill="y")
        self.count_var = tk.StringVar(value="0 Spieler")
        ttk.Label(frm, textvariable=self.count_var, foreground="#666").grid(row=2, column=1, sticky="w", padx=8)
        self.txt.bind("<KeyRelease>", lambda e: self._update_count())
        self.txt.focus_set()

        ttk.Label(frm, text="Startpunktzahl:").grid(row=3, column=0, sticky="w", **pad)
        self.start_score = tk.IntVar(value=cfg.get("start_score", 501))
        sf = ttk.Frame(frm)
        sf.grid(row=3, column=1, sticky="w", **pad)
        for s in (301, 501, 701):
            ttk.Radiobutton(sf, text=str(s), value=s, variable=self.start_score).pack(side="left", padx=4)

        self.double_out = tk.BooleanVar(value=cfg.get("double_out", True))
        ttk.Checkbutton(frm, text="Double-Out", variable=self.double_out).grid(
            row=4, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Legs zum Sieg (First to):").grid(row=5, column=0, sticky="w", **pad)
        self.legs = tk.IntVar(value=2)
        ttk.Spinbox(frm, from_=1, to=21, textvariable=self.legs, width=5).grid(row=5, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Legs zum Sieg im Finale:").grid(row=6, column=0, sticky="w", **pad)
        self.final_legs = tk.IntVar(value=3)
        ttk.Spinbox(frm, from_=1, to=21, textvariable=self.final_legs, width=5).grid(
            row=6, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Anzahl Stationen:").grid(row=7, column=0, sticky="w", **pad)
        self.stations = tk.IntVar(value=6)
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self.stations, width=5).grid(row=7, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Server-Port:").grid(row=8, column=0, sticky="w", **pad)
        self.port = tk.IntVar(value=cfg.get("tournament_port", DEFAULT_PORT))
        ttk.Spinbox(frm, from_=1024, to=65535, textvariable=self.port, width=7).grid(
            row=8, column=1, sticky="w", **pad)

        self.shuffle = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Spieler zufällig auslosen (sonst Reihenfolge = Setzliste)",
                        variable=self.shuffle).grid(row=9, column=0, columnspan=2, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="Turnier starten", command=self._on_ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

    def _players(self):
        return [line for line in self.txt.get("1.0", "end").splitlines() if line.strip()]

    def _update_count(self):
        n = len(self._players())
        self.count_var.set(f"{n} Spieler (erlaubt: {MIN_PLAYERS}-{MAX_PLAYERS})")

    def _on_ok(self):
        try:
            players = clean_players(self._players())
            self.result = {
                "name": self.name_var.get().strip() or "Dart-Turnier",
                "players": players,
                "start_score": self.start_score.get(),
                "double_out": self.double_out.get(),
                "legs_to_win": max(1, self.legs.get()),
                "final_legs_to_win": max(1, self.final_legs.get()),
                "stations": max(1, self.stations.get()),
                "port": self.port.get(),
                "shuffle": self.shuffle.get(),
            }
        except (TournamentError, tk.TclError) as e:
            self.result = None
            messagebox.showerror("Turnier", str(e), parent=self)
            return
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
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.grid()
        ttk.Label(frm, text=match["label"], font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(frm, text="Sieger").grid(row=1, column=0)
        ttk.Label(frm, text="Spieler").grid(row=1, column=1)
        ttk.Label(frm, text="Legs").grid(row=1, column=2)

        self.winner = tk.StringVar(value=match["winner"] or "")
        self.legs_vars = []
        old = match.get("legs") or [0, 0]
        for i, name in enumerate(match["p"]):
            ttk.Radiobutton(frm, value=name, variable=self.winner).grid(row=2 + i, column=0)
            ttk.Label(frm, text=name, width=22).grid(row=2 + i, column=1, sticky="w", padx=6)
            var = tk.IntVar(value=old[i])
            ttk.Spinbox(frm, from_=0, to=99, textvariable=var, width=4).grid(row=2 + i, column=2, pady=3)
            self.legs_vars.append(var)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(btns, text="Speichern", command=self._ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

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

BOX_W, ROW_H, GAP_X, V_GAP, LEFT, TOP = 210, 24, 56, 26, 20, 46


class MasterWindow(tk.Toplevel):
    def __init__(self, master, tournament, server, on_close):
        super().__init__(master)
        self.t = tournament
        self.server = server
        self.on_close = on_close
        self.selected = None
        self._last_version = None
        self._after = None
        self._pos = {}

        self.title(f"Turnierleiter - {tournament.name}")
        self.geometry("1240x720")

        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(header, text=tournament.name, font=("", 15, "bold")).pack(side="left")
        self.champion_var = tk.StringVar()
        ttk.Label(header, textvariable=self.champion_var, font=("", 13, "bold"), foreground="#2a7a2a").pack(
            side="left", padx=20)
        addr = f"{local_ip()}:{server.port}"
        ttk.Label(header, text=f"Stationen verbinden sich mit:  {addr}", font=("", 11)).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Turnierbaum
        canvas_frame = ttk.Frame(body)
        canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#f4f4f4", highlightthickness=0)
        xsb = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        ysb = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        xsb.pack(side="bottom", fill="x")
        ysb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        # Seitenleiste
        side = ttk.Frame(body, padding=10, width=300)
        side.pack(side="right", fill="y")

        st_frame = ttk.LabelFrame(side, text="Stationen", padding=8)
        st_frame.pack(fill="x")
        self.station_labels = []
        for n in range(1, tournament.stations + 1):
            lbl = tk.Label(st_frame, text="", justify="left", anchor="w", wraplength=270)
            lbl.pack(fill="x", pady=2)
            self.station_labels.append(lbl)

        sel_frame = ttk.LabelFrame(side, text="Ausgewähltes Match", padding=8)
        sel_frame.pack(fill="x", pady=(12, 0))
        self.sel_var = tk.StringVar(value="Match im Baum anklicken")
        ttk.Label(sel_frame, textvariable=self.sel_var, wraplength=270, justify="left").pack(fill="x", pady=(0, 6))
        self.btn_result = ttk.Button(sel_frame, text="Ergebnis eintragen / korrigieren...",
                                     command=self.edit_result, state="disabled")
        self.btn_result.pack(fill="x", pady=2)
        self.btn_release = ttk.Button(sel_frame, text="Match an Station freigeben",
                                      command=self.release_match, state="disabled")
        self.btn_release.pack(fill="x", pady=2)
        self.btn_reset = ttk.Button(sel_frame, text="Ergebnis zurücksetzen",
                                    command=self.reset_match, state="disabled")
        self.btn_reset.pack(fill="x", pady=2)

        ttk.Label(side, foreground="#666", wraplength=270, justify="left",
                  text="Gelb = bereit, blau = läuft an einer Station, weiß = beendet. "
                       "Ergebnisse von den Stationen erscheinen automatisch im Baum. "
                       "Der Turnierstand wird laufend gespeichert.").pack(fill="x", pady=(12, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._tick()

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
        self._update_stations(snap)
        self._update_selection(snap)
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
            lbl.configure(text=line1 + line2, fg="#1b6b1b" if online else "#777777")

    def _update_selection(self, snap):
        m = next((x for x in snap["matches"] if x["id"] == self.selected), None)
        if not m:
            self.sel_var.set("Match im Baum anklicken")
            for b in (self.btn_result, self.btn_release, self.btn_reset):
                b.configure(state="disabled")
            return
        status = {"waiting": "wartet auf Vorrunde", "ready": "spielbereit",
                  "running": f"läuft an Station {m['station']}", "done": "beendet"}[m["status"]]
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

    # ---------------- Zeichnen ----------------

    def _draw(self, snap):
        c = self.canvas
        c.delete("all")
        self._pos = {}
        matches = snap["matches"]
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
        self.grab_set()

        frm = ttk.Frame(self, padding=15)
        frm.grid()
        pad = {"padx": 8, "pady": 5}
        ttk.Label(frm, text="IP-Adresse des Turnierleiters:").grid(row=0, column=0, sticky="w", **pad)
        self.host = tk.StringVar(value=cfg.get("tournament_host", ""))
        e = ttk.Entry(frm, textvariable=self.host, width=22)
        e.grid(row=0, column=1, **pad)
        e.focus_set()
        ttk.Label(frm, text="Port:").grid(row=1, column=0, sticky="w", **pad)
        self.port = tk.IntVar(value=cfg.get("tournament_port", DEFAULT_PORT))
        ttk.Spinbox(frm, from_=1024, to=65535, textvariable=self.port, width=7).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Diese Station (Nr.):").grid(row=2, column=0, sticky="w", **pad)
        self.station = tk.IntVar(value=cfg.get("tournament_station", 1))
        ttk.Spinbox(frm, from_=1, to=16, textvariable=self.station, width=5).grid(row=2, column=1, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="Verbinden", command=self._ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)
        self.bind("<Return>", lambda ev: self._ok())

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
        self.geometry("620x440")

        self.head_var = tk.StringVar()
        ttk.Label(self, textvariable=self.head_var, font=("", 13, "bold"), padding=(10, 10, 10, 2)).pack(fill="x")
        self.status_var = tk.StringVar()
        self.status_lbl = tk.Label(self, textvariable=self.status_var, anchor="w", padx=10)
        self.status_lbl.pack(fill="x")

        ttk.Label(self, text="Spielbereite Matches - eins auswählen und hier spielen:",
                  padding=(10, 10, 10, 2)).pack(fill="x")
        tree_frame = ttk.Frame(self, padding=(10, 0))
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("round", "players", "status"), show="headings",
                                 selectmode="browse", height=10)
        self.tree.heading("round", text="Runde")
        self.tree.heading("players", text="Spieler")
        self.tree.heading("status", text="Status")
        self.tree.column("round", width=170)
        self.tree.column("players", width=260)
        self.tree.column("status", width=130)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-Button-1>", lambda e: self.play_selected())

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        self.play_btn = ttk.Button(btns, text="Ausgewähltes Match hier spielen", command=self.play_selected)
        self.play_btn.pack(side="left")
        ttk.Button(btns, text="Aktualisieren", command=self.refresh_now).pack(side="left", padx=8)
        ttk.Button(btns, text="Trennen", command=self.destroy).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_state(state)
        self._schedule()

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
        self.status_lbl.configure(fg="#1b6b1b")

        mine, ready, other = [], [], []
        for m in state["matches"]:
            if m["status"] == "running" and m["station"] == n:
                mine.append(m)
            elif m["status"] == "ready":
                ready.append(m)
            elif m["status"] == "running":
                other.append(m)

        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self._matches = {}
        for group, label in ((mine, "läuft hier (fortsetzen)"), (ready, "bereit"), (other, None)):
            for m in group:
                status = label or f"läuft an Station {m['station']}"
                self.tree.insert("", "end", iid=m["id"],
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
