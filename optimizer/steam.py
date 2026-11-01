"""Поиск Steam, установленных игр и запись параметров запуска."""
import re
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

from . import ctx, journal, vdf

_SKIP_APPIDS = {"228980"}  # Steamworks Common Redistributables
_SKIP_WORDS = ("redistributable", "proton", "steam linux runtime", "wallpaper engine", "soundtrack",
               "soundpad", "3dmark", "obs studio", "dedicated server", "sdk")


class SteamRunning(Exception):
    pass


@dataclass
class Game:
    appid: str
    name: str
    path: Path


def steam_root():
    for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        for val in ("SteamPath", "InstallPath"):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    p = Path(winreg.QueryValueEx(k, val)[0])
                    if p.exists():
                        return p
            except OSError:
                pass
    for p in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(p).exists():
            return Path(p)
    return None


def libraries(root: Path) -> list:
    libs = [root]
    f = root / "steamapps" / "libraryfolders.vdf"
    if f.exists():
        data = vdf.parse(f.read_text("utf-8", errors="replace"))
        top = vdf.get_ci(data, "libraryfolders") or {}
        for v in top.values():
            if isinstance(v, dict) and "path" in v:
                libs.append(Path(v["path"]))
    seen, out = set(), []
    for p in libs:
        if str(p).lower() not in seen and p.exists():
            seen.add(str(p).lower())
            out.append(p)
    return out


def installed_games(root: Path) -> list:
    games = []
    for lib in libraries(root):
        apps = lib / "steamapps"
        for acf in apps.glob("appmanifest_*.acf"):
            st = vdf.get_ci(vdf.parse(acf.read_text("utf-8", errors="replace")), "AppState") or {}
            appid, name, d = st.get("appid", ""), st.get("name", ""), st.get("installdir", "")
            if not appid or appid in _SKIP_APPIDS or any(w in name.lower() for w in _SKIP_WORDS):
                continue
            path = apps / "common" / d
            if path.exists():
                games.append(Game(appid, name, path))
    return sorted(games, key=lambda g: g.name.lower())


def is_steam_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                         capture_output=True, text=True, errors="replace", creationflags=0x08000000).stdout
    return "steam.exe" in out.lower()


def localconfigs(root: Path) -> list:
    return list((root / "userdata").glob("*/config/localconfig.vdf"))


def merge_flags(existing: str, wanted: list) -> str:
    """Дописывает флаги, которых ещё нет. Если флаг уже задан пользователем, не трогает его."""
    tokens = existing.split()
    out = existing.strip()
    for chunk in wanted:
        if chunk.split()[0] not in tokens:
            out = (out + " " + chunk).strip()
    return out


def strip_flags(existing: str, chunks) -> str:
    """Убирает ровно те флаги (вместе со значением), которые когда-то добавила программа."""
    out = existing
    for chunk in chunks:
        out = re.sub(r"(?<!\S)" + re.escape(chunk) + r"(?!\S)", " ", out)
    return " ".join(out.split())


def get_launch_options(root: Path, appid: str) -> str:
    for cfg in localconfigs(root) if root else []:
        data = vdf.parse(cfg.read_text("utf-8", errors="replace"))
        node = vdf.get_ci(data, "UserLocalConfigStore") or {}
        for part in ("Software", "Valve", "Steam", "apps", appid):
            node = vdf.get_ci(node, part) or {}
        val = next((v for k, v in node.items() if k.lower() == "launchoptions"), "")
        if val:
            return val
    return ""


def set_launch_options(root: Path, appid: str, wanted: list, remove=()) -> bool:
    """Требует закрытого Steam, иначе он перезапишет файл при выходе."""
    cfgs = localconfigs(root)
    if not cfgs:
        return False
    if not ctx.dry_run and is_steam_running():
        raise SteamRunning("Steam запущен: закрой его, чтобы записать параметры запуска")
    changed = False
    for cfg in cfgs:
        data = vdf.parse(cfg.read_text("utf-8", errors="replace"))
        node = vdf.get_ci(data, "UserLocalConfigStore", create=True)
        for part in ("Software", "Valve", "Steam", "apps"):
            node = vdf.get_ci(node, part, create=True)
        app = vdf.get_ci(node, appid, create=True)
        key = next((k for k in app if k.lower() == "launchoptions"), "LaunchOptions")
        old = app.get(key, "")
        new = merge_flags(strip_flags(old, remove), wanted)
        if new == old:
            continue
        ctx.log(f"  параметры запуска [{appid}]: {new}")
        if not ctx.dry_run:
            journal.backup_file(cfg)
            app[key] = new
            cfg.write_text(vdf.dump(data), "utf-8")
        changed = True
    return changed
