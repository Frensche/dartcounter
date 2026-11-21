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
FOCUS = "#ffc928"   # sichtbarer Tastaturfokus
CHIP_COLORS = {"triple": RED, "double": GREEN, "single": "#34373d"}   # Finish-Wege: Triple / Double / Single

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


def place_dialog(win):
    """Größe aus dem fertigen Inhalt berechnen, festsetzen und zentrieren.

    Muss aufgerufen werden, NACHDEM alle Widgets gebaut sind und BEVOR das Fenster angezeigt wird -
    sonst bleibt es auf manchen Fenstermanagern (z. B. labwc) auf der leeren Anfangsgröße stehen.
    """
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w = min(win.winfo_reqwidth(), sw - 40)
    h = min(win.winfo_reqheight(), sh - 80)
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
    win.resizable(False, False)


def fit_window(win, width, height, min_size=(640, 420)):
    """Fenster mit Wunschgröße, aber nie größer als der Bildschirm, zentriert."""
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(width, sw - 40), min(height, sh - 80)
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
    win.minsize(min(min_size[0], w), min(min_size[1], h))


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
        s.configure(w, background=BG, focuscolor="#555555", indicatorbackground=CARD)
        s.map(w, background=[("active", BG)])

    for w in ("TEntry", "TSpinbox", "TCombobox"):
        s.configure(w, fieldbackground=CARD, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=6)
        s.map(w, bordercolor=[("focus", RED)], lightcolor=[("focus", RED)], darkcolor=[("focus", RED)])
    s.configure("TSpinbox", arrowsize=14, padding=4)

    def button(style, bg, hover, fg="white", font=("", 10, "bold"), pad=(16, 8)):
        s.configure(style, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg, darkcolor=bg,
                    focuscolor="white", padding=pad, font=font, relief="flat", borderwidth=2)
        # Tastaturfokus: gelber Rahmen, damit man sieht, welcher Button mit Enter/Leertaste ausgelöst wird
        s.map(style,
              background=[("disabled", "#d5d7db"), ("pressed", hover), ("active", hover)],
              bordercolor=[("disabled", "#d5d7db"), ("focus", FOCUS), ("active", hover)],
              lightcolor=[("disabled", "#d5d7db"), ("focus", FOCUS), ("active", hover)],
              darkcolor=[("disabled", "#d5d7db"), ("focus", FOCUS), ("active", hover)],
              foreground=[("disabled", "#9a9da3")])

    button("TButton", "#2b2d31", "#4a4d54")
    button("Accent.TButton", RED, RED_HOVER, font=("", 11, "bold"), pad=(18, 10))
    button("Quick.TButton", "#34373d", "#565a62", font=("", 12, "bold"), pad=(8, 12))
    button("Danger.TButton", "#7a2a31", "#9b3640")
    button("Rest.TButton", "#b86e00", "#d98200", font=("", 12, "bold"), pad=(8, 12))
    button("MiniBad.TButton", "#7a2a31", "#9b3640", font=("", 12, "bold"), pad=(8, 12))
    button("MiniTriple.TButton", RED, RED_HOVER, font=("", 12, "bold"), pad=(8, 12))
    button("Finish.TButton", GREEN, "#238a23", font=("", 12, "bold"), pad=(8, 12))

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
    s.configure("Big.Treeview", rowheight=40, font=("", 13))
    s.configure("Stats.Treeview", rowheight=32, font=("", 12))
    enable_keyboard(root)


# --------------------------------------------------------------------------
# Tastaturbedienung (Touchpad-freundlich)
# --------------------------------------------------------------------------

def _radio_move(event, step):
    """Pfeiltasten wechseln zwischen den Auswahlpunkten einer Gruppe (und wählen sie aus)."""
    w = event.widget
    try:
        var = str(w.cget("variable"))
        siblings = [c for c in w.master.winfo_children()
                    if c.winfo_class() == "TRadiobutton" and str(c.cget("variable")) == var]
    except tk.TclError:
        return None
    if len(siblings) < 2 or w not in siblings:
        return None
    nxt = siblings[(siblings.index(w) + step) % len(siblings)]
    nxt.focus_set()
    nxt.invoke()
    return "break"


def enable_keyboard(root):
    """Enter löst fokussierte Buttons aus, Pfeiltasten wechseln Optionen (Radiobuttons)."""
    root.bind_class("TButton", "<Return>", lambda e: (e.widget.invoke(), "break")[1])
    root.bind_class("TButton", "<KP_Enter>", lambda e: (e.widget.invoke(), "break")[1])
    root.bind_class("TCheckbutton", "<Return>", lambda e: (e.widget.invoke(), "break")[1])
    for key, step in (("Up", -1), ("Left", -1), ("Down", 1), ("Right", 1)):
        root.bind_class("TRadiobutton", f"<{key}>", lambda e, st=step: _radio_move(e, st))


def bind_dialog_keys(win, ok=None, cancel=None):
    """Return = bestätigen, Escape = abbrechen."""
    if ok:
        win.bind("<Return>", lambda e: (ok(), "break")[1])
        win.bind("<KP_Enter>", lambda e: (ok(), "break")[1])
    win.bind("<Escape>", lambda e: ((cancel or win.destroy)(), "break")[1])


def tab_moves_focus(text_widget):
    """In mehrzeiligen Textfeldern soll Tab den Fokus weiterbewegen statt ein Tabulatorzeichen einzufügen."""
    text_widget.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
    text_widget.bind("<Shift-Tab>", lambda e: (e.widget.tk_focusPrev().focus_set(), "break")[1])
    text_widget.bind("<ISO_Left_Tab>", lambda e: (e.widget.tk_focusPrev().focus_set(), "break")[1])


# --------------------------------------------------------------------------
# Zahleneingabe: nur Ziffern erlaubt
# --------------------------------------------------------------------------

def digits_only(widget, maxlen=3):
    """Lässt in einem Eingabefeld nur Ziffern zu (Buchstaben und Sonderzeichen werden einfach nicht angenommen)."""
    check = widget.register(lambda proposed: proposed == "" or (proposed.isdigit() and len(proposed) <= maxlen))
    widget.configure(validate="key", validatecommand=(check, "%P"))
    return widget


def num_spinbox(parent, variable, lo, hi, width=5, **kw):
    """Zahlen-Spinbox, die nur Ziffern annimmt."""
    sp = ttk.Spinbox(parent, from_=lo, to=hi, textvariable=variable, width=width, **kw)
    return digits_only(sp, maxlen=len(str(hi)))


def get_int(variable, default, lo=None, hi=None):
    """Zahl aus einer Variablen lesen; bei leerem/ungültigem Feld der Standardwert, sonst auf lo..hi begrenzt."""
    try:
        value = int(variable.get())
    except (tk.TclError, ValueError, TypeError):
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value
