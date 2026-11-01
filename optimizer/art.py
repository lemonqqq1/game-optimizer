"""Обложки игр из кэша Steam (appcache/librarycache) + заглушки."""
import hashlib
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

_FILES = {"cover": "library_600x900.jpg", "header": "header.jpg", "hero": "library_hero.jpg"}
_FONTS = (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf")


def _find(root, appid, name):
    d = Path(root) / "appcache" / "librarycache" / str(appid)
    if not d.exists():
        return None
    p = d / name
    return p if p.exists() else next(d.glob("**/" + name), None)


CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{name}"


def _download(appid, name):
    """Нет обложки в кэше Steam: качаем с CDN Steam и кладём к себе."""
    from . import journal
    dst = journal.state_dir() / "covers" / f"{appid}_{name}"
    if dst.exists():
        return dst if dst.stat().st_size else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(CDN.format(appid=appid, name=name), timeout=5) as r:
            dst.write_bytes(r.read())
    except Exception:
        dst.write_bytes(b"")  # не пытаться снова при каждом запуске
        return None
    return dst


def app_icon(size=256) -> Image.Image:
    """Иконка приложения: синий скруглённый квадрат с молнией."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=(61, 123, 255))
    k = size / 100
    bolt = [(58, 10), (24, 56), (46, 56), (38, 90), (76, 42), (54, 42), (64, 10)]
    d.polygon([(x * k, y * k) for x, y in bolt], fill=(255, 255, 255))
    return im


def placeholder(title: str, size) -> Image.Image:
    h = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:6], 16)
    base = (40 + h % 90, 50 + (h >> 8) % 90, 80 + (h >> 16) % 120)
    im = Image.new("RGB", size, base)
    d = ImageDraw.Draw(im)
    font = None
    for f in _FONTS:
        try:
            font = ImageFont.truetype(f, size[1] // 3)
            break
        except OSError:
            pass
    letter = (title.strip()[:1] or "?").upper()
    d.text((size[0] / 2, size[1] / 2), letter, fill=(255, 255, 255), font=font, anchor="mm")
    return im


def load(root, appid, title: str, size, kind: str = "cover"):
    """PhotoImage нужного размера; если обложки нет, пробуем header, затем заглушку."""
    im = None
    for k in (kind, "cdn", "header", "hero"):
        if k == "cdn":
            p = _download(appid, _FILES[kind])
        else:
            p = _find(root, appid, _FILES[k]) if root else None
        if not p:
            continue
        try:
            im = Image.open(p)
            im.draft("RGB", (size[0] * 2, size[1] * 2))
            im = ImageOps.fit(im.convert("RGB"), size, Image.LANCZOS)
            break
        except Exception:
            im = None
    return ImageTk.PhotoImage(im or placeholder(title, size))
