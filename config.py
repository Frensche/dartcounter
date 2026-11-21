"""Einstellungen (~/.config/dartcounter/config.json)."""

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "dartcounter")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# F1-F8: frei belegbare Schnell-Scores. F9 / R = Rest, F10-F12 = Finish mit 1/2/3 Darts (fest).
DEFAULT_FKEYS = [0, 26, 41, 45, 60, 81, 85, 100]
OLD_DEFAULT_FKEYS = [26, 41, 45, 60, 81, 85, 95, 100, 110, 120, 140, 180]   # alte Belegung (F1-F12)
SCORE_KEYS = len(DEFAULT_FKEYS)

DEFAULT_CONFIG = {
    "fkeys": list(DEFAULT_FKEYS),
    "start_score": 501,
    "double_out": True,
    "legs_to_win": 1,
}


def migrate_fkeys(fkeys):
    """Alte Konfigurationen (12 Scores) auf die neue Belegung (8 Scores) umstellen."""
    if not isinstance(fkeys, list) or fkeys == OLD_DEFAULT_FKEYS:
        return list(DEFAULT_FKEYS)
    cleaned = [v for v in fkeys[:SCORE_KEYS] if isinstance(v, int) and 0 <= v <= 180]
    return cleaned if len(cleaned) == SCORE_KEYS else list(DEFAULT_FKEYS)


def load_config(path=None):
    path = path or CONFIG_PATH
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    cfg["fkeys"] = migrate_fkeys(cfg.get("fkeys"))
    return cfg


def save_config(cfg, path=None):
    path = path or CONFIG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
