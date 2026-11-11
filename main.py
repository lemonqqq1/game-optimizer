"""Game Optimizer: запуск без аргументов открывает окно.

CLI: --list | --scan | --apply-all | --revert, плюс --dry-run (ничего не менять).
"""
import argparse
import ctypes
import sys

from optimizer import core, ctx, gpu, launchers, recommend, scan, steam


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
    ap.add_argument("--scan", action="store_true", help="скан ПК и подобранные настройки (ничего не меняет)")
    ap.add_argument("--apply-all", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--clean-temp", action="store_true", help="также очистить TEMP (необратимо)")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    a = ap.parse_args()
    ctx.dry_run = a.dry_run

    if not a.dry_run and not a.list and not a.scan and not is_admin():
        elevate()

    if a.list:
        for g in gpu.detect():
            print(f"GPU: {g.name} [{g.vendor}] driver {g.driver}")
        root = steam.steam_root()
        print(f"Steam: {root}")
        for g in launchers.all_games(root):
            print(f"  {g.appid:>8}  {g.name}")
    elif a.scan:
        specs = scan.scan()
        print("Скан ПК:")
        for label, value in specs.summary():
            print(f"  {label}: {value}")
        print(f"Оценка: {specs.score}/100, уровень: {core.TIER_NAMES.get(specs.tier, specs.tier)}")
        print("Что будет подобрано под это железо:")
        for title, reason in recommend.build(specs).notes:
            print(f"  - {title}: {reason}")
    elif a.apply_all:
        root = steam.steam_root()
        _, plan = core.auto(None, launchers.all_games(root), make_restore_point=not a.dry_run)
        if a.clean_temp:
            from optimizer import system_tweaks
            for t in system_tweaks.TWEAKS:
                if t.id == "temp":
                    ctx.log(f"{t.title}:")
                    t.fn()
    elif a.revert:
        core.undo()
    else:
        from optimizer import gui
        gui.main()


if __name__ == "__main__":
    main()
