"""Минимальный парсер/писатель текстового VDF (Steam)."""
import re

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
_UNESC = {"n": "\n", "t": "\t"}


def _unesc(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _UNESC.get(m.group(1), m.group(1)), s)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def parse(text: str) -> dict:
    root: dict = {}
    stack = [root]
    key = None
    for m in _TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            d: dict = {}
            stack[-1][key] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = _unesc(s)
        else:
            stack[-1][key] = _unesc(s)
            key = None
    return root


def dump(d: dict, indent: int = 0) -> str:
    t = "\t" * indent
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f'{t}"{_esc(k)}"\n{t}{{\n{dump(v, indent + 1)}{t}}}\n')
        else:
            out.append(f'{t}"{_esc(k)}"\t\t"{_esc(v)}"\n')
    return "".join(out)


def get_ci(d: dict, key: str, create: bool = False):
    """Поиск ключа без учёта регистра (в localconfig он плавает)."""
    for k in d:
        if k.lower() == key.lower():
            return d[k]
    if create:
        d[key] = {}
        return d[key]
    return None
