"""Game Optimizer: запуск без аргументов открывает окно.

CLI: --list | --apply-all | --revert, плюс --dry-run (ничего не менять).
"""
import argparse
import ctypes
import sys

from optimizer import core, ctx, gpu, steam, system_tweaks


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """Перезапуск с правами администратора (нужно для HKLM и драйвера)."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="показать видеокарту и игры")
    ap.add_argument("--apply-all", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--clean-temp", action="store_true", help="также очистить TEMP (необратимо)")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    a = ap.parse_args()
    ctx.dry_run = a.dry_run

    if not a.dry_run and not a.list and not is_admin():
        elevate()

    if a.list:
        for g in gpu.detect():
            print(f"GPU: {g.name} [{g.vendor}] driver {g.driver}")
        root = steam.steam_root()
        print(f"Steam: {root}")
        for g in (steam.installed_games(root) if root else []):
            print(f"  {g.appid:>8}  {g.name}")
    elif a.apply_all:
        gpus = gpu.detect()
        root = steam.steam_root()
        games = steam.installed_games(root) if root else []
        core.run({t.id for t in system_tweaks.TWEAKS if t.id != "temp" or a.clean_temp}, games, gpus[0] if gpus else None,
                 make_restore_point=not a.dry_run)
    elif a.revert:
        core.undo()
    else:
        from optimizer import gui
        gui.main()


if __name__ == "__main__":
    main()
