"""«Фишки» для игр: свой шрифт интерфейса, цвет HUD, бинды, параметры запуска по движку.

Шрифт: в panorama/fonts/fonts.conf игры дописывается правило fontconfig, которое ставит выбранный
шрифт Windows первым для всего интерфейса (игра уже читает WINDOWSFONTDIR). Игровые файлы
(.vpk) не трогаются. Остальное пишется отдельным блоком в autoexec.cfg. Всё откатывается по журналу.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import ctx, journal

FONTS = {
    "Bahnschrift": "Bahnschrift",
    "Segoe UI Black": "Segoe UI Black",
    "Consolas (моно)": "Consolas",
    "Impact": "Impact",
    "Comic Sans": "Comic Sans MS",
    "Franklin Gothic": "Franklin Gothic Medium",
    "Ink Free (рукописный)": "Ink Free",
    "Segoe Print": "Segoe Print",
    "Gabriola": "Gabriola",
}
FONT_BEGIN, FONT_END = "<!-- >>> GameOptimizer font -->", "<!-- <<< GameOptimizer font -->"
# не начинаются с маркеров games.BEGIN/END, чтобы блоки не съедали друг друга
CFG_BEGIN, CFG_END = "// >>> GO-extras", "// <<< GO-extras"


@dataclass
class Extra:
    key: str
    title: str
    desc: str
    lines: list = field(default_factory=list)   # строки для autoexec
    launch: list = field(default_factory=list)  # параметры запуска Steam
    kind: str = ""                              # "dpi": флаг совместимости exe


@dataclass
class Choice:
    key: str
    title: str
    options: dict = field(default_factory=dict)  # название -> Extra (используются lines/launch)


@dataclass
class GameExtras:
    fonts_conf: str = ""                         # относительно папки игры
    autoexec: str = ""
    extras: list = field(default_factory=list)
    choices: list = field(default_factory=list)


def _opts(d: dict) -> dict:
    return {name: Extra(name, name, "", *v) for name, v in d.items()}


UNIVERSAL = [
    Extra("dpi", "Чёткая картинка при масштабе Windows",
          "При масштабе 125–150% старые игры растягиваются и мылят: отключаем", kind="dpi"),
]

ENGINE_EXTRAS = {
    "unity": GameExtras(
        extras=[Extra("d3d11", "Принудительно DirectX 11", "Если игра вылетает или фризит на DX12/Vulkan",
                      launch=["-force-d3d11"]),
                Extra("nolog", "Без файла логов", "Игра не пишет лог на диск во время игры", launch=["-nolog"])],
        choices=[Choice("winmode", "Режим окна", _opts({
            "Без рамки (быстрый Alt+Tab)": ([], ["-screen-fullscreen 0", "-popupwindow"]),
            "Эксклюзивный (меньше задержка)": ([], ["-window-mode exclusive"]),
        }))]),
    "unreal": GameExtras(
        extras=[Extra("allcores", "Все ядра процессора", "Движок использует все потоки CPU",
                      launch=["-USEALLAVAILABLECORES"]),
                Extra("nosplash", "Без заставки", "Пропуск заставки движка при запуске", launch=["-nosplash"])],
        choices=[Choice("api", "Графический API", _opts({
            "DirectX 11 (стабильнее)": ([], ["-dx11"]), "DirectX 12": ([], ["-dx12"]),
        }))]),
    "source2": GameExtras(extras=[Extra("novid", "Без вступительного ролика", "Сразу в меню", launch=["-novid"])]),
    "source": GameExtras(extras=[Extra("novid", "Без вступительного ролика", "Сразу в меню", launch=["-novid"]),
                                 Extra("console", "Консоль при запуске", "Консоль открыта сразу", launch=["-console"])]),
}


CS2_HUD = {"Белый": 1, "Голубой": 4, "Синий": 5, "Фиолетовый": 6, "Красный": 7, "Оранжевый": 8,
           "Жёлтый": 9, "Зелёный": 10, "Аква": 11, "Розовый": 12}

EXTRAS = {
    "730": GameExtras(
        fonts_conf=r"game\csgo\panorama\fonts\fonts.conf",
        autoexec=r"game\csgo\cfg\autoexec.cfg",
        extras=[
            Extra("viewmodel", "Оружие как у про", "Широкий обзор, оружие ниже и правее: видно больше экрана",
                  ['viewmodel_fov "68"', 'viewmodel_offset_x "2.5"', 'viewmodel_offset_y "0"',
                   'viewmodel_offset_z "-1.5"', 'viewmodel_presetpos "0"']),
            Extra("jumpbind", "Прыжок на колёсико", "Бинд прыжка на прокрутку вниз: легче распрыжка",
                  ['bind "mwheeldown" "+jump"']),
            Extra("telemetry", "FPS и пинг на экране", "Встроенная телеметрия CS2 вместо net_graph",
                  ['cl_hud_telemetry_frametime_show "2"', 'cl_hud_telemetry_ping_show "2"',
                   'cl_hud_telemetry_net_misdelivery_show "2"']),
            Extra("radar", "Радар как у про", "Видна вся карта, радар не крутится за камерой",
                  ['cl_radar_scale "0.4"', 'cl_hud_radar_scale "1.15"', 'cl_radar_always_centered "0"',
                   'cl_radar_rotate "1"']),
            Extra("decals", "Чистка крови на Shift", "При ходьбе стираются кровь и следы на стенах",
                  ['bind "shift" "+sprint; r_cleardecals"']),
            Extra("losefocus", "Тишина при Alt+Tab", "Звук игры выключается, когда окно свёрнуто",
                  ['snd_mute_losefocus "1"']),
            Extra("usebuy", "E не открывает закупку", "Закупка только на B, E только поднимает и открывает",
                  ['cl_use_opens_buy_menu "0"']),
            Extra("hints", "Без подсказок новичка", "Убирает всплывающие советы", ['gameinstructor_enable "0"']),
        ],
        choices=[Choice("hud", "Цвет HUD", _opts({name: ([f'cl_hud_color "{v}"'],) for name, v in CS2_HUD.items()}))],
    ),
    "570": GameExtras(
        fonts_conf=r"game\core\panorama\fonts\fonts.conf",
        autoexec=r"game\dota\cfg\autoexec.cfg",
        extras=[
            Extra("hpbars", "Деления на полосках здоровья", "Каждое деление = 250 HP: проще считать добивания",
                  ['dota_health_per_vertical_marker "250"']),
            Extra("fps", "FPS и пинг на экране", "Счётчик кадров и сеть в углу",
                  ['cl_showfps "1"', 'dota_hud_netgraph "1"']),
            Extra("minimap", "Крупные герои на миникарте", "Иконки героев на миникарте больше",
                  ['dota_minimap_hero_size "800"']),
            Extra("rmb", "Удержание ПКМ = повтор приказа", "Зажал правую кнопку: герой идёт за курсором",
                  ['dota_player_auto_repeat_right_mouse "1"']),
            Extra("range", "Радиус атаки и умений", "Показывает дальность при наведении на умение",
                  ['dota_disable_range_finder "0"']),
        ],
    ),
    "252490": GameExtras(  # Rust
        extras=[Extra("gc", "Меньше фризов от сборщика мусора", "Увеличенный буфер памяти Unity (нужно 16 ГБ ОЗУ)",
                      launch=["-gc.buffer 4096"])],
        choices=[Choice("winmode", "Режим окна", _opts({
            "Без рамки (быстрый Alt+Tab)": ([], ["-window-mode borderless"]),
            "Эксклюзивный (меньше задержка)": ([], ["-window-mode exclusive"]),
        }))],
    ),
}


def for_game(appid: str, eng, skip=()) -> GameExtras:
    """Собирает все фишки игры: свои + по движку + общие для любой игры.
    skip: параметры запуска, которые уже ставит профиль игры (не дублируем)."""
    own = EXTRAS.get(appid, GameExtras())
    base = ENGINE_EXTRAS.get(eng, GameExtras())
    keys = {e.key for e in own.extras} | {e.key for e in base.extras if e.launch and set(e.launch) <= set(skip)}
    ckeys = {c.key for c in own.choices}
    return GameExtras(fonts_conf=own.fonts_conf, autoexec=own.autoexec,
                      extras=own.extras + [e for e in base.extras if e.key not in keys] + UNIVERSAL,
                      choices=own.choices + [c for c in base.choices if c.key not in ckeys])


def all_launch(ex: GameExtras) -> list:
    out = [f for e in ex.extras for f in e.launch]
    for c in ex.choices:
        out += [f for o in c.options.values() for f in o.launch]
    return out


def font_block(family: str) -> str:
    return (f"\t{FONT_BEGIN}\n"
            "\t<match target=\"pattern\">\n"
            "\t\t<edit name=\"family\" mode=\"prepend\" binding=\"strong\">\n"
            f"\t\t\t<string>{family}</string>\n"
            "\t\t</edit>\n"
            "\t</match>\n"
            f"\t{FONT_END}\n")


def _strip(text: str, begin: str, end: str) -> str:
    return re.sub(r"[ \t]*" + re.escape(begin) + r".*?" + re.escape(end) + r"\r?\n?", "", text, flags=re.S)


def set_font(game_path: Path, ex: GameExtras, family):
    """family=None убирает свой шрифт (возвращает стандартный)."""
    conf = game_path / ex.fonts_conf
    if not conf.exists():
        ctx.log("  fonts.conf не найден: шрифт не поменять")
        return
    text = conf.read_text("utf-8", errors="replace")
    new = _strip(text, FONT_BEGIN, FONT_END)
    if family:
        i = new.rfind("</fontconfig>")
        new = new[:i] + font_block(family) + new[i:]
    if new == text:
        return
    if ctx.dry_run:
        ctx.log(f"  [dry-run] шрифт интерфейса: {family or 'стандартный'}")
        return
    journal.backup_file(conf)
    conf.write_text(new, "utf-8")
    ctx.log(f"  шрифт интерфейса: {family or 'стандартный'} (применится при следующем запуске игры)")


def current_font(game_path: Path, ex: GameExtras):
    conf = game_path / ex.fonts_conf
    if not conf.exists():
        return None
    m = re.search(re.escape(FONT_BEGIN) + r".*?<string>(.*?)</string>",
                  conf.read_text("utf-8", errors="replace"), re.S)
    return m.group(1) if m else None


def set_cfg(game_path: Path, ex: GameExtras, lines: list):
    """Перезаписывает блок «фишек» в autoexec (пустой список убирает блок)."""
    path = game_path / ex.autoexec
    old = path.read_text("utf-8", errors="replace") if path.exists() else ""
    new = _strip(old, CFG_BEGIN, CFG_END).rstrip()
    if lines:
        new = (new + "\n\n" if new else "") + CFG_BEGIN + "\n" + "\n".join(lines) + "\n" + CFG_END
    new = new + "\n" if new else ""
    if new == old:
        return
    if ctx.dry_run:
        ctx.log(f"  [dry-run] autoexec: {len(lines)} строк фишек")
        return
    journal.backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, "utf-8")
    ctx.log(f"  autoexec: фишек {len(lines)} строк")


def current_cfg(game_path: Path, ex: GameExtras) -> list:
    path = game_path / ex.autoexec
    if not path.exists():
        return []
    m = re.search(re.escape(CFG_BEGIN) + r"\n(.*?)" + re.escape(CFG_END),
                  path.read_text("utf-8", errors="replace"), re.S)
    return m.group(1).strip().splitlines() if m else []
