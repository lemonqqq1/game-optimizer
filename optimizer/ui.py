"""Виджеты в стиле игровых бустеров: скруглённые карточки и кнопки (рисуются через PIL), переключатели,
спарклайны, кольцо оценки, всплывающие уведомления."""
import ctypes
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

BG, SIDE, CARD, CARD_HI, LINE = "#0a0c12", "#0e1119", "#141824", "#1b2030", "#262d42"
ACCENT, ACCENT2, ACCENT_HI = "#7b61ff", "#3d8bff", "#9580ff"
TEXT, MUTED, DIM = "#eef1f8", "#8b93a7", "#5b627a"
OK, WARN, DANGER = "#2ee59d", "#ffb547", "#ff5c6c"
FONT = "Segoe UI"
SS = 3  # суперсэмплинг для гладких краёв

_cache = {}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(size, c1, c2) -> Image.Image:
    """Горизонтальный градиент c1 -> c2."""
    w, h = size
    mask = Image.linear_gradient("L").rotate(90).resize((w, h))
    return Image.composite(Image.new("RGB", (w, h), c1), Image.new("RGB", (w, h), c2), mask)


def rounded(im: Image.Image, r: int, bg: str, outline=None) -> Image.Image:
    """Скругляет углы картинки, подкладывая цвет фона родителя."""
    w, h = im.size
    mask = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = Image.new("RGB", (w, h), bg)
    out.paste(im, (0, 0), mask)
    if outline:
        big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), r * SS, outline=outline,
                                              width=SS)
        out.paste(big.resize((w, h), Image.LANCZOS), (0, 0), big.resize((w, h), Image.LANCZOS))
    return out


def rr(w, h, r, fill, bg, outline=None, grad=None, cache=True):
    key = (w, h, r, fill, bg, outline, grad)
    if cache and key in _cache:
        return _cache[key]
    base = gradient((w, h), *grad) if grad else Image.new("RGB", (w, h), fill)
    ph = ImageTk.PhotoImage(rounded(base, r, bg, outline))
    if cache:
        _cache[key] = ph
    return ph


def label(parent, text, size=10, color=TEXT, bold=False, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", parent["bg"]), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), **kw)


class Card(tk.Frame):
    """Фрейм со скруглённым фоном. Содержимое кладётся с отступом >= радиуса."""

    def __init__(self, parent, r=14, fill=CARD, outline=None, **kw):
        super().__init__(parent, bg=fill, **kw)
        self.r, self.fill, self.outline = r, fill, outline
        self._bg = tk.Label(self, bd=0, bg=fill)
        self._bg.place(x=0, y=0, relwidth=1, relheight=1)
        self._size = None
        self.bind("<Configure>", lambda e: self.redraw())

    def redraw(self, force=False):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4 or (not force and self._size == (w, h)):
            return
        self._size = (w, h)
        img = rr(w, h, self.r, self.fill, self.master["bg"], self.outline, cache=False)
        self._bg.configure(image=img)
        self._bg.image = img
        self._bg.lower()

    def set_outline(self, outline):
        if outline != self.outline:
            self.outline = outline
            self.redraw(force=True)

    def set_fill(self, fill):
        if fill != self.fill:
            self.fill = fill
            self.configure(bg=fill)
            for c in self.winfo_children():
                if isinstance(c, (tk.Label, tk.Frame)) and not isinstance(c, (Btn, Toggle, Card)):
                    c.configure(bg=fill)
            self.redraw(force=True)


class Btn(tk.Label):
    """Скруглённая кнопка. primary: градиент фиолетовый -> синий."""
    KINDS = {
        "primary": (None, None, "#ffffff", (ACCENT, ACCENT2), (ACCENT_HI, "#5b9dff")),
        "ghost": (CARD_HI, "#262d42", TEXT, None, None),
        "danger": ("#2a1519", "#3b1c22", "#ff8a95", None, None),
        "ok": ("#0f2e22", "#15402f", OK, None, None),
    }

    def __init__(self, parent, text, command, kind="primary", size=10, padx=16, pady=8, width=None, r=10):
        fill, hi, fg, grad, grad_hi = self.KINDS[kind]
        font = tkfont.Font(family=FONT, size=size, weight="bold")
        w = width or font.measure(text) + padx * 2
        h = font.metrics("linespace") + pady * 2
        bg = parent["bg"]
        self.img = rr(w, h, r, fill, bg, grad=grad)
        self.img_hi = rr(w, h, r, hi, bg, grad=grad_hi)
        self.img_off = rr(w, h, r, "#1d2130", bg)
        self.fg = fg
        super().__init__(parent, image=self.img, text=text, compound="center", fg=fg, font=font, bd=0,
                         bg=bg, cursor="hand2", activebackground=bg)
        self.command, self.enabled = command, True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(image=self.img_hi))
        self.bind("<Leave>", lambda e: self.enabled and self.configure(image=self.img))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def set_enabled(self, v: bool):
        self.enabled = v
        self.configure(image=self.img if v else self.img_off, fg=self.fg if v else DIM,
                       cursor="hand2" if v else "arrow")


class Toggle(tk.Label):
    """Переключатель-«таблетка» вместо галочки."""

    def __init__(self, parent, variable: tk.BooleanVar, command=None):
        bg = parent["bg"]
        super().__init__(parent, bd=0, bg=bg, cursor="hand2")
        self.var, self.command = variable, command
        self.on, self.off = self._img(True, bg), self._img(False, bg)
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *a: self._sync())
        self._sync()

    @staticmethod
    def _img(on, bg):
        key = ("toggle", on, bg)
        if key not in _cache:
            w, h = 42, 24
            base = gradient((w * SS, h * SS), ACCENT, ACCENT2) if on else Image.new("RGB", (w * SS, h * SS),
                                                                                   "#2a3046")
            im = Image.new("RGB", (w * SS, h * SS), bg)
            m = Image.new("L", (w * SS, h * SS), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), h * SS // 2, fill=255)
            im.paste(base, (0, 0), m)
            d = ImageDraw.Draw(im)
            pad = 3 * SS
            x = (w - h) * SS + pad if on else pad
            d.ellipse((x, pad, x + h * SS - 2 * pad, h * SS - pad), fill="#ffffff" if on else "#9aa2b8")
            _cache[key] = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
        return _cache[key]

    def _click(self, e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _sync(self):
        self.configure(image=self.on if self.var.get() else self.off)


class Spark(tk.Canvas):
    """Спарклайн: линия истории + заливка под ней."""

    def __init__(self, parent, w, h, color):
        super().__init__(parent, width=w, height=h, bg=parent["bg"], highlightthickness=0)
        self.w, self.h, self.color = w, h, color
        self.fill = mix(color, parent["bg"], 0.78)

    def draw(self, values, top=100.0):
        self.delete("all")
        vals = list(values)
        if len(vals) < 2:
            return
        step = self.w / (len(vals) - 1)
        pts = [(i * step, self.h - 2 - (min(v, top) / top) * (self.h - 4)) for i, v in enumerate(vals)]
        poly = [(0, self.h)] + pts + [(self.w, self.h)]
        self.create_polygon(*[c for p in poly for c in p], fill=self.fill, outline="")
        self.create_line(*[c for p in pts for c in p], fill=self.color, width=2, smooth=True)


def ring_image(score: int, size=210, hover=False, bg=CARD) -> ImageTk.PhotoImage:
    """Кольцо оценки ПК: серый трек + дуга-градиент на score%."""
    key = ("ring", score, size, hover, bg)
    if key in _cache:
        return _cache[key]
    S = size * SS
    im = Image.new("RGB", (S, S), bg)
    d = ImageDraw.Draw(im)
    wd = 16 * SS
    box = (wd, wd, S - wd, S - wd)
    glow = mix(ACCENT, bg, 0.85 if not hover else 0.7)
    d.ellipse((wd * 2, wd * 2, S - wd * 2, S - wd * 2), fill=glow)
    d.ellipse((wd * 2.6, wd * 2.6, S - wd * 2.6, S - wd * 2.6), fill=mix(CARD_HI, bg, 0.2 if hover else 0.5))
    d.arc(box, 0, 360, fill="#232a3d", width=wd)
    n = max(1, int(score * 3.6))
    for i in range(n):
        d.arc(box, -90 + i, -90 + i + 1.6, fill=mix(ACCENT2, ACCENT, i / 360), width=wd)
    ph = ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))
    _cache[key] = ph
    return ph


def toast(root, text, kind="ok"):
    """Уведомление в правом нижнем углу окна программы."""
    color = {"ok": OK, "warn": WARN, "err": DANGER}.get(kind, ACCENT)
    w = tk.Toplevel(root, bg=BG)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    card = Card(w, r=12, fill=CARD_HI, outline=mix(color, CARD_HI, 0.4))
    card.pack()
    row = tk.Frame(card, bg=CARD_HI)
    row.pack(padx=16, pady=12)
    label(row, "●", 11, color).pack(side="left")
    label(row, text, 10, TEXT, wraplength=340, justify="left").pack(side="left", padx=(8, 0))
    w.update_idletasks()
    x = root.winfo_rootx() + root.winfo_width() - w.winfo_reqwidth() - 24
    y = root.winfo_rooty() + root.winfo_height() - w.winfo_reqheight() - 24
    w.geometry(f"+{x}+{y}")
    try:
        w.attributes("-alpha", 0.97)
    except tk.TclError:
        pass
    root.after(3200, w.destroy)


def dark_titlebar(win):
    try:
        win.update()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        # Windows 11: цвет заголовка под фон программы
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(0x00120c0a)), 4)
    except Exception:
        pass


class Scroll(tk.Frame):
    def __init__(self, parent, bg=BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        from tkinter import ttk
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize)
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
            w.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.on_resize = None

    def _wheel(self, e):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")

    def _resize(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        if self.on_resize:
            self.on_resize(e.width)


class Slider(tk.Canvas):
    """Ползунок: тонкая дорожка, заполненная часть с акцентом, белая ручка."""

    def __init__(self, parent, var: tk.IntVar, lo, hi, length=170, command=None):
        super().__init__(parent, width=length, height=22, bg=parent["bg"], highlightthickness=0, cursor="hand2")
        self.var, self.lo, self.hi, self.L, self.command = var, lo, hi, length, command
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.draw()

    def _x(self, v):
        return 9 + (v - self.lo) / (self.hi - self.lo) * (self.L - 18)

    def draw(self):
        self.delete("all")
        x = self._x(self.var.get())
        self.create_line(9, 11, self.L - 9, 11, fill=LINE, width=4, capstyle="round")
        self.create_line(9, 11, x, 11, fill=ACCENT, width=4, capstyle="round")
        self.create_oval(x - 8, 3, x + 8, 19, fill="#ffffff", outline=ACCENT, width=2)

    def _drag(self, e):
        t = min(1.0, max(0.0, (e.x - 9) / (self.L - 18)))
        v = round(self.lo + t * (self.hi - self.lo))
        if v != self.var.get():
            self.var.set(v)
            self.draw()
            if self.command:
                self.command(v)
