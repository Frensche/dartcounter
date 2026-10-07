"""Passwortschutz für den Turnierleiter-Bereich und das Verlassen des Kiosk-Modus.

Das Passwort wird nie im Klartext gespeichert (PBKDF2-SHA256). Wer die Konfiguration
unter ~/.config/dartcounter/ ändern kann, kann den Schutz aber umgehen - es ist eine
Sperre gegen versehentliche Bedienung durch Mitspieler, kein Hochsicherheitssystem.
"""

import hashlib
import hmac
import os
import tkinter as tk
from tkinter import ttk

import theme

ITERATIONS = 200_000
# Standard-Passwort-Hash (das Klartext-Passwort steht bewusst nicht im Code)
DEFAULT_SALT = "5d1c7ab94e0f3a28c6b1d97e42f08a35"
DEFAULT_HASH = "b76a4b481e35cacf1a5d3e4265d7b888afd3133aec4eef11a353db164f293bba"
MIN_LENGTH = 4


def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex),
                               ITERATIONS).hex()


def verify_password(cfg, password):
    salt, expected = cfg.get("password_salt"), cfg.get("password_hash")
    if not salt or not expected:
        salt, expected = DEFAULT_SALT, DEFAULT_HASH
    return hmac.compare_digest(_hash(password, salt), expected)


def set_password(cfg, new_password):
    salt = os.urandom(16).hex()
    cfg["password_salt"] = salt
    cfg["password_hash"] = _hash(new_password, salt)


class PasswordDialog(tk.Toplevel):
    def __init__(self, master, cfg, reason):
        super().__init__(master)
        self.cfg = cfg
        self.ok = False
        self.title("Passwort erforderlich")
        self.resizable(False, False)
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=20)
        frm.pack()
        logo = theme.load_image("logo_small.png")
        if logo:
            ttk.Label(frm, image=logo).grid(row=0, column=0, rowspan=3, padx=(0, 16))
        ttk.Label(frm, text="Geschützter Bereich", font=("", 13, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text=reason, style="Muted.TLabel", wraplength=280).grid(row=1, column=1, sticky="w", pady=(2, 8))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(frm, textvariable=self.var, show="•", width=26)
        self.entry.grid(row=2, column=1, sticky="w")
        self.msg = tk.Label(frm, text="", fg="#b00020", bg=theme.BG)
        self.msg.grid(row=3, column=1, sticky="w", pady=(4, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(14, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Entsperren", style="Accent.TButton", command=self._check).pack(side="right")

        theme.bind_dialog_keys(self, ok=self._check)
        theme.modal(self)
        self.entry.focus_set()

    def _check(self):
        if verify_password(self.cfg, self.var.get()):
            self.ok = True
            self.destroy()
        else:
            self.var.set("")
            self.msg.configure(text="Falsches Passwort")
            self.entry.focus_set()


def ask_password(parent, cfg, reason="Bitte Passwort eingeben."):
    dlg = PasswordDialog(parent, cfg, reason)
    parent.wait_window(dlg)
    return dlg.ok


class ChangePasswordDialog(tk.Toplevel):
    def __init__(self, master, cfg, save):
        super().__init__(master)
        self.cfg, self.save = cfg, save
        self.title("Passwort ändern")
        self.resizable(False, False)
        self.transient(master)
        theme.set_window_icon(self)

        frm = ttk.Frame(self, padding=20)
        frm.pack()
        self.vars = []
        for i, label in enumerate(("Aktuelles Passwort:", "Neues Passwort:", "Neues Passwort wiederholen:")):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 10))
            var = tk.StringVar()
            ttk.Entry(frm, textvariable=var, show="•", width=24).grid(row=i, column=1, pady=4)
            self.vars.append(var)
        self.msg = tk.Label(frm, text="", fg="#b00020", bg=theme.BG)
        self.msg.grid(row=3, column=0, columnspan=2, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Speichern", style="Accent.TButton", command=self._save).pack(side="right")
        theme.bind_dialog_keys(self, ok=self._save)
        theme.modal(self)

    def _save(self):
        old, new, again = (v.get() for v in self.vars)
        if not verify_password(self.cfg, old):
            self.msg.configure(text="Das aktuelle Passwort stimmt nicht.")
        elif len(new) < MIN_LENGTH:
            self.msg.configure(text=f"Das neue Passwort braucht mindestens {MIN_LENGTH} Zeichen.")
        elif new != again:
            self.msg.configure(text="Die beiden neuen Passwörter sind nicht gleich.")
        else:
            set_password(self.cfg, new)
            self.save(self.cfg)
            self.destroy()
