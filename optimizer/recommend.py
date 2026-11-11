"""Подбор настроек по результатам скана железа: что включать в драйвере и Windows и почему."""
import re
from dataclasses import dataclass, field

from . import gpu as gpu_mod, system_tweaks
from .scan import Specs


@dataclass
class Plan:
    gpu_keys: list = field(default_factory=list)     # ключи gpu.NVIDIA / gpu.AMD для применения
    gpu_values: dict = field(default_factory=dict)   # ключ -> значение драйвера, отличное от Setting.value
    tweak_ids: list = field(default_factory=list)    # id из system_tweaks.TWEAKS (без "temp")
    game_tier: str = "mid"                           # low | mid | high: пресет графики в играх
    notes: list = field(default_factory=list)        # [(заголовок, причина)] для показа пользователю


def supports_hags(gpu_name: str, vendor: str) -> bool:
    """Аппаратное планирование GPU: NVIDIA GTX 10xx и новее (GTX 16xx, RTX), AMD RX 5000 и новее."""
    n = (gpu_name or "").lower()
    if vendor == "nvidia":
        if re.search(r"\brtx\b", n):
            return True
        m = re.search(r"\bgtx\s*(\d{3,4})", n)
        return bool(m) and int(m.group(1)) >= 1000
    if vendor == "amd":
        m = re.search(r"\brx\s*(\d{4})", n)
        return bool(m) and int(m.group(1)) >= 5000
    return False


def _nvidia(specs: Specs, p: Plan, g):
    hz = specs.monitor.hz if specs.monitor else 0
    keys = [s.key for s in gpu_mod.NVIDIA]
    hw = f"{g.name}, {g.vram_gb:g} ГБ"
    if specs.tier == "low":
        p.notes.append(("Режим низкой задержки: Вкл", f"{hw}: слабая система, Ultra даёт лишнюю нагрузку на CPU"))
    else:
        p.gpu_values["lowlat"] = 2
        p.notes.append(("Режим низкой задержки: Ultra", f"{hw}: мощная система, Ultra минимизирует очередь кадров"))
    if specs.tier == "low":
        p.notes.append(("Фильтрация текстур: высокая производительность",
                        f"{hw}: видеопамяти и мощности мало, экономим ресурсы GPU"))
    elif specs.tier == "mid":
        p.gpu_values["texq"] = 10
        p.notes.append(("Фильтрация текстур: производительность", f"{hw}: баланс качества и FPS"))
    else:
        keys.remove("texq")
        p.notes.append(("Фильтрация текстур: качество (по умолчанию драйвера)",
                        f"{hw}: запаса мощности достаточно, качество не режем"))
    if hz >= 120:
        p.gpu_values["fpslimit"] = hz - 3
        p.notes.append((f"Лимит FPS: {hz - 3}", f"Монитор {hz} Гц: ограничение на 3 кадра ниже частоты "
                        "работает с G-Sync/VRR без разрыва и без задержки V-Sync"))
    else:
        p.notes.append(("Лимит FPS: без ограничения", f"Монитор {hz or 'неизвестно'} Гц (меньше 120): "
                        "ограничение не нужно, меньше задержка"))
    p.gpu_keys = keys


def _amd(specs: Specs, p: Plan, g):
    keys = [s.key for s in gpu_mod.AMD]
    if specs.is_laptop and "ulps" in keys:
        keys.remove("ulps")
        p.notes.append(("ULPS не отключаем", f"{g.name}: это ноутбук, отключение энергосбережения ULPS "
                        "перегревает и разряжает батарею"))
    p.gpu_keys = keys


def build(specs: Specs) -> Plan:
    """Строит план настроек по Specs. Каждое решение, зависящее от железа, объясняется в notes."""
    p = Plan(game_tier=specs.tier)
    g = specs.gpu
    ids = {t.id for t in system_tweaks.TWEAKS}
    if g and g.vendor == "nvidia":
        _nvidia(specs, p, g)
    elif g and g.vendor == "amd":
        _amd(specs, p, g)
    else:
        name = specs.gpus[0].name if specs.gpus else "видеокарта не найдена"
        p.notes.append(("Драйвер видеокарты не настраивается",
                        f"{name}: настройка драйвера есть только для дискретных NVIDIA и AMD; "
                        "применяются системные твики и пресет игр для слабого ПК"))

    tweaks = ["power", "gamemode", "dvr", "hags", "mmcss", "mouse", "net"]
    if specs.is_laptop and specs.on_battery:
        tweaks.remove("power")
        p.notes.append(("Схема питания не меняется", "Ноутбук работает от батареи: Ultimate Performance "
                        "быстро её разрядит. Подключи зарядку и запусти оптимизацию снова"))
    if not (specs.os_build >= 19041 and g and supports_hags(g.name, g.vendor)):
        tweaks.remove("hags")
        why = (f"Windows сборки {specs.os_build} не поддерживает функцию" if specs.os_build < 19041
               else f"{g.name if g else 'видеокарта'} не поддерживает аппаратное планирование GPU")
        p.notes.append(("Аппаратное планирование GPU пропущено", why))
    p.tweak_ids = [t for t in tweaks if t in ids and t != "temp"]

    # советы, настройки не меняют
    if specs.ram_gb and specs.ram_gb < 16:
        p.notes.append(("Мало оперативной памяти", f"Установлено {specs.ram_gb:g} ГБ: для современных игр "
                        "нужно 16 ГБ и больше, закрывай браузер и лишние программы перед игрой"))
    if specs.ram_sticks == 1:
        p.notes.append(("Одна планка памяти", "Нет двухканального режима: вторая такая же планка "
                        "заметно поднимает FPS, особенно на встроенной графике и Ryzen"))
    if specs.ram_mhz and 0 < specs.ram_mhz < 3000 and specs.ram_mhz >= 1600:
        p.notes.append(("Память работает медленно", f"Частота памяти {specs.ram_mhz} МГц: проверь, включён ли "
                        "профиль XMP/EXPO в BIOS"))
    if specs.disks and specs.system_disk_kind == "hdd":
        p.notes.append(("Системный диск HDD", f"{specs.disks[0].model}: Windows и игры на HDD грузятся долго, "
                        "SSD заметно ускорит загрузку"))
    if specs.system_free_gb and specs.system_free_gb < 20:
        p.notes.append(("Мало места на системном диске", f"Свободно {specs.system_free_gb:g} ГБ: "
                        "освободи хотя бы 20 ГБ, иначе Windows и игры будут тормозить"))
    m = specs.monitor
    if m and m.hz >= 120:
        p.notes.append(("Проверь частоту монитора", f"Монитор поддерживает {m.hz} Гц: убедись в Параметрах "
                        "Windows > Дисплей > Расширенный дисплей, что выбрана максимальная частота"))
    return p
