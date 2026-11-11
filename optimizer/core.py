"""Сценарий «оптимизировать»: используется и GUI, и командной строкой."""
import subprocess

from . import ctx, games, gpu, recommend, revert, scan as scan_mod, steam, system_tweaks


TIER_NAMES = {"low": "Слабый ПК", "mid": "Средний ПК", "high": "Мощный ПК"}


def restore_point():
    ctx.log("Создаю точку восстановления Windows...")
    if ctx.dry_run:
        return
    ps = ('Checkpoint-Computer -Description "GameOptimizer" '
          '-RestorePointType MODIFY_SETTINGS -ErrorAction Stop')
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=0x08000000)
    ctx.log("  готово" if r.returncode == 0 else "  не создана (Windows разрешает одну точку в сутки или защита отключена)")


def run(tweak_ids, game_list, gpu_obj, make_restore_point=True, gpu_keys=None, tier="mid", gpu_values=None):
    if make_restore_point:
        restore_point()
    if gpu_obj:
        ctx.log(f"Видеокарта: {gpu_obj.name}")
        gpu.apply_for(gpu_obj, gpu_keys, gpu_values)
    for t in system_tweaks.TWEAKS:
        if t.id in tweak_ids:
            ctx.log(f"{t.title}:")
            t.fn()
    root = steam.steam_root()
    for g in game_list:
        games.optimize(g, root, tier)
    ctx.log("Готово. Перезагрузи ПК, чтобы применились все настройки.")


def auto(specs=None, game_list=None, make_restore_point=True):
    """Скан ПК (если specs не передан), подбор настроек по железу и применение. Возвращает (specs, plan)."""
    if specs is None:
        ctx.log("Сканирую железо...")
        specs = scan_mod.scan()
    plan = recommend.build(specs)
    ctx.log("Скан ПК:")
    for label, value in specs.summary():
        ctx.log(f"  {label}: {value}")
    ctx.log(f"  Оценка: {specs.score}/100, уровень: {TIER_NAMES.get(specs.tier, specs.tier)}")
    for title, reason in plan.notes:
        ctx.log(f"  • {title}: {reason}")
    gpu_obj = specs.gpu
    if gpu_obj:  # scan.GpuInfo совместим с gpu.Gpu (name, vendor, driver)
        gpu_obj = gpu.Gpu(gpu_obj.name, gpu_obj.vendor, gpu_obj.driver)
    run(set(plan.tweak_ids), game_list or [], gpu_obj, make_restore_point, plan.gpu_keys, plan.game_tier,
        plan.gpu_values)
    return specs, plan


def undo():
    revert.revert_all()
