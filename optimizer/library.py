"""Сведения об играх для библиотеки: время в игре, последний запуск, размер, движок."""
import time
from pathlib import Path

from . import steam, vdf

ENGINES = {"source2": "Source 2", "source": "Source", "unity": "Unity", "unreal": "Unreal Engine"}


def playtimes(root) -> dict:
    """appid -> (минут в игре, unix-время последнего запуска). Берём максимум по всем аккаунтам."""
    res = {}
    for cfg in steam.localconfigs(root) if root else []:
        try:
            data = vdf.parse(cfg.read_text("utf-8", errors="replace"))
        except OSError:
            continue
        node = vdf.get_ci(data, "UserLocalConfigStore") or {}
        for part in ("Software", "Valve", "Steam", "apps"):
            node = vdf.get_ci(node, part) or {}
        for appid, app in node.items():
            if not isinstance(app, dict):
                continue
            mins = int(app.get("Playtime", 0) or 0) if str(app.get("Playtime", "0")).isdigit() else 0
            last = int(app.get("LastPlayed", 0) or 0) if str(app.get("LastPlayed", "0")).isdigit() else 0
            pm, pl = res.get(appid, (0, 0))
            res[appid] = (max(pm, mins), max(pl, last))
    return res


def size_on_disk(game) -> int:
    acf = Path(game.path).parent.parent / f"appmanifest_{game.appid}.acf"
    try:
        st = vdf.get_ci(vdf.parse(acf.read_text("utf-8", errors="replace")), "AppState") or {}
        return int(st.get("SizeOnDisk", 0))
    except (OSError, ValueError):
        return 0


def engine(game):
    p = Path(game.path)
    if (p / "game" / "bin" / "win64").is_dir() and any(p.glob("game/*/gameinfo.gi")):
        return "source2"
    if any(p.glob("*/gameinfo.txt")) and any(p.glob("hl2*.exe")):
        return "source"
    if any(p.glob("UnityPlayer.dll")) or any(p.glob("*/UnityPlayer.dll")) or any(p.glob("*_Data/globalgamemanagers")):
        return "unity"
    if (p / "Engine" / "Binaries").is_dir() or any(p.glob("*/Binaries/Win64/*-Shipping.exe")):
        return "unreal"
    return None


def fmt_hours(minutes: int) -> str:
    if minutes <= 0:
        return "не запускалась"
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes / 60:.0f} ч" if minutes >= 600 else f"{minutes / 60:.1f} ч".replace(".", ",")


def fmt_size(b: int) -> str:
    if b <= 0:
        return "—"
    gb = b / 1024 ** 3
    return f"{gb:.1f} ГБ".replace(".", ",") if gb < 100 else f"{gb:.0f} ГБ"


def fmt_ago(ts: int) -> str:
    if not ts:
        return "никогда"
    d = (time.time() - ts) / 86400
    if d < 1:
        return "сегодня"
    if d < 2:
        return "вчера"
    if d < 30:
        return f"{d:.0f} дн. назад"
    return time.strftime("%d.%m.%Y", time.localtime(ts))
