"""Полный скан железа ПК: CPU, RAM, GPU, мониторы, диски, Windows. Основа для рекомендаций."""
import ctypes
import json
import re
import subprocess
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field

from .gpu import DISPLAY_CLASS, _vendor

# Один вызов PowerShell возвращает один JSON-объект со всем железом
_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$sd = ($env:SystemDrive + '').TrimEnd(':')
$free = (Get-PSDrive -Name $sd).Free
[pscustomobject]@{
  cpu = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
  ram = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity, Speed, ConfiguredClockSpeed)
  gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM)
  os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, BuildNumber
  chassis = @((Get-CimInstance Win32_SystemEnclosure).ChassisTypes)
  battery = @(Get-CimInstance Win32_Battery | Select-Object Name)
  disks = @(Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, BusType, Size)
  parts = @(Get-Partition | Where-Object DriveLetter | Select-Object DriveLetter, DiskNumber)
  sysdrive = $sd
  sysfree = $free
} | ConvertTo-Json -Compress -Depth 4
"""

GB = 1024 ** 3
# типы корпуса, означающие ноутбук: Portable, Laptop, Notebook, Hand Held, Sub Notebook, Tablet, Convertible, Detachable
LAPTOP_CHASSIS = {8, 9, 10, 11, 14, 30, 31, 32}


@dataclass
class GpuInfo:
    name: str
    vendor: str  # nvidia | amd | intel | other
    driver: str
    vram_gb: float


@dataclass
class Monitor:
    width: int
    height: int
    hz: int
    primary: bool


@dataclass
class Disk:
    model: str
    kind: str  # nvme | ssd | hdd | unknown
    size_gb: float


def is_discrete(g: GpuInfo) -> bool:
    """Дискретная видеокарта: NVIDIA/AMD, кроме встроенной графики AMD (Radeon Graphics, Vega N Graphics)."""
    if g.vendor == "nvidia":
        return True
    if g.vendor == "amd":
        return not re.search(r"radeon(\(tm\))?\s+(graphics|vega\s*\d*\s*graphics|\d{3}m)\s*$", g.name.lower())
    return False


def _gen_points(g: GpuInfo) -> int:
    """Поколение видеокарты, 0..20 баллов."""
    n = g.name.lower()
    m = re.search(r"\b(?:rtx|gtx)\s*(\d{3,4})", n) or re.search(r"\brx\s*(\d{3,4})", n)
    if not m:
        return 3
    num = int(m.group(1))
    if g.vendor == "nvidia":
        gen = num // 1000 if num >= 1000 else num // 100  # 5090 -> 5, 1060 -> 1, 960 -> 9 (GTX 9xx)
        if "rtx" in n:
            return {5: 20, 4: 20, 3: 17, 2: 13}.get(gen, 10)
        return 13 if num // 100 == 16 else 9 if num >= 1000 else 5
    if g.vendor == "amd":
        if num >= 9000:
            return 20
        gen = num // 1000
        return {7: 20, 6: 17, 5: 13}.get(gen, 8 if num >= 400 else 3)
    return 3


@dataclass
class Specs:
    cpu_name: str = ""
    cores: int = 0
    threads: int = 0
    ram_gb: float = 0.0
    ram_mhz: int = 0
    ram_sticks: int = 0
    gpus: list = field(default_factory=list)
    monitors: list = field(default_factory=list)
    disks: list = field(default_factory=list)
    system_free_gb: float = 0.0
    game_drive_kinds: dict = field(default_factory=dict)  # буква диска -> тип (может быть пустым)
    os_name: str = ""
    os_build: int = 0
    is_laptop: bool = False
    on_battery: bool = False

    @property
    def gpu(self):
        """Лучшая дискретная видеокарта (nvidia/amd с максимумом VRAM) или None."""
        cand = [g for g in self.gpus if is_discrete(g)]
        return max(cand, key=lambda g: (g.vram_gb, g.vendor == "nvidia"), default=None)

    @property
    def monitor(self):
        return next((m for m in self.monitors if m.primary), self.monitors[0] if self.monitors else None)

    @property
    def system_disk_kind(self) -> str:
        """Тип системного диска (parse ставит его первым в списке)."""
        return self.disks[0].kind if self.disks else "unknown"

    @property
    def score(self) -> int:
        """Оценка 0..100: видеокарта 50 (VRAM до 30: 2.5 балла за ГБ, максимум на 12 ГБ; поколение до 20),
        процессор 25 (потоки, максимум на 16), RAM 15 (максимум на 32 ГБ),
        системный диск 10 (nvme 10, ssd 7, hdd 2, неизвестно 4). Нет дискретной GPU: не больше 39."""
        g = self.gpu
        s = 0.0
        if g:
            s += min(g.vram_gb, 12) / 12 * 30 + _gen_points(g)
        s += min(self.threads, 16) / 16 * 25
        s += min(self.ram_gb, 32) / 32 * 15
        s += {"nvme": 10, "ssd": 7, "hdd": 2}.get(self.system_disk_kind, 4)
        s = int(round(s))
        return max(0, min(s if g else min(s, 39), 100))

    @property
    def tier(self) -> str:
        """low: score < 40 (или нет дискретной GPU), mid: < 70, иначе high."""
        if not self.gpu:
            return "low"
        s = self.score
        return "low" if s < 40 else "mid" if s < 70 else "high"

    def summary(self) -> list:
        """Список (метка, значение) для вывода пользователю."""
        out = [("Процессор", f"{self.cpu_name or 'не определён'} ({self.cores} ядер / {self.threads} потоков)")]
        mhz = f", {self.ram_mhz} МГц" if self.ram_mhz else ""
        out.append(("Память", f"{self.ram_gb:g} ГБ ({self.ram_sticks} план.){mhz}"))
        g = self.gpu or (self.gpus[0] if self.gpus else None)
        if g:
            vram = f", {g.vram_gb:g} ГБ" if g.vram_gb else ""
            out.append(("Видеокарта", f"{g.name}{vram}" + ("" if is_discrete(g) else " (встроенная)")))
        else:
            out.append(("Видеокарта", "не определена"))
        m = self.monitor
        out.append(("Монитор", f"{m.width}x{m.height}, {m.hz} Гц" if m else "не определён"))
        out.append(("Диски", "; ".join(f"{d.model} ({d.kind.upper()}, {d.size_gb:g} ГБ)" for d in self.disks)
                    or "не определены"))
        out.append(("Windows", f"{self.os_name or 'не определена'} (сборка {self.os_build})"))
        kind = "ноутбук" if self.is_laptop else "настольный ПК"
        if self.is_laptop:
            kind += ", от батареи" if self.on_battery else ", от сети"
        out.append(("Тип ПК", kind))
        return out


# ---------- разбор ----------
def _list(v) -> list:
    """PowerShell отдаёт dict вместо списка, если элемент один, и None, если пусто."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _num(v, default=0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _disk_kind(d: dict) -> str:
    bus = str(d.get("BusType") or "").lower()
    media = str(d.get("MediaType") or "").lower()
    if bus == "nvme" or bus == "17":
        return "nvme"
    if media in ("ssd", "4"):
        return "ssd"
    if media in ("hdd", "3"):
        return "hdd"
    return "unknown"


def parse(raw: dict, monitors: list, vram: dict, on_battery: bool) -> Specs:
    """raw: JSON из PowerShell, monitors: [Monitor], vram: {DriverDesc: ГБ из реестра}, on_battery: от батареи."""
    raw = raw if isinstance(raw, dict) else {}
    cpus = [c for c in _list(raw.get("cpu")) if isinstance(c, dict)]
    cpu = cpus[0] if cpus else {}
    sticks = [r for r in _list(raw.get("ram")) if isinstance(r, dict)]
    speeds = [int(_num(r.get("ConfiguredClockSpeed") or r.get("Speed"))) for r in sticks]
    gpus = []
    for g in _list(raw.get("gpu")):
        if not isinstance(g, dict) or not g.get("Name"):
            continue
        name = str(g["Name"])
        v = vram.get(name) or _num(g.get("AdapterRAM")) / GB  # AdapterRAM упирается в 4 ГБ
        gpus.append(GpuInfo(name, _vendor(name), str(g.get("DriverVersion") or ""), round(float(v), 1)))
    order = {"nvidia": 0, "amd": 1, "intel": 2, "other": 3}
    gpus.sort(key=lambda g: order[g.vendor])
    dlist = [d for d in _list(raw.get("disks")) if isinstance(d, dict)]
    kinds = {str(d.get("DeviceId")): _disk_kind(d) for d in dlist}
    letters = {str(p.get("DriveLetter")).upper(): kinds.get(str(p.get("DiskNumber")), "unknown")
               for p in _list(raw.get("parts")) if isinstance(p, dict) and p.get("DriveLetter")}
    sysletter = str(raw.get("sysdrive") or "C").upper()[:1]
    # системный диск ставим первым: по нему считается score и советы
    sysid = next((str(p.get("DiskNumber")) for p in _list(raw.get("parts"))
                  if isinstance(p, dict) and str(p.get("DriveLetter")).upper() == sysletter), None)
    dlist.sort(key=lambda d: str(d.get("DeviceId")) != sysid)
    disks = [Disk(str(d.get("FriendlyName") or "диск"), _disk_kind(d), round(_num(d.get("Size")) / 1e9))
             for d in dlist]
    chassis = {int(_num(c, -1)) for c in _list(raw.get("chassis"))}
    os_ = raw.get("os") if isinstance(raw.get("os"), dict) else {}
    laptop = bool(chassis & LAPTOP_CHASSIS) if chassis - {-1} else bool(_list(raw.get("battery")))
    return Specs(
        cpu_name=re.sub(r"\s+", " ", str(cpu.get("Name") or "")).strip(),
        cores=int(_num(cpu.get("NumberOfCores"))), threads=int(_num(cpu.get("NumberOfLogicalProcessors"))),
        ram_gb=round(sum(_num(r.get("Capacity")) for r in sticks) / GB), ram_mhz=max(speeds, default=0),
        ram_sticks=len(sticks), gpus=gpus, monitors=list(monitors or []), disks=disks,
        system_free_gb=round(_num(raw.get("sysfree")) / GB, 1), game_drive_kinds=letters,
        os_name=str(os_.get("Caption") or "").replace("Майкрософт ", "").replace("Microsoft ", "").strip(),
        os_build=int(_num(os_.get("BuildNumber"))), is_laptop=laptop, on_battery=bool(on_battery and laptop))


# ---------- сбор ----------
def _powershell() -> dict:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", _PS], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=40, creationflags=0x08000000).stdout.strip()
    data = json.loads(out)
    return data if isinstance(data, dict) else {}


def read_vram() -> dict:
    """Реальный объём VRAM из реестра (qwMemorySize), {DriverDesc: ГБ}. AdapterRAM в WMI режется до 4 ГБ."""
    res = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as base:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(base, sub) as k:
                        desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        size = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                except OSError:
                    continue
                if isinstance(size, (bytes, bytearray)):
                    size = int.from_bytes(size[:8], "little")
                if size:
                    res[str(desc)] = round(size / GB, 1)
    except OSError:
        pass
    return res


class _DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32), ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD), ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


class _DEVMODE(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD)]


def read_monitors() -> list:
    """Активные мониторы: разрешение и текущая частота через user32."""
    u32 = ctypes.windll.user32
    out, i = [], 0
    while True:
        dev = _DISPLAY_DEVICE()
        dev.cb = ctypes.sizeof(dev)
        if not u32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        i += 1
        if not dev.StateFlags & 0x1:  # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
            continue
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(dm)
        if u32.EnumDisplaySettingsW(dev.DeviceName, -1, ctypes.byref(dm)):  # ENUM_CURRENT_SETTINGS
            out.append(Monitor(int(dm.dmPelsWidth), int(dm.dmPelsHeight), int(dm.dmDisplayFrequency),
                               bool(dev.StateFlags & 0x4)))  # DISPLAY_DEVICE_PRIMARY_DEVICE
    return out


class _POWER(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def read_on_battery() -> bool:
    st = _POWER()
    return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st))) and st.ACLineStatus == 0


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def scan() -> Specs:
    """Полный скан железа. Никогда не бросает исключений: при сбое поля остаются пустыми."""
    try:
        raw = _safe(_powershell, {})
        return parse(raw, _safe(read_monitors, []), _safe(read_vram, {}), _safe(read_on_battery, False))
    except Exception:
        return Specs()
