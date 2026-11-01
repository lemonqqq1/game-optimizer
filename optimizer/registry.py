"""Обёртка над winreg: запись с сохранением старого значения в журнал."""
import winreg

from . import ctx, journal

HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
_ACCESS = winreg.KEY_WOW64_64KEY


def _enc(v):
    return {"hex": v.hex()} if isinstance(v, (bytes, bytearray)) else v


def _dec(v):
    return bytes.fromhex(v["hex"]) if isinstance(v, dict) else v


def read(hive: str, path: str, name: str):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | _ACCESS) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def write(hive: str, path: str, name: str, value, typ=winreg.REG_DWORD):
    if ctx.dry_run:
        ctx.log(f"  [dry-run] {hive}\\{path} : {name} = {value!r}")
        return
    old = read(hive, path, name)
    journal.record({
        "kind": "reg", "hive": hive, "path": path, "name": name,
        "existed": old is not None,
        "value": _enc(old[0]) if old else None,
        "type": old[1] if old else typ,
    })
    with winreg.CreateKeyEx(HIVES[hive], path, 0, winreg.KEY_SET_VALUE | _ACCESS) as k:
        winreg.SetValueEx(k, name, 0, typ, value)


def restore(e: dict):
    hive, path, name = HIVES[e["hive"]], e["path"], e["name"]
    if e["existed"]:
        with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE | _ACCESS) as k:
            winreg.SetValueEx(k, name, 0, e["type"], _dec(e["value"]))
    else:
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE | _ACCESS) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass


def subkeys(hive: str, path: str):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | _ACCESS) as k:
            i, out = 0, []
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    return out
    except OSError:
        return []
