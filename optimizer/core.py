"""Сценарий «оптимизировать»: используется и GUI, и командной строкой."""
import subprocess

from . import ctx, games, gpu, revert, steam, system_tweaks


def restore_point():
    ctx.log("Создаю точку восстановления Windows...")
    if ctx.dry_run:
        return
    ps = ('Checkpoint-Computer -Description "GameOptimizer" '
          '-RestorePointType MODIFY_SETTINGS -ErrorAction Stop')
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=0x08000000)
    ctx.log("  готово" if r.returncode == 0 else "  не создана (Windows разрешает одну точку в сутки или защита отключена)")


def run(tweak_ids, game_list, gpu_obj, make_restore_point=True, gpu_keys=None):
    if make_restore_point:
        restore_point()
    if gpu_obj:
        ctx.log(f"Видеокарта: {gpu_obj.name}")
        gpu.apply_for(gpu_obj, gpu_keys)
    for t in system_tweaks.TWEAKS:
        if t.id in tweak_ids:
            ctx.log(f"{t.title}:")
            t.fn()
    root = steam.steam_root()
    for g in game_list:
        games.optimize(g, root)
    ctx.log("Готово. Перезагрузи ПК, чтобы применились все настройки.")


def undo():
    revert.revert_all()
