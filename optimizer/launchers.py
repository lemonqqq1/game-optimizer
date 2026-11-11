"""Поиск игр других лаунчеров (Epic Games Launcher) и общий список игр."""
import json
import os
from pathlib import Path

from . import steam

# appid ("epic:<AppName>") -> LaunchExecutable относительно папки игры (из манифеста Epic)
EXECUTABLES: dict = {}


def _manifests_dir() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"


def _is_game(m: dict) -> bool:
    name = str(m.get("AppName", ""))
    if not name or name.startswith("UE_"):
        return False
    cats = [str(c).lower() for c in (m.get("AppCategories") or []) if isinstance(c, str)]
    if cats and any(c.endswith(("engines", "plugins")) or c in ("engines", "plugins") for c in cats):
        return False
    return True


def epic_games(manifests_dir=None) -> list:
    """Установленные игры Epic: Game(appid="epic:<AppName>", name, path). Битые манифесты пропускаются."""
    d = Path(manifests_dir) if manifests_dir else _manifests_dir()
    games = []
    try:
        files = sorted(d.glob("*.item"))
    except OSError:
        return []
    for f in files:
        try:
            m = json.loads(f.read_text("utf-8-sig", errors="replace"))
            if not isinstance(m, dict) or m.get("bIsIncompleteInstall") or not _is_game(m):
                continue
            path = Path(str(m.get("InstallLocation", "")))
            name = str(m.get("DisplayName") or m["AppName"])
            if not str(m.get("InstallLocation", "")).strip() or not path.is_dir():
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        appid = "epic:" + str(m["AppName"])
        if m.get("LaunchExecutable"):
            EXECUTABLES[appid] = str(m["LaunchExecutable"])
        games.append(steam.Game(appid, name, path))
    return sorted(games, key=lambda g: g.name.lower())


def all_games(steam_root) -> list:
    """Steam + Epic, по имени. steam_root может быть None."""
    games = steam.installed_games(steam_root) if steam_root else []
    return sorted(games + epic_games(), key=lambda g: g.name.lower())
