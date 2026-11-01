"""Журнал изменений: всё, что программа меняет, записывается сюда, чтобы откатить."""
import json
import os
import shutil
import time
from pathlib import Path


def state_dir() -> Path:
    base = os.environ.get("HO_STATE_DIR") or str(
        Path(os.environ.get("APPDATA", str(Path.home()))) / "GameOptimizer")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file() -> Path:
    return state_dir() / "journal.json"


def load() -> list:
    try:
        return json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list):
    _file().write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")


def record(entry: dict):
    items = load()
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    items.append(entry)
    _save(items)


def backup_file(path):
    """Вызывать перед изменением или созданием файла."""
    path = Path(path)
    if path.exists():
        dst = state_dir() / "backups" / f"{time.time_ns()}_{path.name}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        record({"kind": "file", "path": str(path), "backup": str(dst)})
    else:
        record({"kind": "file", "path": str(path), "backup": None})


def clear():
    _save([])
