"""Системные твики Windows. Всё, кроме очистки TEMP, откатывается."""
import ctypes
import os
import re
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import ctx, journal, registry as reg

SZ = winreg.REG_SZ
ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"


def _run(*args) -> str:
    # консольные утилиты пишут в OEM-кодировке (cp866 на русской Windows)
    raw = subprocess.run(args, capture_output=True).stdout
    return raw.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors="replace")


_GUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"


def power_plan():
    if ctx.dry_run:
        ctx.log("  [dry-run] powercfg: Ultimate Performance")
        return
    cur = re.search(_GUID, _run("powercfg", "/getactivescheme"))
    # схема уже может существовать под другим GUID: ищем по имени, чтобы не плодить копии
    target = next((g for g, n in re.findall(_GUID + r"\s+\((.*?)\)", _run("powercfg", "/list"))
                   if re.search(r"ultimate|максимальная производительность", n, re.I)), None)
    if not target:
        m = re.search(_GUID, _run("powercfg", "-duplicatescheme", ULTIMATE))
        if not m:
            ctx.log("  схема Ultimate недоступна на этом ПК, оставлена текущая")
            return
        target = m.group(1)
        journal.record({"kind": "powerscheme_created", "guid": target})
    if cur:
        journal.record({"kind": "powerplan", "guid": cur.group(1)})
    _run("powercfg", "/setactive", target)


def game_mode():
    reg.write("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1)
    reg.write("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1)


def game_dvr_off():
    reg.write("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", 0)
    reg.write("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0)
    reg.write("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2)
    reg.write("HKCU", r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 1)
    reg.write("HKCU", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 1)


def hags():
    reg.write("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2)
    ctx.log("  планирование GPU: нужна перезагрузка ПК")


def multimedia():
    base = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
    reg.write("HKLM", base, "SystemResponsiveness", 0)
    games = base + r"\Tasks\Games"
    reg.write("HKLM", games, "GPU Priority", 8)
    reg.write("HKLM", games, "Priority", 6)
    reg.write("HKLM", games, "Scheduling Category", "High", SZ)
    reg.write("HKLM", games, "SFIO Priority", "High", SZ)


def mouse_accel_off():
    for n in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"):
        reg.write("HKCU", r"Control Panel\Mouse", n, "0", SZ)
    ctx.log("  мышь: применится после перезахода в Windows")


def network_latency():
    root = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    for guid in reg.subkeys("HKLM", root):
        p = root + "\\" + guid
        reg.write("HKLM", p, "TcpAckFrequency", 1)
        reg.write("HKLM", p, "TCPNoDelay", 1)


def clean_temp():
    n = 0
    for d in {os.environ.get("TEMP"), r"C:\Windows\Temp"}:
        if not d or not Path(d).exists():
            continue
        for f in Path(d).iterdir():
            try:
                if ctx.dry_run:
                    n += 1
                elif f.is_file():
                    f.unlink()
                    n += 1
            except OSError:
                pass
    ctx.log(f"  временных файлов {'найдено' if ctx.dry_run else 'удалено'}: {n}")


@dataclass
class Tweak:
    id: str
    title: str
    desc: str
    fn: Callable[[], None]
    revertible: bool = True


TWEAKS = [
    Tweak("power", "Схема питания: максимальная производительность", "Ultimate Performance вместо сбалансированной", power_plan),
    Tweak("gamemode", "Игровой режим Windows", "Приоритет ресурсов игре", game_mode),
    Tweak("dvr", "Отключить фоновую запись (Game DVR)", "Меньше просадок FPS, полноэкранный режим без оверлеев", game_dvr_off),
    Tweak("hags", "Аппаратное планирование GPU", "Меньше задержек на RTX/RX (нужна перезагрузка)", hags),
    Tweak("mmcss", "Приоритет игр в планировщике", "SystemResponsiveness=0, высокий приоритет задач Games", multimedia),
    Tweak("mouse", "Отключить ускорение мыши", "Точный прицел без «плавающей» чувствительности", mouse_accel_off),
    Tweak("net", "Снизить сетевую задержку", "Отключает задержку пакетов (Nagle) на всех адаптерах", network_latency),
    Tweak("temp", "Очистить временные файлы", "Не откатывается", clean_temp, revertible=False),
]
