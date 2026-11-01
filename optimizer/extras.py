"""«Фишки» для игр: свой шрифт интерфейса, цвет HUD, бинды и прочее.

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


@dataclass
class GameExtras:
    fonts_conf: str = ""                         # относительно папки игры
    autoexec: str = ""
    extras: list = field(default_factory=list)
    choices: dict = field(default_factory=dict)  # key -> {название: строки}


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
        ],
        choices={"hud": {name: [f'cl_hud_color "{v}"'] for name, v in CS2_HUD.items()}},
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
        ],
    ),
}


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
