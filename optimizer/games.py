"""Оптимизация игр (Steam и Epic): общие твики exe + профили конкретных игр по уровням low/mid/high.

Чтобы добавить игру, допиши Profile в PROFILES (ключ: appid Steam или строковый id вида "epic:Fortnite").
Префиксы путей в kv_files/video: "userdata:" (Steam userdata), "local:" (%LOCALAPPDATA%),
"docs:" (Документы), "saved:" (Saved Games), "game:" (папка игры); иначе абсолютный путь. В относительной части допустимы маски.
"""
import codecs
import os
import re
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from . import ctx, journal, launchers, registry as reg, steam

_EXE_SKIP = ("unins", "crash", "redist", "setup", "launcher", "helper", "vc_", "dxsetup", "easyanticheat", "battleye",
             "install", "busybox", "quickedit", "editor", "tool", "config", "bugreport", "updater", "uplay", "ubisoft", "unity", "dotnet", "vcredist")
BEGIN, END = "// >>> GameOptimizer", "// <<< GameOptimizer"
TIERS = ("low", "mid", "high")


@dataclass
class Profile:
    title: str = ""                                   # название игры для списка поддерживаемых
    launch: list = field(default_factory=list)        # параметры запуска Steam
    exe: list = field(default_factory=list)           # пути exe относительно папки игры
    autoexec: str = ""                                # cfg относительно папки игры
    autoexec_lines: list = field(default_factory=list)
    kv_files: list = field(default_factory=list)      # (путь или шаблон, {ключ: значение}) для любого уровня
    video: dict = field(default_factory=dict)         # уровень -> [(путь/шаблон, {ключ: значение})]
    no_exe_tweaks: bool = False                       # античит: не трогаем exe и реестр, только конфиги


def _tiers(*updates) -> dict:
    """Три набора ключей (low, mid, high) в одном файле -> словарь video."""
    return {t: list(u) for t, u in zip(TIERS, updates)}


_CS2 = "userdata:730/local/cfg/cs2_video.txt"
_APEX = "saved:Respawn/Apex/local/videoconfig.txt"
_PUBG = r"local:TslGame\Saved\Config\WindowsNoEditor\GameUserSettings.ini"
_FN = r"local:FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini"
_VAL = r"local:VALORANT\Saved\Config\*\Windows\GameUserSettings.ini"


def _ue(spec: str, tex, shadow, effects, view, aa) -> dict:
    """Unreal Engine: sg.* (0 = минимум); посты и листва всегда на минимуме, V-Sync выключен."""
    return _tiers(*[[(spec, {(None, "bUseVSync"): "False", (None, "sg.TextureQuality"): str(tex[i]),
                             (None, "sg.ShadowQuality"): str(shadow[i]), (None, "sg.EffectsQuality"): str(effects[i]),
                             (None, "sg.PostProcessQuality"): "0", (None, "sg.FoliageQuality"): "0",
                             (None, "sg.ViewDistanceQuality"): str(view[i]),
                             (None, "sg.AntiAliasingQuality"): str(aa[i])})] for i in range(3)])


PROFILES = {
    "730": Profile(  # Counter-Strike 2
        title="Counter-Strike 2",
        launch=["-novid", "-high", "+fps_max 0", "+exec autoexec"],
        exe=[r"game\bin\win64\cs2.exe"],
        autoexec=r"game\csgo\cfg\autoexec.cfg",
        autoexec_lines=['fps_max "0"', 'fps_max_ui "120"', 'cl_autohelp "0"'],
        kv_files=[(_CS2, {"setting.mat_vsync": "0", "setting.msaa_samples": "0", "setting.r_csgo_cmaa_enable": "0",
                          "setting.videocfg_fsr_detail": "0", "setting.videocfg_ao_detail": "0",
                          "setting.videocfg_particle_detail": "0", "setting.videocfg_dynamic_shadows": "0"})],
        video=_tiers(
            [(_CS2, {"setting.r_texturefilteringquality": "0", "setting.videocfg_shadow_quality": "0",
                     "setting.shaderquality": "0"})],
            [(_CS2, {"setting.r_texturefilteringquality": "1", "setting.videocfg_shadow_quality": "1",
                     "setting.shaderquality": "0"})],
            [(_CS2, {"setting.r_texturefilteringquality": "3", "setting.videocfg_shadow_quality": "1",
                     "setting.shaderquality": "1"})]),
    ),
    "570": Profile(  # Dota 2
        title="Dota 2",
        launch=["-novid", "-high"],
        exe=[r"game\bin\win64\dota2.exe"],
        autoexec=r"game\dota\cfg\autoexec.cfg",
        autoexec_lines=['fps_max "0"'],
        kv_files=[(r"game:game\dota\cfg\video.txt", {"setting.mat_vsync": "0", "setting.mat_triplebuffered": "0"})],
    ),
    "1172470": Profile(  # Apex Legends
        title="Apex Legends",
        launch=["-novid", "-high", "+fps_max unlimited"],
        exe=["r5apex_dx12.exe", "r5apex.exe"],
        kv_files=[(_APEX, {"setting.mat_vsync_mode": "0", "setting.volumetric_lighting": "0",
                           "setting.csm_enabled": "0", "setting.mat_antialias_mode": "0"})],
        video=_tiers([(_APEX, {"setting.mat_forceaniso": "0"})], [(_APEX, {"setting.mat_forceaniso": "4"})],
                     [(_APEX, {"setting.mat_forceaniso": "8"})]),
    ),
    "578080": Profile(  # PUBG: Battlegrounds
        title="PUBG: Battlegrounds",
        launch=["-high"],
        exe=[r"TslGame\Binaries\Win64\TslGame.exe"],
        video=_ue(_PUBG, (0, 1, 2), (0, 0, 1), (0, 1, 1), (1, 2, 3), (0, 1, 2)),
    ),
    "252490": Profile(title="Rust", launch=["-high"], exe=["RustClient.exe"]),  # остальные флаги в extras.py
    "epic:Fortnite": Profile(
        title="Fortnite",
        exe=[r"FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe"],
        video=_ue(_FN, (0, 1, 2), (0, 0, 1), (0, 1, 1), (1, 2, 3), (0, 1, 2)),
    ),
    "riot:valorant": Profile(  # Vanguard: только конфиг, без exe и реестра
        title="VALORANT",
        no_exe_tweaks=True,
        video=_tiers(*[[(_VAL, {(None, "bUseVSync"): "False"})] for _ in TIERS]),
    ),
}


def supported() -> list:
    """Игры с профилем: [(id, название)] для интерфейса."""
    return [(k, p.title or k) for k, p in PROFILES.items()]


def _documents() -> Path:
    cur = reg.read("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders", "Personal")
    if cur and cur[0]:
        return Path(os.path.expandvars(cur[0]))
    return Path.home() / "Documents"


def resolve_spec(spec: str, root=None, game_path=None) -> list:
    """Путь или шаблон с префиксом -> список существующих файлов (маски раскрываются)."""
    bases = {"local:": lambda: Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"),
             "docs:": _documents, "saved:": lambda: Path.home() / "Saved Games"}
    if spec.startswith("game:"):
        return [p for p in Path(game_path).glob(spec[5:].replace("\\", "/")) if p.is_file()] if game_path else []
    if spec.startswith("userdata:"):
        return list((Path(root) / "userdata").glob("*/" + spec[len("userdata:"):])) if root else []
    for pre, base in bases.items():
        if spec.startswith(pre):
            rel = spec[len(pre):].replace("\\", "/").lstrip("/")
            return [p for p in base().glob(rel) if p.is_file()]
    return [Path(spec)]


def find_exe(game: steam.Game, profile) -> Path | None:
    if profile:
        for rel in profile.exe:
            p = game.path / rel
            if p.exists():
                return p
    rel = launchers.EXECUTABLES.get(game.appid)   # LaunchExecutable из манифеста Epic
    if rel and (game.path / rel).is_file():
        return game.path / rel
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


_SECTION = re.compile(r"^\s*\[([^\]]*)\]")
_KEYVAL = re.compile(r"^(\s*)([^=;#\[\s][^=]*?)(\s*=\s*)(.*?)(\r?\n?)$", re.S)


def _decode_ini(raw: bytes):
    """Байты -> (текст, кодировка записи). UTF-16 по BOM, UTF-8 (с BOM или без)."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        enc = "utf-16-le" if raw.startswith(codecs.BOM_UTF16_LE) else "utf-16-be"
        return raw[2:].decode(enc, errors="surrogatepass"), enc, raw[:2]
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", errors="surrogateescape"), "utf-8", codecs.BOM_UTF8
    return raw.decode("utf-8", errors="surrogateescape"), "utf-8", b""


def patch_ini(path: Path, updates: dict) -> list:
    """Меняет значения только у уже существующих `Key=Value`. updates: {(секция или None, ключ): значение}.

    Секция None: ключ ищется в любой секции. Сохраняет остальные строки, переводы строк и кодировку.
    """
    path = Path(path)
    if not path.is_file():
        return []
    text, enc, bom = _decode_ini(path.read_bytes())
    lines = text.splitlines(keepends=True)
    want = {(s.lower() if s else None, k.lower()): (s, k, v) for (s, k), v in updates.items()}
    done, changed, section = set(), [], ""
    for i, line in enumerate(lines):
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip().lower()
            continue
        m = _KEYVAL.match(line)
        if not m:
            continue
        key = m.group(2).strip().lower()
        for sk in ((section, key), (None, key)):
            if sk in want and sk not in done:
                s, k, v = want[sk]
                done.add(sk)
                if m.group(4) != v:
                    lines[i] = m.group(1) + m.group(2) + m.group(3) + v + m.group(5)
                    changed.append(k)
                break
    if changed and not ctx.dry_run:
        if not os.access(path, os.W_OK):
            ctx.log(f"  {path.name}: файл только для чтения, пропускаю")
            return []
        journal.backup_file(path)
        path.write_bytes(bom + "".join(lines).encode(enc, errors="surrogatepass" if "16" in enc else "surrogateescape"))
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
    prof = PROFILES.get(game.appid)
    if prof and prof.no_exe_tweaks:
        return False
    exe = find_exe(game, prof)
    cur = reg.read("HKLM", _ifeo(exe), "CpuPriorityClass") if exe else None
    return bool(cur and cur[0] == 3)


_LAYERS = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"


def has_layer(exe: Path, flag: str) -> bool:
    cur = reg.read("HKCU", _LAYERS, str(exe))
    return bool(cur and flag in cur[0].split())


def set_layer(exe: Path, flag: str, on: bool):
    """Флаг совместимости Windows для exe (HIGHDPIAWARE и т.п.), с записью в журнал."""
    cur = reg.read("HKCU", _LAYERS, str(exe))
    tokens = (cur[0] if cur else "~").split()
    if (flag in tokens) == on:
        return
    tokens = tokens + [flag] if on else [t for t in tokens if t != flag]
    reg.write("HKCU", _LAYERS, str(exe), " ".join(tokens), winreg.REG_SZ)


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


def _patch(f: Path, updates: dict) -> list:
    return patch_ini(f, updates) if f.suffix.lower() == ".ini" else patch_kv(f, updates)


def optimize(game: steam.Game, root: Path, tier: str = "mid"):
    """tier: "low" | "mid" | "high" (неизвестное значение трактуется как "mid"). root может быть None (Epic)."""
    if tier not in TIERS:
        tier = "mid"
    prof = PROFILES.get(game.appid)
    ctx.log(f"{game.name}:")
    if prof and prof.no_exe_tweaks:
        ctx.log("  защищённая игра (античит): меняю только конфиг, exe и реестр не трогаю")
    else:
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
    for spec, updates in list(prof.kv_files) + list(prof.video.get(tier, [])):
        for f in resolve_spec(spec, root, game.path):
            keys = _patch(f, updates)
            if keys:
                ctx.log(f"  {f.name} ({tier}): {', '.join(k if isinstance(k, str) else k[1] for k in keys)}")
    if prof.launch and root and str(game.appid).isdigit():
        try:
            steam.set_launch_options(root, game.appid, prof.launch)
        except steam.SteamRunning as e:
            ctx.log(f"  ! {e}")
