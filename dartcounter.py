#!/usr/bin/env python3
"""
Dartcounter - Dart-Scorer für Linux (TSV Feichten).

Eingabe:
  F1-F8        frei belegbare Schnell-Scores (Standard: 0, 26, 41, 45, 60, 81, 85, 100)
  F9 oder R    Rest: statt der geworfenen Punkte die Restpunktzahl eingeben
  F10/F11/F12  Finish mit 1/2/3 Darts (auch Strg+1/2/3) - trägt automatisch den Rest ein
  Zahl + Enter eigene Aufnahme (nur Ziffern); bei einem Finish wird nach den Darts gefragt

Weitere Funktionen: 1-4 Spieler, 301/501/701, Double-Out, Legs, Handicap, Münzwurf/Ausbullen,
Finish-Wege für alle Spieler, Statistik nach dem Spiel, Turniermodus (KO / Gruppen + KO) mit
Turnierleiter-Server und Stationen, Kiosk-Modus, vollständige Tastaturbedienung.

Start:
    python3 dartcounter.py               (Kiosk-Modus / Vollbild)
    python3 dartcounter.py --windowed    (normales Fenster, z.B. zum Testen)

Benötigt:
    sudo apt install python3-tk   (falls tkinter noch nicht installiert ist)
"""

import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

import config
import lock
import theme
import tournament_ui
from config import DEFAULT_FKEYS, SCORE_KEYS, load_config, save_config   # save_config: Rückwärtskompatibilität
from engine import (IMPOSSIBLE_TURN_SCORES, MAX_TURN_SCORE, Player, chip_kind, finish_options,
                    solve_checkout)
from game_dialogs import (DartsDialog, MainMenuDialog, NewGameDialog, SettingsDialog, StartOrderDialog,
                          StatsDialog)
from tournament import (DEFAULT_PORT, TOURNAMENT_PATH, Tournament, TournamentClient, TournamentError,
                        TournamentServer, start_scores)

# Schriftgrößen in Punkten bei 1920x1080 - werden mit der Fenstergröße skaliert
FONT_SPEC = {
    "name": (24, "bold"), "score": (84, "bold"), "sub": (15, "normal"), "caption": (10, "bold"),
    "chip": (28, "bold"), "recent": (17, "bold"), "fkey": (19, "bold"),
    "entry": (26, "bold"), "entrylbl": (14, "normal"), "log": (14, "bold"),
}
PLAYER_FONTS = ("name", "score", "sub", "chip", "recent")   # werden bei 3-4 Spielern zusätzlich verkleinert
FKEY_STYLES = ["Quick.TButton"] * SCORE_KEYS + ["Rest.TButton"] + ["Finish.TButton"] * 3
INACTIVE_NAME_BG = "#dfe2e6"


class DartCounterApp:
    def __init__(self, root, kiosk=True):
        self.root = root
        self.root.title("Dartcounter - TSV Feichten")
        theme.apply_style(self.root)
        theme.set_window_icon(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.request_quit)
        if kiosk:
            self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        else:
            theme.fit_window(self.root, 1280, 800, (900, 600))

        self.cfg = load_config()

        self.players = []
        self.start_score = self.cfg.get("start_score", 501)
        self.double_out = self.cfg.get("double_out", True)
        self.legs_to_win = self.cfg.get("legs_to_win", 1)
        self.current_idx = 0
        self.leg_starter_idx = 0
        self.leg_no = 1
        self.history = []          # Undo-Stack
        self.match_over = False
        self.rest_mode = False     # F9 / R: nächste Eingabe ist die Restpunktzahl
        self.last_setup = None     # Einstellungen des letzten Spiels (für Revanche)
        self._rescale_job = None

        # Turniermodus
        self.tourn = None          # laufendes Turnier-Match an dieser Station
        self.tournament = None     # Turnier, das dieser Rechner leitet (Server)
        self.server = None
        self.master_win = None
        self.station_panel = None

        self._make_fonts()
        self._build_menu()
        self._build_layout()

        self.fullscreen = False
        if kiosk:
            self._set_fullscreen(True)
        self.root.bind("<Configure>", self._on_configure, add="+")

        # Direkt beim Start ein neues Spiel anbieten
        self.root.after(150, self.new_game)

    # ---------------- Schriften ----------------

    def _make_fonts(self):
        family = tkfont.nametofont("TkDefaultFont").actual("family")
        self.fonts = {key: tkfont.Font(root=self.root, family=family, size=size, weight=weight)
                      for key, (size, weight) in FONT_SPEC.items()}
        style = ttk.Style(self.root)
        for name in ("Quick.TButton", "Rest.TButton", "Finish.TButton"):
            style.configure(name, font=self.fonts["fkey"], padding=(6, 4))

    def _on_configure(self, event):
        if event.widget is not self.root:
            return
        if self._rescale_job:
            self.root.after_cancel(self._rescale_job)
        self._rescale_job = self.root.after(60, self._rescale)

    def _rescale(self):
        """Schriften an die Fenstergröße anpassen, damit der ganze Platz genutzt wird."""
        self._rescale_job = None
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w < 200 or h < 200:
            return
        scale = max(0.5, min(w / 1920, h / 1080, 2.5))
        n = max(1, min(len(self.players), 4))
        per_player = {1: 1.0, 2: 1.0, 3: 0.8, 4: 0.65}[n]
        for key, (size, _) in FONT_SPEC.items():
            factor = scale * (per_player if key in PLAYER_FONTS else 1.0)
            self.fonts[key].configure(size=max(7, round(size * factor)))
        card_w = max(160, w // n - 70)
        for pw in self.player_widgets:
            pw["recent"].configure(wraplength=card_w)

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
                ("Schnell-Scores F1-F8 bearbeiten...", "", self.open_settings),
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
            "EINGABE\n"
            "F1-F8: Schnell-Scores (änderbar unter Einstellungen)\n"
            "F9 oder R: Rest - Restpunktzahl statt der geworfenen Punkte eingeben\n"
            "F10 / F11 / F12 oder Strg+1 / 2 / 3: Finish mit 1 / 2 / 3 Darts\n"
            "Zahl + Enter: eigene Aufnahme (nur Ziffern), Strg+Z: rückgängig\n\n"
            "OHNE MAUS\n"
            "Esc: Hauptmenü (Pfeiltasten, Enter)\n"
            "Strg+N: Neues Spiel   Strg+W: Wer beginnt?   Strg+R: Leg neu\n"
            "Strg+Q: Beenden   Strg+Umschalt+K: Kiosk ein/aus\n"
            "Strg+Umschalt+N / O / L: Turnier neu / fortsetzen / Leiter-Fenster\n"
            "Strg+Umschalt+S / P: Station verbinden / Station-Fenster\n"
            "Alt+S, Alt+T, Alt+E, Alt+H: Menüleiste öffnen\n"
            "In Fenstern: Tab / Pfeiltasten wechseln, Enter bestätigt, Esc bricht ab\n\n"
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
        lock.ChangePasswordDialog(self.root, self.cfg, config.save_config)

    def _unlock_master(self):
        if self.master_win and self.master_win.winfo_exists():
            return True
        return lock.ask_password(self.root, self.cfg, "Der Turnierleiter-Bereich ist passwortgeschützt.")

    # ---------------- Layout ----------------

    def _build_layout(self):
        outer = ttk.Frame(self.root, padding=(16, 10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=5)   # Spielerfelder
        outer.rowconfigure(3, weight=4)   # F-Tasten

        # Kopfzeile: Logo + Spielinfo
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        logo = theme.load_image("logo_small.png")
        if logo:
            ttk.Label(header, image=logo).pack(side="left", padx=(0, 14))
        ttk.Button(header, text="☰  Menü  [Esc]", command=self.open_main_menu).pack(side="right")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text="TSV Feichten - Dartcounter", style="Title.TLabel").pack(anchor="w")
        self.info_var = tk.StringVar(value="")
        ttk.Label(titles, textvariable=self.info_var, style="Muted.TLabel", font=("", 12)).pack(anchor="w")

        # Spielerfelder (nehmen den meisten Platz ein)
        self.players_container = ttk.Frame(outer)
        self.players_container.grid(row=1, column=0, sticky="nsew")
        self.player_widgets = []

        # Eingabezeile
        input_row = ttk.Frame(outer)
        input_row.grid(row=2, column=0, sticky="ew", pady=(10, 8))
        self.entry_lbl_var = tk.StringVar()
        ttk.Label(input_row, textvariable=self.entry_lbl_var, font=self.fonts["entrylbl"]).pack(side="left")
        self.entry_var = tk.StringVar()
        self.entry = ttk.Entry(input_row, textvariable=self.entry_var, width=5, font=self.fonts["entry"],
                               justify="center")
        theme.digits_only(self.entry, 3)    # nur Ziffern
        self.entry.pack(side="left", padx=12)
        ttk.Button(input_row, text="Bestätigen  [Enter]", style="Accent.TButton",
                   command=self.submit_manual).pack(side="left", padx=4)
        ttk.Button(input_row, text="Undo  [Strg+Z]", command=self.undo).pack(side="left", padx=4)
        self.mode_lbl = tk.Label(input_row, text="", font=self.fonts["log"], fg="white", bg=theme.BG, padx=14, pady=4)
        self.mode_lbl.pack(side="left", padx=14)
        self.log_var = tk.StringVar(value="")
        self.log_lbl = tk.Label(input_row, textvariable=self.log_var, font=self.fonts["log"], fg=theme.MUTED,
                                bg=theme.BG, anchor="e")
        self.log_lbl.pack(side="right", fill="x", expand=True)

        # F-Tasten: 4 x 3 große Felder
        self.fkey_frame = ttk.Frame(outer)
        self.fkey_frame.grid(row=3, column=0, sticky="nsew")
        self._build_fkey_buttons()

        # Turnier-Leiste (nur sichtbar, solange an dieser Station ein Turnier-Match läuft)
        self.tourn_bar = ttk.LabelFrame(outer, text="Turnier-Match", padding=10)
        self.tourn_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.tourn_var = tk.StringVar(value="")
        ttk.Label(self.tourn_bar, textvariable=self.tourn_var, font=("", 12, "bold")).pack(side="left")
        ttk.Button(self.tourn_bar, text="Match abbrechen", style="Danger.TButton",
                   command=self.abort_tournament_match).pack(side="right", padx=4)
        self.send_btn = ttk.Button(self.tourn_bar, text="Ergebnis senden", style="Accent.TButton",
                                   command=self.send_tournament_result, state="disabled")
        self.send_btn.pack(side="right", padx=4)
        self.tourn_bar.grid_remove()

        self._update_mode_ui()
        self._bind_keys()

    def _bind_keys(self):
        r = self.root
        shortcuts = {
            "<Escape>": self.open_main_menu, "<Menu>": self.open_main_menu,
            "<Control-n>": self.new_game, "<Control-w>": self.change_starter, "<Control-r>": self.restart_leg,
            "<Control-q>": self.request_quit, "<Control-K>": self.toggle_kiosk,
            "<Control-N>": self.new_tournament, "<Control-O>": self.resume_tournament,
            "<Control-L>": self.show_master, "<Control-S>": self.connect_station,
            "<Control-P>": self.show_station_panel,
            "<Control-z>": self.undo,
            "<KeyPress-r>": self.toggle_rest, "<KeyPress-R>": self.toggle_rest,
        }
        for seq, fn in shortcuts.items():
            r.bind(seq, lambda e, f=fn: (f(), "break")[1])
        # F-Tasten: "break" verhindert, dass Tk zusätzlich das Menü öffnet (F10)
        for i in range(12):
            r.bind(f"<F{i + 1}>", lambda e, idx=i: (self.submit_fkey(idx), "break")[1])
        for darts in (1, 2, 3):
            r.bind(f"<Control-Key-{darts}>", lambda e, d=darts: (self.finish_with(d), "break")[1])
        # Ziffern landen immer im Eingabefeld, auch wenn dort gerade nicht der Fokus liegt
        for d in "0123456789":
            r.bind(f"<KeyPress-{d}>", self._digit_key)
        self.entry.bind("<Return>", lambda e: (self.submit_manual(), "break")[1])
        self.entry.bind("<KP_Enter>", lambda e: (self.submit_manual(), "break")[1])

    def _digit_key(self, event):
        if self.root.focus_get() is self.entry or not self.players:
            return None
        if self.root.focus_get() is not None and self.root.focus_get().winfo_class() in ("TEntry", "TSpinbox", "Entry"):
            return None
        self.entry.focus_set()
        self.entry.insert("end", event.char)
        return "break"

    def _build_fkey_buttons(self):
        for child in self.fkey_frame.winfo_children():
            child.destroy()
        for c in range(4):
            self.fkey_frame.columnconfigure(c, weight=1, uniform="fk")
        for r in range(3):
            self.fkey_frame.rowconfigure(r, weight=1, uniform="fkr")
        fkeys = self.cfg.get("fkeys", list(DEFAULT_FKEYS))
        self.fkey_btns = []
        for i in range(12):
            if i < SCORE_KEYS:
                text = f"F{i + 1}\n{fkeys[i]}"
            elif i == SCORE_KEYS:
                text = f"F{i + 1}  ·  R\nREST"
            else:
                d = i - SCORE_KEYS
                text = f"F{i + 1}  ·  Strg+{d}\nFINISH  {d} Dart{'s' if d > 1 else ''}"
            btn = ttk.Button(self.fkey_frame, text=text, style=FKEY_STYLES[i],
                             command=lambda idx=i: self.submit_fkey(idx))
            btn.grid(row=i // 4, column=i % 4, padx=5, pady=5, sticky="nsew")
            self.fkey_btns.append(btn)

    def _rebuild_player_panels(self):
        for child in self.players_container.winfo_children():
            child.destroy()
        self.player_widgets = []
        self.players_container.rowconfigure(0, weight=1)
        for i, p in enumerate(self.players):
            self.players_container.columnconfigure(i, weight=1, uniform="players")
            frame = tk.Frame(self.players_container, bg=theme.CARD, highlightthickness=3,
                             highlightbackground=theme.LINE, padx=10, pady=8)
            frame.grid(row=0, column=i, sticky="nsew", padx=6)

            name_lbl = tk.Label(frame, text=p.name, font=self.fonts["name"], bg=INACTIVE_NAME_BG, fg=theme.INK,
                                pady=4)
            name_lbl.pack(fill="x")
            score_lbl = tk.Label(frame, text=str(p.score), font=self.fonts["score"], bg=theme.CARD, fg=theme.INK)
            score_lbl.pack(expand=True, fill="both")
            sub_lbl = tk.Label(frame, text="", font=self.fonts["sub"], bg=theme.CARD, fg=theme.INK)
            sub_lbl.pack()
            fin_cap = tk.Label(frame, text="FINISH", font=self.fonts["caption"], bg=theme.CARD, fg=theme.MUTED)
            fin_cap.pack(pady=(10, 0))
            chips = tk.Frame(frame, bg=theme.CARD)
            chips.pack(pady=(2, 0))
            rec_cap = tk.Label(frame, text="LETZTE WÜRFE", font=self.fonts["caption"], bg=theme.CARD,
                               fg=theme.MUTED)
            rec_cap.pack(pady=(12, 0))
            recent_lbl = tk.Label(frame, text="-", font=self.fonts["recent"], bg=theme.CARD, fg=theme.INK,
                                  justify="center")
            recent_lbl.pack(pady=(0, 4))

            self.player_widgets.append({
                "frame": frame, "name": name_lbl, "score": score_lbl, "sub": sub_lbl,
                "fin_cap": fin_cap, "chips": chips, "recent": recent_lbl,
            })
        self._rescale()

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
            if self.players:
                return
            # kein Spiel konfiguriert und keins läuft -> Spiel mit den letzten Namen anlegen
            names = (self.cfg.get("last_names") or ["Spieler 1", "Spieler 2"])[:4]
            result = {
                "names": names, "handicaps": [0] * len(names),
                "start_score": self.cfg.get("start_score", 501),
                "double_out": self.cfg.get("double_out", True),
                "legs_to_win": self.cfg.get("legs_to_win", 1),
            }
        else:
            result = dlg.result
        self.start_game(result)

    def start_game(self, setup):
        self.start_score = setup["start_score"]
        self.double_out = setup["double_out"]
        self.legs_to_win = setup["legs_to_win"]
        names = list(setup["names"])
        handicaps = list(setup.get("handicaps") or [0] * len(names))
        if not self.tourn:
            self.last_setup = {"names": names, "handicaps": handicaps, "start_score": self.start_score,
                               "double_out": self.double_out, "legs_to_win": self.legs_to_win}
            self.cfg.update({"start_score": self.start_score, "double_out": self.double_out,
                             "legs_to_win": self.legs_to_win, "last_names": names,
                             "last_handicaps": handicaps, "last_players": len(names)})
            config.save_config(self.cfg)

        starts = setup.get("start_scores") or start_scores(self.start_score, handicaps)
        self.players = [Player(name, sc) for name, sc in zip(names, starts)]
        for p in self.players:
            p.reset_leg()
        self.current_idx = 0
        self.leg_starter_idx = 0
        self.leg_no = 1
        self.history = []
        self.match_over = False
        self.rest_mode = False
        self.entry_var.set("")

        self._rebuild_player_panels()
        self._update_mode_ui()
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
        self._say(f"{self.players[starter].name} beginnt.")
        self.refresh()
        self.entry.focus_set()

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
            p.drop_leg_turns(self.leg_no)
        self.current_idx = self.leg_starter_idx
        self.history = []
        self.match_over = False
        self.rest_mode = False
        self._update_mode_ui()
        self.refresh()

    def open_settings(self):
        SettingsDialog(self.root, self.cfg, self._build_fkey_buttons)

    # ---------------- Meldungen / Eingabemodus ----------------

    def _say(self, text, error=False):
        self.log_var.set(text)
        self.log_lbl.configure(fg="#b00020" if error else theme.MUTED)
        if error:
            self.root.bell()

    def _update_mode_ui(self):
        if self.rest_mode:
            self.entry_lbl_var.set("Rest eingeben:")
            self.mode_lbl.configure(text="REST-EINGABE AKTIV  (F9 / R = abbrechen)", bg="#b86e00")
        else:
            self.entry_lbl_var.set("Geworfene Punkte (0-180):")
            self.mode_lbl.configure(text="", bg=theme.BG, padx=0)
            return
        self.mode_lbl.configure(padx=14)

    def toggle_rest(self):
        if self.match_over or not self.players:
            return
        self.rest_mode = not self.rest_mode
        self._update_mode_ui()
        self.entry.focus_set()

    # ---------------- Score-Eingabe ----------------

    def submit_fkey(self, idx):
        if self.match_over or not self.players:
            return
        if idx < SCORE_KEYS:
            fkeys = self.cfg.get("fkeys", list(DEFAULT_FKEYS))
            self.submit_score(fkeys[idx])
        elif idx == SCORE_KEYS:
            self.toggle_rest()
        else:
            self.finish_with(idx - SCORE_KEYS)

    def submit_manual(self):
        if self.match_over or not self.players:
            return
        raw = self.entry_var.get().strip()
        if not raw.isdigit():
            return
        self.entry_var.set("")
        if self.rest_mode:
            self.submit_rest(int(raw))
        else:
            self.submit_score(int(raw))

    def submit_rest(self, rest):
        """Restpunktzahl eingegeben -> geworfene Punkte = bisheriger Stand - Rest."""
        player = self.players[self.current_idx]
        if rest > player.score:
            self._say(f"Rest {rest} ist größer als der aktuelle Stand ({player.score}).", error=True)
            return
        if self.double_out and rest == 1:
            self._say("Rest 1 ist bei Double-Out nicht möglich.", error=True)
            return
        self.submit_score(player.score - rest)

    def submit_score(self, score):
        """Geworfene Punkte einer Aufnahme prüfen und eintragen (bei einem Finish wird nach den Darts gefragt)."""
        if self.match_over or not self.players:
            return
        player = self.players[self.current_idx]
        if score > MAX_TURN_SCORE:
            self._say(f"{score} Punkte sind in einer Aufnahme nicht möglich (maximal {MAX_TURN_SCORE}).", error=True)
            return
        if score in IMPOSSIBLE_TURN_SCORES:
            self._say(f"{score} Punkte lassen sich mit drei Darts nicht werfen.", error=True)
            return
        if score == player.score:                       # direktes Finish
            options = finish_options(player.score, self.double_out)
            if not options:
                self._say(f"{player.score} lässt sich nicht auschecken - bitte die Eingabe prüfen.", error=True)
                return
            darts = options[0] if len(options) == 1 else self._ask_darts(player, options)
            if darts is None:
                return
            self._apply_turn(score, darts)
        else:
            self._apply_turn(score, 3)

    def finish_with(self, darts):
        """F10 / F11 / F12 bzw. Strg+1 / 2 / 3: trägt den Rest des aktuellen Spielers als Finish mit n Darts ein."""
        if self.match_over or not self.players:
            return
        player = self.players[self.current_idx]
        if darts not in finish_options(player.score, self.double_out):
            self._say(f"{player.score} lässt sich nicht mit {darts} Dart{'s' if darts > 1 else ''} "
                      f"auschecken.", error=True)
            return
        self._apply_turn(player.score, darts)

    def _ask_darts(self, player, options):
        dlg = DartsDialog(self.root, player.name, player.score, options)
        self.root.wait_window(dlg)
        self.entry.focus_set()
        return dlg.result

    def _apply_turn(self, turn_score, darts=3):
        player = self.players[self.current_idx]
        prev_score = player.score
        remaining = prev_score - turn_score
        bust = remaining < 0 or (self.double_out and remaining == 1)

        self.history.append({"player_idx": self.current_idx, "prev_score": prev_score, "won_leg": False})
        self.rest_mode = False
        self._update_mode_ui()

        if bust:
            player.add_turn(self.leg_no, turn_score, 3, True, prev_score)
            self._say(f"{player.name}: {turn_score} -> BUST! Der Stand bleibt bei {prev_score}.", error=True)
        else:
            finish = remaining == 0
            player.score = remaining
            player.add_turn(self.leg_no, turn_score, darts if finish else 3, False, prev_score, finish=finish)
            if finish:
                self._say(f"{player.name}: CHECKOUT mit {darts} Dart{'s' if darts > 1 else ''}!")
                self._handle_leg_win(player)
                self.refresh()
                if self.match_over:
                    self.show_stats()
                return
            self._say(f"{player.name}: {turn_score} -> Rest {remaining}")

        self._advance_player()
        self.refresh()

    def _handle_leg_win(self, player):
        player.legs_won += 1
        if player.legs_won >= self.legs_to_win:
            self.match_over = True
            self.history[-1]["won_leg"] = True  # Undo muss das Leg wieder abziehen
        else:
            messagebox.showinfo(
                "Leg gewonnen",
                f"🎯 {player.name} gewinnt das Leg!\nStand: " +
                ", ".join(f"{p.name} {p.legs_won}" for p in self.players)
            )
            # nächstes Leg: Startspieler rotiert
            self.leg_starter_idx = (self.leg_starter_idx + 1) % len(self.players)
            self.leg_no += 1
            for p in self.players:
                p.reset_leg()
            self.current_idx = self.leg_starter_idx
            self.history = []

    def show_stats(self):
        """Übersicht mit Statistiken am Spielende; danach Revanche / neues Spiel / schließen."""
        winner = max(self.players, key=lambda p: p.legs_won)
        dlg = StatsDialog(self.root, self.players, winner, tournament=bool(self.tourn))
        self.root.wait_window(dlg)
        if dlg.result == "rematch" and self.last_setup and not self.tourn:
            self.start_game(dict(self.last_setup))
        elif dlg.result == "new" and not self.tourn:
            self.new_game()
        elif self.tourn:
            self.send_btn.focus_set()
        else:
            self.entry.focus_set()

    def _advance_player(self):
        self.current_idx = (self.current_idx + 1) % len(self.players)

    def undo(self):
        if not self.history:
            return
        last = self.history.pop()
        player = self.players[last["player_idx"]]
        player.pop_turn()
        if last.get("won_leg"):
            player.legs_won -= 1
        player.score = last["prev_score"]
        self.current_idx = last["player_idx"]
        self.match_over = False
        self.rest_mode = False
        self._update_mode_ui()
        self._say(f"Undo: {player.name} zurück auf {player.score}")
        self.refresh()

    # ---------------- Anzeige ----------------

    def refresh(self):
        if not self.players:
            return
        mode = "Double-Out" if self.double_out else "Straight-Out"
        starts = {p.start_score for p in self.players}
        start_txt = (" / ".join(str(p.start_score) for p in self.players) + " (Handicap)"
                     if len(starts) > 1 else str(self.start_score))
        self.info_var.set(f"Start: {start_txt}   |   {mode}   |   First to {self.legs_to_win} Leg(s)")

        handicap = len(starts) > 1
        for i, p in enumerate(self.players):
            w = self.player_widgets[i]
            active = (i == self.current_idx) and not self.match_over
            w["frame"].configure(highlightbackground=theme.RED if active else theme.LINE,
                                 highlightthickness=7 if active else 3)
            w["name"].configure(bg=theme.RED if active else INACTIVE_NAME_BG, fg="white" if active else theme.INK,
                                text=("▶  " if active else "") + p.name)
            w["score"].configure(text=str(p.score))
            extra = f"      Start {p.start_score}" if handicap else ""
            w["sub"].configure(text=f"Legs {p.legs_won}      Ø {p.average:.1f}{extra}")
            w["recent"].configure(text=p.recent_text(self.leg_no))
            self._render_finish(w, p)

        # Finish-Tasten nur anbieten, wenn der aktuelle Spieler damit wirklich auschecken kann
        cur = self.players[self.current_idx]
        options = [] if self.match_over else finish_options(cur.score, self.double_out)
        for d in (1, 2, 3):
            self.fkey_btns[SCORE_KEYS + d].configure(state="normal" if d in options else "disabled")

        if self.tourn:
            self.send_btn.configure(state="normal" if self.match_over else "disabled")

    def _render_finish(self, w, p):
        """Finish-Weg des Spielers als große farbige Felder (immer sichtbar, auch wenn er nicht am Zug ist)."""
        for child in w["chips"].winfo_children():
            child.destroy()
        route = solve_checkout(p.score, 3, self.double_out) if p.score > 0 else None
        if route:
            w["fin_cap"].configure(text=f"FINISH  ·  {len(route)} Dart{'s' if len(route) > 1 else ''}")
            for label in route:
                tk.Label(w["chips"], text=label, font=self.fonts["chip"], fg="white",
                         bg=theme.CHIP_COLORS[chip_kind(label)], padx=12, pady=2).pack(side="left", padx=4)
            return
        w["fin_cap"].configure(text="FINISH")
        if p.score == 0:
            text = "geschafft!"
        elif p.score > 170 or (not self.double_out and p.score > 180):
            text = "noch kein Finish möglich"
        else:
            text = "kein Finish möglich"
        tk.Label(w["chips"], text=text, font=self.fonts["recent"], fg=theme.MUTED, bg=theme.CARD).pack()


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
        config.save_config(self.cfg)
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
            config.save_config(self.cfg)
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
        self.tourn_bar.grid()
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
        self.tourn_bar.grid_remove()
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
