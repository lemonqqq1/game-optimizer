"""Определение видеокарты и настройка драйвера NVIDIA / AMD."""
import io
import json
import os
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import ctx, journal, registry as reg

NPI_URL = "https://github.com/Orbmu2k/nvidiaProfileInspector/releases/download/v3.0.2.1/nvidiaProfileInspector.zip"
DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


@dataclass
class Gpu:
    name: str
    vendor: str  # nvidia | amd | intel | other
    driver: str


@dataclass
class Setting:
    key: str
    title: str
    desc: str
    # NVIDIA: id настройки драйвера (DRS), значение, значение драйвера по умолчанию
    # AMD: (подключ относительно адаптера, имя, значение, тип реестра)
    id: int = 0
    value: object = None
    default: object = None
    reg: tuple = ()


def _vendor(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "ati " in n:
        return "amd"
    if "intel" in n:
        return "intel"
    return "other"


def detect() -> list:
    ps = ("Get-CimInstance Win32_VideoController | "
          "Select-Object Name,DriverVersion | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, errors="replace").stdout.strip()
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    gpus = [Gpu(d["Name"], _vendor(d["Name"]), d.get("DriverVersion") or "") for d in data]
    order = {"nvidia": 0, "amd": 1, "intel": 2, "other": 3}
    return sorted(gpus, key=lambda g: order[g.vendor])


# ---------- NVIDIA: глобальный профиль драйвера через NVIDIA Profile Inspector ----------
# ID и значения из NvApiDriverSettings.h (NVAPI SDK)
NVIDIA = [
    Setting("power", "Режим управления питанием", "Предпочтителен режим максимальной производительности",
            0x1057EB71, 1, 5),
    Setting("lowlat", "Режим низкой задержки", "Вкл: CPU готовит не больше 1 кадра вперёд, меньше инпут-лаг",
            0x007BA09E, 1, 0),
    Setting("vsync", "Вертикальная синхронизация", "Выкл: без ограничения FPS частотой монитора",
            0x00A879CF, 0x08416747, 0x60925292),
    Setting("texq", "Фильтрация текстур: качество", "Высокая производительность",
            0x00CE2691, 20, 0),
    Setting("lodbias", "Отрицательное отклонение УД", "Привязка: убирает «рябь» текстур при фильтрации",
            0x0019BB68, 1, 0),
    Setting("thread", "Потоковая оптимизация", "Вкл: драйвер использует несколько ядер CPU",
            0x20C1221E, 1, 0),
    Setting("fxaa", "Сглаживание FXAA", "Выкл: без мыла на картинке и потери FPS",
            0x1074C972, 0, 0),
    Setting("tbuf", "Тройная буферизация", "Выкл: меньше задержка (актуально только с V-Sync)",
            0x20FDD1F9, 0, 0),
    Setting("fpslimit", "Макс. частота кадров", "Без ограничения",
            0x10835002, 0, 0),
]

_NIP_HEAD = """<?xml version="1.0" encoding="utf-16"?>
<ArrayOfProfile>
  <Profile>
    <ProfileName>Base Profile</ProfileName>
    <Executeables />
    <Settings>
"""
_NIP_ITEM = """      <ProfileSetting>
        <SettingNameInfo>{name}</SettingNameInfo>
        <SettingID>{id}</SettingID>
        <SettingValue>{value}</SettingValue>
        <ValueType>Dword</ValueType>
      </ProfileSetting>
"""
_NIP_TAIL = """    </Settings>
  </Profile>
</ArrayOfProfile>
"""


def build_nip(pairs) -> str:
    """pairs: [(Setting, значение)] -> текст .nip для Profile Inspector."""
    items = "".join(_NIP_ITEM.format(name=s.title, id=s.id, value=v) for s, v in pairs)
    return _NIP_HEAD + items + _NIP_TAIL


def _npi_exe() -> Path:
    d = journal.state_dir() / "npi"
    exe = d / "nvidiaProfileInspector.exe"
    if not exe.exists():
        ctx.log("  скачиваю NVIDIA Profile Inspector (официальный релиз с GitHub)...")
        with urllib.request.urlopen(NPI_URL, timeout=60) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(d)
    return exe


def _import_nip(text: str):
    nip = journal.state_dir() / "profile.nip"
    nip.write_text(text, encoding="utf-16")
    subprocess.run([str(_npi_exe()), "-silentImport", str(nip)], timeout=60)


def nvidia_apply(keys=None):
    chosen = [s for s in NVIDIA if keys is None or s.key in keys]
    if not chosen:
        return
    if ctx.dry_run:
        for s in chosen:
            ctx.log(f"  [dry-run] NVIDIA: {s.title} -> {s.desc}")
        return
    try:
        _import_nip(build_nip([(s, s.value) for s in chosen]))
        journal.record({"kind": "nvidia", "keys": [s.key for s in chosen]})
        for s in chosen:
            ctx.log(f"  NVIDIA: {s.title}: {s.desc}")
    except Exception as e:
        ctx.log(f"  NVIDIA: не удалось применить ({e}). Можно вручную: Панель управления NVIDIA > "
                "Управление параметрами 3D")


def nvidia_revert(keys=None):
    chosen = [s for s in NVIDIA if keys is None or s.key in keys]
    _import_nip(build_nip([(s, s.default) for s in chosen]))


def open_nvidia_panel():
    try:
        os.startfile(r"shell:AppsFolder\NVIDIACorp.NVIDIAControlPanel_56jybvy8sckqj!NVIDIACorp.NVIDIAControlPanel")
    except OSError:
        ctx.log("Панель NVIDIA не найдена (установи её из Microsoft Store)")


# ---------- AMD: ключи драйвера в реестре (как их пишет Adrenalin) ----------
# Строковые значения UMD хранятся как REG_BINARY: ASCII-символы + 00
BIN, DW = reg.winreg.REG_BINARY, reg.winreg.REG_DWORD


def _s(v: str) -> bytes:
    return b"".join(c.encode() + b"\x00" for c in v)


AMD = [
    Setting("vsync", "Ждать вертикального обновления", "Всегда выкл", reg=("UMD", "VSyncControl", _s("0"), BIN)),
    Setting("flipq", "Очередь кадров (Flip Queue)", "1 кадр: меньше инпут-лаг", reg=("UMD", "FlipQueueSize", _s("1"), BIN)),
    Setting("tfq", "Качество фильтрации текстур", "Производительность", reg=("UMD", "TFQ", _s("2"), BIN)),
    Setting("tessmode", "Режим тесселяции", "Переопределить настройки приложения",
            reg=("UMD", "Tessellation_OPTION", _s("2"), BIN)),
    Setting("tess", "Уровень тесселяции", "Выкл (1x)", reg=("UMD", "Tessellation", _s("1"), BIN)),
    Setting("surface", "Оптимизация формата поверхности", "Вкл", reg=("UMD", "SurfaceFormatReplacements", _s("1"), BIN)),
    Setting("shader", "Кэш шейдеров", "Оптимизировано AMD", reg=("UMD", "ShaderCache", _s("2"), BIN)),
    Setting("ulps", "Энергосбережение ULPS", "Выкл: GPU не засыпает, нет фризов при выходе из простоя",
            reg=("", "EnableUlps", 0, DW)),
]


def amd_adapters() -> list:
    out = []
    for sub in reg.subkeys("HKLM", DISPLAY_CLASS):
        if not sub.isdigit():
            continue
        desc = reg.read("HKLM", DISPLAY_CLASS + "\\" + sub, "DriverDesc")
        if desc and _vendor(str(desc[0])) == "amd":
            out.append(DISPLAY_CLASS + "\\" + sub)
    return out


def amd_apply(keys=None):
    chosen = [s for s in AMD if keys is None or s.key in keys]
    adapters = amd_adapters()
    if not adapters:
        ctx.log("  AMD: адаптер в реестре не найден")
        return
    for path in adapters:
        for s in chosen:
            sub, name, value, typ = s.reg
            reg.write("HKLM", path + ("\\" + sub if sub else ""), name, value, typ)
            ctx.log(f"  AMD: {s.title}: {s.desc}")
    ctx.log("  AMD: перезагрузи ПК, чтобы драйвер подхватил настройки")


def open_amd_panel():
    p = Path(r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe")
    if p.exists():
        os.startfile(p)
    else:
        ctx.log("AMD Software: Adrenalin Edition не найден")


def apply_for(gpu: Gpu, keys=None):
    if gpu.vendor == "nvidia":
        nvidia_apply(keys)
    elif gpu.vendor == "amd":
        amd_apply(keys)
    else:
        ctx.log(f"  {gpu.name}: настройка драйвера не поддерживается, применяются только системные твики")
