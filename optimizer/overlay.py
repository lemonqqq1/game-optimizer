"""Оверлеи поверх игры: свой прицел и мини-монитор железа. Окна прозрачные для мыши.

Работают в оконном режиме и «полноэкранном без рамки». В эксклюзивном полноэкранном режиме
Windows рисует игру поверх всех окон, поэтому оверлей не виден.
"""
import ctypes
import tkinter as tk

from . import sysmon

KEY = "#010203"  # цвет, который Windows делает прозрачным
STYLES = ("Крест", "Крест с точкой", "Точка", "Круг", "Круг с точкой", "T-образный")
COLORS = {"Зелёный": "#00ff66", "Голубой": "#00e5ff", "Жёлтый": "#ffe600", "Розовый": "#ff3df2",
          "Красный": "#ff2b2b", "Белый": "#ffffff"}
CORNERS = ("Слева сверху", "Справа сверху", "Слева снизу", "Справа снизу")
HOTKEYS = {"crosshair": ("Ctrl+Shift+X", (0x11, 0x10, 0x58)), "monitor": ("Ctrl+Shift+M", (0x11, 0x10, 0x4D))}


def _click_through(win):
    win.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
    # LAYERED | TRANSPARENT | TOOLWINDOW (не в Alt+Tab) | NOACTIVATE
    ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)


def _base(root):
    w = tk.Toplevel(root, bg=KEY)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.attributes("-transparentcolor", KEY)
    w.withdraw()
    return w


class Crosshair:
    SIZE = 120

    def __init__(self, root):
        self.root = root
        self.win = _base(root)
        self.cv = tk.Canvas(self.win, width=self.SIZE, height=self.SIZE, bg=KEY, highlightthickness=0)
        self.cv.pack()
        self.visible = False
        _click_through(self.win)

    def draw(self, cfg):
        draw(self.cv, cfg, self.SIZE // 2)

    def show(self, cfg):
        self.draw(cfg)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.win.geometry(f"{self.SIZE}x{self.SIZE}+{sw // 2 - self.SIZE // 2}+{sh // 2 - self.SIZE // 2}")
        self.win.deiconify()
        self.win.lift()
        self.visible = True

    def hide(self):
        self.win.withdraw()
        self.visible = False


def draw(cv, cfg, c):
    """Рисует прицел на холсте с центром в (c, c). Используется и оверлеем, и превью."""
    cv.delete("x")
    st, col = cfg["style"], cfg["color"]
    s, t, g = int(cfg["size"]), int(cfg["thick"]), int(cfg["gap"])
    out = "#000000" if cfg.get("outline") else None

    def bar(x1, y1, x2, y2):
        if out:
            cv.create_rectangle(x1 - 1, y1 - 1, x2 + 1, y2 + 1, fill=out, outline="", tags="x")
        cv.create_rectangle(x1, y1, x2, y2, fill=col, outline="", tags="x")

    def dot():
        r = max(1, t)
        if out:
            cv.create_rectangle(c - r // 2 - 1, c - r // 2 - 1, c + (r + 1) // 2 + 1, c + (r + 1) // 2 + 1,
                                fill=out, outline="", tags="x")
        cv.create_rectangle(c - r // 2, c - r // 2, c + (r + 1) // 2, c + (r + 1) // 2, fill=col,
                            outline="", tags="x")

    def circle():
        r = g + s // 2 + 2
        if out:
            cv.create_oval(c - r, c - r, c + r, c + r, outline=out, width=t + 2, tags="x")
        cv.create_oval(c - r, c - r, c + r, c + r, outline=col, width=t, tags="x")

    lo, hi = -(t // 2), (t + 1) // 2
    if st in ("Крест", "Крест с точкой", "T-образный"):
        if st != "T-образный":
            bar(c + lo, c - g - s, c + hi, c - g)                  # верх
        bar(c + lo, c + g, c + hi, c + g + s)                      # низ
        bar(c - g - s, c + lo, c - g, c + hi)                      # лево
        bar(c + g, c + lo, c + g + s, c + hi)                      # право
    if st in ("Круг", "Круг с точкой"):
        circle()
    if st in ("Точка", "Крест с точкой", "Круг с точкой"):
        dot()


class MonitorOverlay:
    W, H = 330, 30

    def __init__(self, root, mon):
        self.root, self.mon = root, mon
        self.win = _base(root)
        self.cv = tk.Canvas(self.win, width=self.W, height=self.H, bg=KEY, highlightthickness=0)
        self.cv.pack()
        self.visible = False
        _click_through(self.win)

    def show(self, corner):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = 12 if "Слева" in corner else sw - self.W - 12
        y = 10 if "сверху" in corner else sh - self.H - 52
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.win.deiconify()
        self.visible = True
        self.tick()

    def hide(self):
        self.win.withdraw()
        self.visible = False

    def text(self):
        m, last = self.mon, sysmon.last
        parts = [f"CPU {last(m.cpu):.0f}%"]
        if m.has_gpu:
            parts.append(f"GPU {last(m.gpu):.0f}% {m.gpu_temp:.0f}°C")
        parts.append(f"RAM {m.ram_used:.1f}/{m.ram_total:.0f} ГБ")
        return "   ".join(parts)

    def tick(self):
        if not self.visible:
            return
        self.cv.delete("all")
        tid = self.cv.create_text(10, self.H // 2, text=self.text(), anchor="w", fill="#7CFFB2",
                                  font=("Consolas", 11, "bold"))
        x2 = self.cv.bbox(tid)[2]
        bg = self.cv.create_rectangle(0, 0, x2 + 10, self.H, fill="#0b0d12", outline="")
        self.cv.tag_lower(bg)
        self.win.lift()
        self.root.after(1000, self.tick)


class Hotkeys:
    """Опрос клавиш (GetAsyncKeyState): работает, даже когда фокус в игре."""

    def __init__(self, root, actions: dict):
        self.root, self.actions, self.down = root, actions, set()
        self.poll()

    def poll(self):
        gks = ctypes.windll.user32.GetAsyncKeyState
        for name, (_, keys) in HOTKEYS.items():
            pressed = all(gks(k) & 0x8000 for k in keys)
            if pressed and name not in self.down:
                self.down.add(name)
                fn = self.actions.get(name)
                if fn:
                    fn()
            elif not pressed:
                self.down.discard(name)
        self.root.after(60, self.poll)
