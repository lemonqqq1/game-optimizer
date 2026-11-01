"""Оптимизация игр Steam: общие твики exe + профили конкретных игр.

Чтобы добавить игру, допиши Profile в PROFILES (ключ: appid из URL магазина Steam).
"""
import re
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from . import ctx, journal, registry as reg, steam

_EXE_SKIP = ("unins", "crash", "redist", "setup", "launcher", "helper", "vc_", "dxsetup", "easyanticheat", "battleye",
             "install", "busybox", "quickedit", "editor", "tool", "config", "bugreport", "updater", "uplay", "ubisoft", "unity", "dotnet", "vcredist")
BEGIN, END = "// >>> GameOptimizer", "// <<< GameOptimizer"


@dataclass
class Profile:
    launch: list = field(default_factory=list)        # параметры запуска Steam
    exe: list = field(default_factory=list)           # пути exe относительно папки игры
    autoexec: str = ""                                # cfg относительно папки игры
    autoexec_lines: list = field(default_factory=list)
    kv_files: list = field(default_factory=list)      # (абсолютный путь или шаблон, {ключ: значение})


PROFILES = {
    "730": Profile(  # Counter-Strike 2
        launch=["-novid", "-high", "+fps_max 0"],
        exe=[r"game\bin\win64\cs2.exe"],
        autoexec=r"game\csgo\cfg\autoexec.cfg",
        autoexec_lines=['fps_max "0"', 'fps_max_ui "120"', 'cl_autohelp "0"'],
        kv_files=[("userdata:730/local/cfg/cs2_video.txt",
                   {"setting.mat_vsync": "0", "setting.msaa_samples": "0",
                    "setting.r_csgo_cmaa_enable": "0", "setting.r_texturefilteringquality": "0"})],
    ),
    "570": Profile(  # Dota 2
        launch=["-novid", "-high"],
        exe=[r"game\bin\win64\dota2.exe"],
        autoexec=r"game\dota\cfg\autoexec.cfg",
        autoexec_lines=['fps_max "0"'],
    ),
    "1172470": Profile(  # Apex Legends
        launch=["-novid", "-high", "+fps_max unlimited"],
        exe=["r5apex_dx12.exe", "r5apex.exe"],
        kv_files=[(str(Path.home() / "Saved Games/Respawn/Apex/local/videoconfig.txt"),
                   {"setting.mat_vsync_mode": "0", "setting.volumetric_lighting": "0",
                    "setting.csm_enabled": "0"})],
    ),
}


def find_exe(game: steam.Game, profile) -> Path | None:
    if profile:
        for rel in profile.exe:
            p = game.path / rel
            if p.exists():
                return p
    # ищем exe на минимальной глубине (до 3 уровней), берём самый большой
    for pattern in ("*.exe", "*/*.exe", "*/*/*.exe"):
        cands = [p for p in game.path.glob(pattern)
                 if not any(s in p.name.lower() for s in _EXE_SKIP)]
        if cands:
            return max(cands, key=lambda p: p.stat().st_size)
    return None


def patch_kv(path: Path, updates: dict) -> list:
    """Меняет значения только у уже существующих ключей `"ключ" "значение"`."""
    if not path.exists():
        return []
    text = path.read_text("utf-8", errors="replace")
    changed = []
    for k, v in updates.items():
        pat = re.compile(r'("' + re.escape(k) + r'"\s+")([^"]*)(")')
        m = pat.search(text)
        if m and m.group(2) != v:
            text = pat.sub(lambda m_: m_.group(1) + v + m_.group(3), text, count=1)
            changed.append(k)
    if changed and not ctx.dry_run:
        journal.backup_file(path)
        path.write_text(text, "utf-8")
    return changed


def write_block(path: Path, lines: list):
    old = path.read_text("utf-8", errors="replace") if path.exists() else ""
    old = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\r?\n?", "", old, flags=re.S)
    new = old.rstrip() + ("\n\n" if old.strip() else "") + BEGIN + "\n" + "\n".join(lines) + "\n" + END + "\n"
    if ctx.dry_run:
        ctx.log(f"  [dry-run] {path}: {len(lines)} строк")
        return
    journal.backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, "utf-8")


def _ifeo(exe: Path) -> str:
    return (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
            + "\\" + exe.name + "\\PerfOptions")


def is_optimized(game: steam.Game) -> bool:
    exe = find_exe(game, PROFILES.get(game.appid))
    cur = reg.read("HKLM", _ifeo(exe), "CpuPriorityClass") if exe else None
    return bool(cur and cur[0] == 3)


def exe_tweaks(exe: Path):
    """Для любой игры: дискретная видеокарта, высокий приоритет, без оптимизаций полного экрана."""
    reg.write("HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences", str(exe),
              "GpuPreference=2;", winreg.REG_SZ)
    layers = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    old = reg.read("HKCU", layers, str(exe))
    cur = old[0] if old else ""
    if "DISABLEDXMAXIMIZEDWINDOWEDMODE" not in cur.split():
        reg.write("HKCU", layers, str(exe), (cur or "~") + " DISABLEDXMAXIMIZEDWINDOWEDMODE", winreg.REG_SZ)
    reg.write("HKLM", _ifeo(exe), "CpuPriorityClass", 3)


def optimize(game: steam.Game, root: Path):
    prof = PROFILES.get(game.appid)
    ctx.log(f"{game.name}:")
    exe = find_exe(game, prof)
    if exe:
        exe_tweaks(exe)
        ctx.log(f"  exe: {exe.name} (GPU high perf, приоритет High, без FSO)")
    else:
        ctx.log("  exe не найден, пропускаю системные настройки exe")
    if not prof:
        ctx.log("  отдельного профиля нет: применены общие настройки")
        return
    if prof.autoexec_lines:
        write_block(game.path / prof.autoexec, prof.autoexec_lines)
        ctx.log(f"  autoexec: {Path(prof.autoexec).name}")
    for spec, updates in prof.kv_files:
        if spec.startswith("userdata:"):
            files = list((root / "userdata").glob("*/" + spec[len("userdata:"):]))
        else:
            files = [Path(spec)]
        for f in files:
            keys = patch_kv(f, updates)
            if keys:
                ctx.log(f"  {f.name}: {', '.join(keys)}")
    if prof.launch:
        try:
            steam.set_launch_options(root, game.appid, prof.launch)
        except steam.SteamRunning as e:
            ctx.log(f"  ! {e}")
