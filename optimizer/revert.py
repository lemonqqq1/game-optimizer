"""Откат всех изменений по журналу (в обратном порядке)."""
import shutil
import subprocess
from pathlib import Path

from . import ctx, gpu, journal, registry as reg


def _revert(e: dict):
    kind = e["kind"]
    if kind == "reg":
        reg.restore(e)
    elif kind == "file":
        p = Path(e["path"])
        if e["backup"]:
            shutil.copy2(e["backup"], p)
        elif p.exists():
            p.unlink()
    elif kind == "powerplan":
        subprocess.run(["powercfg", "/setactive", e["guid"]], capture_output=True)
    elif kind == "powerscheme_created":
        subprocess.run(["powercfg", "/delete", e["guid"]], capture_output=True)
    elif kind == "nvidia":
        gpu.nvidia_revert(e.get("keys"))


def revert_all() -> int:
    items = journal.load()
    done = 0
    for e in reversed(items):
        try:
            _revert(e)
            done += 1
        except Exception as ex:  # продолжаем откат остальных
            ctx.log(f"  не удалось откатить {e.get('kind')} {e.get('path', '')}: {ex}")
    journal.clear()
    ctx.log(f"Откат завершён: восстановлено записей {done} из {len(items)}")
    return done
