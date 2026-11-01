"""Буст перед игрой: очистка памяти, закрытие фоновых программ, точный системный таймер."""
import ctypes
import subprocess
import winreg
from ctypes import wintypes

from . import ctx, registry as reg, sysmon

# exe -> название. Только то, что безопасно закрыть перед игрой и что само не перезапускается критично
BACKGROUND = {
    "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
    "opera.exe": "Opera", "browser.exe": "Яндекс Браузер", "brave.exe": "Brave",
    "OneDrive.exe": "OneDrive", "Teams.exe": "Microsoft Teams", "ms-teams.exe": "Microsoft Teams",
    "Spotify.exe": "Spotify", "EpicGamesLauncher.exe": "Epic Games Launcher", "EADesktop.exe": "EA App",
    "upc.exe": "Ubisoft Connect", "Battle.net.exe": "Battle.net", "GalaxyClient.exe": "GOG Galaxy",
    "AdobeCollabSync.exe": "Adobe Sync", "Creative Cloud.exe": "Adobe Creative Cloud",
    "Telegram.exe": "Telegram", "WhatsApp.exe": "WhatsApp", "Skype.exe": "Skype",
    "YandexDisk2.exe": "Яндекс Диск", "Dropbox.exe": "Dropbox", "qbittorrent.exe": "qBittorrent",
    "uTorrent.exe": "uTorrent", "PhoneExperienceHost.exe": "Связь с телефоном",
    "Widgets.exe": "Виджеты Windows", "Cortana.exe": "Cortana",
}

_K32 = ctypes.windll.kernel32
_PSAPI = ctypes.windll.psapi


def running_processes() -> dict:
    """exe (в нижнем регистре) -> (количество процессов, МБ памяти)."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace",
                         creationflags=sysmon.NO_WINDOW).stdout
    res = {}
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 5:
            continue
        mem = "".join(ch for ch in parts[4] if ch.isdigit())
        n, mb = res.get(parts[0].lower(), (0, 0.0))
        res[parts[0].lower()] = (n + 1, mb + (int(mem) / 1024 if mem else 0))
    return res


def background_running() -> list:
    """[(exe, название, МБ)] для запущенных фоновых программ из списка."""
    procs = running_processes()
    out = []
    for exe, title in BACKGROUND.items():
        if exe.lower() in procs:
            out.append((exe, title, procs[exe.lower()][1]))
    return sorted(out, key=lambda x: -x[2])


def close_programs(exes):
    for exe in exes:
        ctx.log(f"  закрываю {BACKGROUND.get(exe, exe)}")
        if not ctx.dry_run:
            subprocess.run(["taskkill", "/IM", exe, "/F", "/T"], capture_output=True,
                           creationflags=sysmon.NO_WINDOW)


class _LUID(ctypes.Structure):
    _fields_ = [("Low", wintypes.DWORD), ("High", wintypes.LONG)]


class _TP(ctypes.Structure):
    _fields_ = [("Count", wintypes.DWORD), ("Luid", _LUID), ("Attr", wintypes.DWORD)]


def _enable_privilege(name: str) -> bool:
    adv = ctypes.windll.advapi32
    tok = wintypes.HANDLE()
    if not adv.OpenProcessToken(_K32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):
        return False
    tp = _TP(1, _LUID(), 2)
    ok = adv.LookupPrivilegeValueW(None, name, ctypes.byref(tp.Luid)) and \
        adv.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
    _K32.CloseHandle(tok)
    return bool(ok) and _K32.GetLastError() == 0


def clean_ram() -> float:
    """Сжимает рабочие наборы всех процессов и чистит standby-список (как ISLC). Возвращает МБ освобождено."""
    before = sysmon.avail_mb()
    if ctx.dry_run:
        return 0.0
    pids = (wintypes.DWORD * 4096)()
    got = wintypes.DWORD()
    _PSAPI.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(got))
    for pid in pids[:got.value // 4]:
        h = _K32.OpenProcess(0x0400 | 0x0100, False, pid)  # QUERY_INFORMATION | SET_QUOTA
        if h:
            _PSAPI.EmptyWorkingSet(h)
            _K32.CloseHandle(h)
    if _enable_privilege("SeProfileSingleProcessPrivilege"):
        cmd = ctypes.c_int(4)  # MemoryPurgeStandbyList
        ctypes.windll.ntdll.NtSetSystemInformation(80, ctypes.byref(cmd), ctypes.sizeof(cmd))
    return max(0.0, sysmon.avail_mb() - before)


_KERNEL = r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel"


def set_timer(on: bool):
    """Таймер 0.5 мс, пока открыта программа. В Windows 11 запрос действует на все процессы
    только с ключом GlobalTimerResolutionRequests (пишется через журнал, откатывается)."""
    cur = ctypes.c_ulong()
    ctypes.windll.ntdll.NtSetTimerResolution(5000, bool(on), ctypes.byref(cur))
    if on:
        old = reg.read("HKLM", _KERNEL, "GlobalTimerResolutionRequests")
        if not old or old[0] != 1:
            reg.write("HKLM", _KERNEL, "GlobalTimerResolutionRequests", 1, winreg.REG_DWORD)
    return cur.value / 10000  # мс
