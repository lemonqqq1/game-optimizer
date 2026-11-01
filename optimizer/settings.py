"""Настройки программы (избранное, прицел, монитор) в settings.json рядом с журналом."""
import copy
import json

from . import journal

DEFAULTS = {
    "favorites": [],
    "sort": "recent",
    "crosshair": {"style": "Крест с точкой", "color": "#00ff66", "size": 9, "thick": 2, "gap": 4,
                  "outline": True, "enabled": False},
    "monitor": {"corner": "Слева сверху", "enabled": False},
    "timer": False,
}


def _file():
    return journal.state_dir() / "settings.json"


def load() -> dict:
    data = copy.deepcopy(DEFAULTS)
    try:
        saved = json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return data
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    return data


def save(data: dict):
    _file().write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
