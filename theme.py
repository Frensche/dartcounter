"""Gemeinsames Aussehen (Farben, moderne Buttons) und Logo-Handling."""

import os
import tkinter as tk
from tkinter import ttk

RED = "#b5081a"
RED_HOVER = "#cf1a2c"
INK = "#1d1d20"
BG = "#eef0f2"
CARD = "#ffffff"
MUTED = "#6b6f76"
LINE = "#c9ccd1"
GREEN = "#1b6b1b"

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_images = {}  # Referenzen halten, sonst räumt Tk die Bilder ab


def load_image(name):
    """Lädt ein PNG aus assets/ (None, wenn es fehlt oder nicht lesbar ist)."""
    if name in _images:
        return _images[name]
    try:
        img = tk.PhotoImage(file=os.path.join(ASSET_DIR, name))
    except (tk.TclError, OSError):
        img = None
    _images[name] = img
    return img


def set_window_icon(win):
    img = load_image("logo_large.png")
    if img:
        try:
            win.iconphoto(True, img)
        except tk.TclError:
            pass


def modal(win):
    """Fenster modal machen (grab schlägt auf manchen Systemen fehl, solange das Fenster nicht sichtbar ist)."""
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    win.focus_set()


def apply_style(root):
    root.configure(bg=BG)
    root.option_add("*Toplevel.background", BG)
    root.option_add("*Menu.font", ("", 10))
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass

    s.configure(".", background=BG, foreground=INK, font=("", 10))
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=CARD)
    s.configure("TLabel", background=BG, foreground=INK)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Title.TLabel", font=("", 16, "bold"))
    s.configure("Good.TLabel", foreground=GREEN, font=("", 13, "bold"))
    s.configure("TLabelframe", background=BG, bordercolor=LINE, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=BG, foreground=INK, font=("", 10, "bold"))
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, background=BG, focuscolor=BG)
        s.map(w, background=[("active", BG)])

    s.configure("TEntry", fieldbackground=CARD, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=6)
    s.configure("TSpinbox", fieldbackground=CARD, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                arrowsize=14, padding=4)

    def button(style, bg, hover, fg="white", font=("", 10, "bold"), pad=(16, 8)):
        s.configure(style, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg, darkcolor=bg,
                    focuscolor=bg, padding=pad, font=font, relief="flat", borderwidth=0)
        s.map(style,
              background=[("disabled", "#d5d7db"), ("pressed", hover), ("active", hover)],
              bordercolor=[("disabled", "#d5d7db"), ("active", hover)],
              lightcolor=[("disabled", "#d5d7db"), ("active", hover)],
              darkcolor=[("disabled", "#d5d7db"), ("active", hover)],
              foreground=[("disabled", "#9a9da3")])

    button("TButton", "#2b2d31", "#4a4d54")
    button("Accent.TButton", RED, RED_HOVER, font=("", 11, "bold"), pad=(18, 10))
    button("Quick.TButton", "#34373d", "#565a62", font=("", 12, "bold"), pad=(8, 12))
    button("Danger.TButton", "#7a2a31", "#9b3640")

    s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK, rowheight=28,
                bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, borderwidth=1)
    s.configure("Treeview.Heading", background="#dfe2e6", foreground=INK, font=("", 10, "bold"),
                relief="flat", padding=6)
    s.map("Treeview", background=[("selected", "#f0c4ca")], foreground=[("selected", INK)])
    s.map("Treeview.Heading", background=[("active", "#d0d4d9")])

    s.configure("TNotebook", background=BG, borderwidth=0)
    s.configure("TNotebook.Tab", background="#dfe2e6", foreground=INK, padding=(18, 8), font=("", 10, "bold"),
                borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", RED)])
    s.configure("TScrollbar", background="#c9ccd1", troughcolor=BG, bordercolor=BG, arrowcolor=INK)
