"""Окно программы в стиле игровых бустеров: панель с оценкой ПК и живым мониторингом, библиотека игр,
буст, оверлей (прицел и монитор), видеокарта, система, журнал."""
import ctypes
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from . import (__version__, art, boost, core, ctx, extras, games, gpu, journal, library, overlay, settings,
               steam, sysmon, system_tweaks)
from .ui import (ACCENT, ACCENT2, BG, CARD, CARD_HI, DANGER, DIM, FONT, LINE, MUTED, OK, SIDE, TEXT, WARN, Btn,
                 Card, Scroll, Slider, Spark, Toggle, dark_titlebar, gradient, label, mix, ring_image, rounded, toast)

COVER = (150, 225)
CARD_W = 186
HEADER = (168, 79)


def has_flags(opts: str, chunks) -> bool:
    return bool(chunks) and all(re.search(r"(?<!\S)" + re.escape(c) + r"(?!\S)", opts) for c in chunks)


def section(parent, title, sub=""):
    label(parent, title, 13, bold=True).pack(anchor="w", pady=(18, 0))
    if sub:
        label(parent, sub, 9, MUTED, wraplength=820, justify="left").pack(anchor="w", pady=(2, 0))


def toggle_row(parent, var, title, desc="", right=None, command=None, wrap=560):
    row = tk.Frame(parent, bg=parent["bg"])
    row.pack(fill="x", pady=5)
    Toggle(row, var, command).pack(side="left", padx=(0, 12))
    col = tk.Frame(row, bg=parent["bg"])
    col.pack(side="left", fill="x", expand=True)
    label(col, title, 10, bold=True).pack(anchor="w")
    if desc:
        label(col, desc, 9, MUTED, wraplength=wrap, justify="left").pack(anchor="w")
    if right:
        label(row, right[0], 9, right[1], bold=True).pack(side="right", padx=(8, 0))
    return row


class GameWindow(tk.Toplevel):
    """Окно игры: большой баннер, статистика, «Играть», оптимизация и фишки."""
    W = 900
    HERO_W = 884  # минус полоса прокрутки

    def __init__(self, app, game):
        super().__init__(app, bg=BG)
        self.app, self.game = app, game
        self.title(game.name)
        self.geometry(f"{self.W}x760")
        self.minsize(self.W, 520)
        self.profile = games.PROFILES.get(game.appid)
        self.exe = games.find_exe(game, self.profile)
        self.engine = library.engine(game)
        self.ex = extras.for_game(game.appid, self.engine, self.profile.launch if self.profile else ())
        dark_titlebar(self)

        sc = Scroll(self)
        sc.pack(fill="both", expand=True)
        body = sc.inner
        self._hero(body)
        wrap = tk.Frame(body, bg=BG)
        wrap.pack(fill="x", padx=28)

        btns = tk.Frame(wrap, bg=BG)
        btns.pack(fill="x", pady=(4, 0))
        Btn(btns, "▶  ИГРАТЬ", self.play, "primary", 12, padx=34, pady=11).pack(side="left")
        self.opt_btn = Btn(btns, "⚡  Оптимизировать", self.optimize, "ghost", 11, padx=20, pady=10)
        self.opt_btn.pack(side="left", padx=(10, 0))
        fav = game.appid in app.cfg["favorites"]
        self.fav_btn = Btn(btns, "★" if fav else "☆", self.toggle_fav, "ghost", 13, padx=14, pady=8)
        self.fav_btn.pack(side="right")
        for text, fn in (("Магазин", lambda: os.startfile(f"steam://store/{game.appid}")),
                         ("Проверить файлы", lambda: os.startfile(f"steam://validate/{game.appid}")),
                         ("Папка", lambda: os.startfile(game.path))):
            Btn(btns, text, fn, "ghost", 9, padx=12, pady=9).pack(side="right", padx=(0, 6))

        stats = tk.Frame(wrap, bg=BG)
        stats.pack(fill="x", pady=(16, 0))
        stats.columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        mins, last = app.playtime.get(game.appid, (0, 0))
        for i, (k, v) in enumerate((("НАИГРАНО", library.fmt_hours(mins)), ("ПОСЛЕДНИЙ ЗАПУСК", library.fmt_ago(last)),
                                    ("РАЗМЕР", library.fmt_size(library.size_on_disk(game))),
                                    ("ДВИЖОК", library.ENGINES.get(self.engine, "—")))):
            c = Card(stats, r=12)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            label(c, k, 8, MUTED, True).pack(anchor="w", padx=14, pady=(12, 0))
            label(c, v, 13, bold=True).pack(anchor="w", padx=14, pady=(0, 12))

        self.status = label(wrap, "", 9, WARN, wraplength=820, justify="left")
        self.status.pack(anchor="w", pady=(4, 0))

        opt = Card(wrap)
        opt.pack(fill="x", pady=(8, 0))
        inner = tk.Frame(opt, bg=CARD)
        inner.pack(fill="x", padx=20, pady=16)
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        label(head, "⚡  Оптимизация", 13, bold=True).pack(side="left")
        self.badge = label(head, "", 9, bold=True)
        self.badge.pack(side="right")
        for line in self.plan():
            label(inner, "•  " + line, 9, MUTED, wraplength=800, justify="left").pack(anchor="w", pady=1)

        self._build_extras(wrap)
        tk.Frame(body, bg=BG, height=24).pack()
        self.refresh()

    def _hero(self, body):
        w, h = self.HERO_W, 250
        im = art.load_pil(self.app.root_dir, self.game.appid, self.game.name, (w, h), "hero")
        fade = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(min(255, v * 1.25)))
        im = Image.composite(Image.new("RGB", (w, h), BG), im, fade)
        self.hero_img = ImageTk.PhotoImage(im)
        cv = tk.Canvas(body, width=w, height=h, bg=BG, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=self.hero_img, anchor="nw")
        cv.create_text(30, h - 46, text=self.game.name, anchor="w", fill=TEXT, font=(FONT, 24, "bold"))
        chips = [library.ENGINES.get(self.engine), "Профиль игры" if self.profile else None,
                 f"Фишек: {len(self.ex.extras) + len(self.ex.choices) + (1 if self.ex.fonts_conf else 0)}"]
        x = 32
        for t in filter(None, chips):
            tid = cv.create_text(x + 10, h - 14, text=t, anchor="w", fill=TEXT, font=(FONT, 8, "bold"))
            x1, y1, x2, y2 = cv.bbox(tid)
            cv.create_rectangle(x1 - 10, y1 - 4, x2 + 10, y2 + 4, fill=mix(ACCENT, BG, 0.55), outline="")
            cv.tag_raise(tid)
            x = x2 + 22

    def _build_extras(self, wrap):
        ex, path = self.ex, self.game.path
        box = Card(wrap)
        box.pack(fill="x", pady=(12, 0))
        inner = tk.Frame(box, bg=CARD)
        inner.pack(fill="x", padx=20, pady=16)
        label(inner, "✨  Фишки", 13, bold=True).pack(anchor="w")
        label(inner, "Всё пишется через журнал и откатывается. Параметры запуска Steam меняются только при "
                     "закрытом Steam.", 9, MUTED, wraplength=800, justify="left").pack(anchor="w", pady=(2, 8))
        cur_lines = extras.current_cfg(path, ex) if ex.autoexec else []
        self.launch_opts = steam.get_launch_options(self.app.root_dir, self.game.appid)

        def combo_row(title, var, values, hint=""):
            row = tk.Frame(inner, bg=CARD)
            row.pack(fill="x", pady=5)
            label(row, title, 10, bold=True, width=24, anchor="w").pack(side="left")
            ttk.Combobox(row, textvariable=var, values=values, state="readonly", width=30).pack(side="left")
            if hint:
                label(row, hint, 9, MUTED).pack(side="left", padx=10)

        self.font_var = None
        if ex.fonts_conf:
            cur = extras.current_font(path, ex)
            self.font_var = tk.StringVar(value=next((k for k, v in extras.FONTS.items() if v == cur), "Стандартный"))
            combo_row("Шрифт интерфейса", self.font_var, ["Стандартный"] + list(extras.FONTS), "меню, HUD, чат")

        self.choice_vars = {}
        for c in ex.choices:
            sel = next((n for n, o in c.options.items()
                        if (o.lines and o.lines[0] in cur_lines) or has_flags(self.launch_opts, o.launch)),
                       "Без изменений")
            v = tk.StringVar(value=sel)
            self.choice_vars[c.key] = v
            combo_row(c.title, v, ["Без изменений"] + list(c.options))

        self.extra_vars = {}
        for e in ex.extras:
            if e.kind == "dpi":
                on = bool(self.exe) and games.has_layer(self.exe, "HIGHDPIAWARE")
            elif e.launch:
                on = has_flags(self.launch_opts, e.launch)
            else:
                on = bool(cur_lines) and all(l in cur_lines for l in e.lines)
            v = tk.BooleanVar(value=on)
            self.extra_vars[e.key] = v
            tag = ("запуск", ACCENT2) if e.launch else ("конфиг", OK) if e.lines else ("Windows", MUTED)
            toggle_row(inner, v, e.title, e.desc, tag)

        bottom = tk.Frame(inner, bg=CARD)
        bottom.pack(fill="x", pady=(12, 0))
        Btn(bottom, "✨  Применить фишки", self.apply_extras, "primary", 10).pack(side="left")

    def plan(self):
        items = ["Запуск на дискретной видеокарте, приоритет процесса High, без оптимизаций полного экрана"]
        p = self.profile
        if p:
            if p.launch:
                items.append("Параметры запуска Steam: " + " ".join(p.launch))
            if p.autoexec_lines:
                items.append(f"Строки в {os.path.basename(p.autoexec)}: " + ", ".join(p.autoexec_lines))
            if p.kv_files:
                keys = [k.replace("setting.", "") for _, u in p.kv_files for k in u]
                items.append("Видеонастройки: " + ", ".join(keys) + " (FPS приоритетнее красоты)")
        else:
            items.append("Отдельного профиля у игры нет: применяются общие настройки, ниже есть фишки")
        return items

    def refresh(self):
        done = games.is_optimized(self.game)
        self.badge.configure(text="✓ ОПТИМИЗИРОВАНО" if done else "НЕ ОПТИМИЗИРОВАНО", fg=OK if done else MUTED)

    def toggle_fav(self):
        on = self.app.toggle_fav(self.game.appid)
        self.fav_btn.configure(text="★" if on else "☆")

    def play(self):
        self.app.play(self.game)
        self.status.configure(text="Запускаю через Steam...", fg=OK)

    def optimize(self):
        if self.profile and self.profile.launch and steam.is_steam_running():
            self.status.configure(text="Steam открыт: параметры запуска не запишутся. Закрой Steam и повтори, "
                                       "остальные настройки применятся сейчас.", fg=WARN)
        else:
            self.status.configure(text="Применяю...", fg=MUTED)
        self.app.run_task(lambda: games.optimize(self.game, self.app.root_dir), self.after_optimize)

    def apply_extras(self):
        ex, path, root, appid = self.ex, self.game.path, self.app.root_dir, self.game.appid
        family = extras.FONTS.get(self.font_var.get()) if self.font_var else None
        lines, launch, dpi = [], [], False
        for c in ex.choices:
            o = c.options.get(self.choice_vars[c.key].get())
            if o:
                lines += o.lines
                launch += o.launch
        for e in ex.extras:
            if self.extra_vars[e.key].get():
                lines += e.lines
                launch += e.launch
                dpi = dpi or e.kind == "dpi"
        managed = extras.all_launch(ex)
        if appid == "730" and lines:  # CS2 сам не запускает autoexec.cfg
            launch.append("+exec autoexec")
        remove = [c for c in managed if c not in launch]
        new_opts = steam.merge_flags(steam.strip_flags(self.launch_opts, remove), launch)
        steam_open = new_opts != self.launch_opts and steam.is_steam_running()

        def work():
            ctx.log(f"{self.game.name}: фишки")
            if ex.fonts_conf:
                extras.set_font(path, ex, family)
            if ex.autoexec:
                extras.set_cfg(path, ex, lines)
            if self.exe:
                games.set_layer(self.exe, "HIGHDPIAWARE", dpi)
            if managed or launch:
                try:
                    steam.set_launch_options(root, appid, launch, remove)
                except steam.SteamRunning:
                    ctx.log("  ! закрой Steam и примени ещё раз: параметры запуска не записаны")

        def done():
            if not self.winfo_exists():
                return
            self.launch_opts = steam.get_launch_options(root, appid)
            if steam_open:
                self.status.configure(text="Фишки применены, кроме параметров запуска: закрой Steam и нажми ещё раз.",
                                      fg=WARN)
                toast(self.app, "Закрой Steam, чтобы записать параметры запуска", "warn")
            else:
                self.status.configure(text="Фишки применены. Перезапусти игру, если она открыта.", fg=OK)
                toast(self.app, f"{self.game.name}: фишки применены")

        self.status.configure(text="Применяю фишки...", fg=MUTED)
        self.app.run_task(work, done)

    def after_optimize(self):
        if self.winfo_exists():
            self.refresh()
            self.status.configure(text="Готово. Всё можно откатить на вкладке «Журнал».", fg=OK)


class App(tk.Tk):
    NAV = (("home", "◆", "Панель"), ("games", "▦", "Игры"), ("boost", "⚡", "Буст"), ("overlay", "⌖", "Оверлей"),
           ("gpu", "▣", "Видеокарта"), ("system", "⚙", "Система"), ("log", "≡", "Журнал"))

    def __init__(self):
        super().__init__()
        self.title(f"Game Optimizer {__version__}")
        self.geometry("1200x800")
        self.minsize(1040, 680)
        self.configure(bg=BG)
        self.icon = ImageTk.PhotoImage(art.app_icon(64))
        self.iconphoto(True, self.icon)
        self.q: queue.Queue = queue.Queue()
        ctx.set_logger(self.q.put)
        self.busy = False
        self.images = []
        self.tweak_vars = {}
        self.cfg = settings.load()
        self.mon = sysmon.Monitor()
        self.admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        self._style()

        self.gpus = gpu.detect()
        self.root_dir = steam.steam_root()
        self.games = steam.installed_games(self.root_dir) if self.root_dir else []
        self.playtime = library.playtimes(self.root_dir)
        self.sizes = {g.appid: library.size_on_disk(g) for g in self.games}
        self.sys_status, self.score = {}, 0

        self._build_sidebar()
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)
        self.topbar = ttk.Progressbar(self.content, mode="indeterminate", style="Thin.Horizontal.TProgressbar")
        self.pages = {"home": self._page_home(), "games": self._page_games(), "boost": self._page_boost(),
                      "overlay": self._page_overlay(), "gpu": self._page_gpu(), "system": self._page_system(),
                      "log": self._page_log()}
        self.crosshair = overlay.Crosshair(self)
        self.monitor_ov = overlay.MonitorOverlay(self, self.mon)
        overlay.Hotkeys(self, {"crosshair": lambda: self.ch_on.set(not self.ch_on.get()) or self.apply_crosshair(),
                               "monitor": lambda: self.mo_on.set(not self.mo_on.get()) or self.apply_monitor()})
        if self.cfg["crosshair"].get("enabled"):
            self.apply_crosshair()
        if self.cfg["monitor"].get("enabled"):
            self.apply_monitor()
        if self.cfg.get("timer"):
            self.after(300, self.apply_timer)
        self.show("home")
        dark_titlebar(self)
        self.after(100, self.pump)
        self.after(500, self.tick)
        self.refresh_score()

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Vertical.TScrollbar", background=CARD_HI, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=CARD_HI, darkcolor=CARD_HI, gripcount=0, arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", LINE)])
        style.configure("TCombobox", fieldbackground=CARD_HI, background=CARD_HI, foreground=TEXT, padding=5,
                        arrowcolor=TEXT, bordercolor=LINE, lightcolor=CARD_HI, darkcolor=CARD_HI)
        style.map("TCombobox", fieldbackground=[("readonly", CARD_HI)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", CARD_HI)], selectforeground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", CARD_HI)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))
        for name, th in (("Horizontal.TProgressbar", 8), ("Thin.Horizontal.TProgressbar", 3)):
            style.configure(name, background=ACCENT, troughcolor=CARD_HI if th > 3 else BG, bordercolor=BG,
                            lightcolor=ACCENT, darkcolor=ACCENT2, thickness=th)

    # ---------- каркас ----------
    def _build_sidebar(self):
        side = tk.Frame(self, bg=SIDE, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        logo = tk.Frame(side, bg=SIDE)
        logo.pack(fill="x", padx=20, pady=(24, 26))
        self.logo_img = ImageTk.PhotoImage(art.app_icon(40))
        tk.Label(logo, image=self.logo_img, bg=SIDE).pack(side="left")
        col = tk.Frame(logo, bg=SIDE)
        col.pack(side="left", padx=10)
        label(col, "GAME", 13, ACCENT, True).pack(anchor="w")
        label(col, "OPTIMIZER", 13, TEXT, True).pack(anchor="w", pady=(0, 0))
        label(side, "МЕНЮ", 8, DIM, True).pack(anchor="w", padx=24, pady=(0, 6))
        self.nav = {}
        for key, icon, text in self.NAV:
            c = Card(side, r=10, fill=SIDE)
            c.pack(fill="x", padx=12, pady=2)
            row = tk.Frame(c, bg=SIDE)
            row.pack(fill="x", padx=12, pady=9)
            ic = label(row, icon, 12, MUTED, True, width=2)
            ic.pack(side="left")
            tx = label(row, text, 11, MUTED, True)
            tx.pack(side="left", padx=(6, 0))
            for w in (c, row, ic, tx):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
                w.bind("<Enter>", lambda e, k=key: k != self.current and self._nav_paint(k, "#141826"))
                w.bind("<Leave>", lambda e, k=key, c=c: k != self.current and not self._inside(c)
                       and self._nav_paint(k, SIDE))
                w.configure(cursor="hand2")
            self.nav[key] = (c, row, ic, tx)

        foot = Card(side, r=12, fill=CARD)
        foot.pack(side="bottom", fill="x", padx=12, pady=16)
        fi = tk.Frame(foot, bg=CARD)
        fi.pack(fill="x", padx=14, pady=12)
        self.side_cpu = label(fi, "CPU —", 9, TEXT, True)
        self.side_cpu.pack(anchor="w")
        self.side_gpu = label(fi, "GPU —", 9, TEXT, True)
        self.side_gpu.pack(anchor="w")
        label(fi, "● Администратор" if self.admin else "● Нет прав админа", 8,
              OK if self.admin else WARN, True).pack(anchor="w", pady=(6, 0))
        label(fi, f"v{__version__}  ·  бонус к гайдам hursaalo", 8, DIM).pack(anchor="w")
        self.current = None

    def _nav_paint(self, key, fill, active=False):
        c, row, ic, tx = self.nav[key]
        c.set_fill(fill)
        row.configure(bg=fill)
        ic.configure(bg=fill, fg=ACCENT if active else MUTED)
        tx.configure(bg=fill, fg=TEXT if active else MUTED)

    def show(self, key):
        for k, p in self.pages.items():
            p.pack_forget()
            self._nav_paint(k, SIDE)
        self.pages[key].pack(fill="both", expand=True)
        self._nav_paint(key, CARD_HI, True)
        self.current = key
        if key == "games":
            self._check_steam_banner()
        if key == "home":
            self.refresh_score()
        if key == "boost":
            self.refresh_bg()

    def page(self, title, subtitle=""):
        f = tk.Frame(self.content, bg=BG)
        head = tk.Frame(f, bg=BG)
        head.pack(fill="x", padx=32, pady=(24, 14))
        label(head, title, 22, bold=True).pack(anchor="w")
        if subtitle:
            label(head, subtitle, 10, MUTED).pack(anchor="w", pady=(2, 0))
        return f

    # ---------- Панель ----------
    def _page_home(self):
        g = self.gpus[0] if self.gpus else None
        f = self.page("Панель", (f"{g.name}  ·  драйвер {g.driver}" if g else "Видеокарта не определена")
                      + f"  ·  игр Steam: {len(self.games)}")
        body = tk.Frame(f, bg=BG)
        body.pack(fill="both", expand=True, padx=32)

        hero = Card(body, r=18)
        hero.pack(fill="x")
        hi = tk.Frame(hero, bg=CARD)
        hi.pack(fill="x", padx=24, pady=20)
        self.ring = tk.Canvas(hi, width=210, height=210, bg=CARD, highlightthickness=0, cursor="hand2")
        self.ring.pack(side="left")
        self.ring_img = self.ring.create_image(105, 105)
        self.ring_score = self.ring.create_text(105, 92, text="—", fill=TEXT, font=(FONT, 40, "bold"))
        self.ring.create_text(105, 132, text="ОЦЕНКА ПК", fill=MUTED, font=(FONT, 9, "bold"))
        self.ring.create_text(105, 152, text="нажми для буста", fill=DIM, font=(FONT, 8))
        self.ring.bind("<Button-1>", lambda e: self.optimize_all())
        self.ring.bind("<Enter>", lambda e: self._paint_ring(True))
        self.ring.bind("<Leave>", lambda e: self._paint_ring(False))
        self._paint_ring(False)

        right = tk.Frame(hi, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(28, 0))
        self.hero_title = label(right, "Выжми максимум FPS", 18, bold=True)
        self.hero_title.pack(anchor="w")
        label(right, "Точка восстановления, драйвер, Windows и все игры за один клик. "
                     "Каждое изменение в журнале и откатывается.", 10, MUTED, wraplength=560,
              justify="left").pack(anchor="w", pady=(2, 10))
        self.checks = {}
        grid = tk.Frame(right, bg=CARD)
        grid.pack(anchor="w")
        for i, (k, t) in enumerate((("sys", "Windows"), ("gpu", "Драйвер видеокарты"), ("games", "Игры"),
                                    ("timer", "Точный таймер"))):
            cell = tk.Frame(grid, bg=CARD)
            cell.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 36), pady=2)
            dot = label(cell, "●", 10, DIM)
            dot.pack(side="left")
            label(cell, t, 10, MUTED).pack(side="left", padx=(6, 6))
            val = label(cell, "—", 10, TEXT, True)
            val.pack(side="left")
            self.checks[k] = (dot, val)
        btns = tk.Frame(right, bg=CARD)
        btns.pack(anchor="w", pady=(16, 0))
        self.btn_all = Btn(btns, "⚡  BOOST: оптимизировать всё", self.optimize_all, "primary", 12, padx=26, pady=12)
        self.btn_all.pack(side="left")
        self.btn_undo = Btn(btns, "Откатить всё", self.undo, "danger", 10, padx=18, pady=12)
        self.btn_undo.pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Готов к работе")
        tk.Label(right, textvariable=self.status_var, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w").pack(
            fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(right, mode="indeterminate", length=420)
        self.progress_parent = right

        tiles = tk.Frame(body, bg=BG)
        tiles.pack(fill="x", pady=(16, 0))
        tiles.columnconfigure((0, 1, 2, 3), weight=1, uniform="t")
        self.tiles = {}
        for i, (k, t, color) in enumerate((("cpu", "ПРОЦЕССОР", ACCENT2), ("gpu", "ВИДЕОКАРТА", ACCENT),
                                           ("ram", "ПАМЯТЬ", OK), ("temp", "ТЕМПЕРАТУРА GPU", WARN))):
            c = Card(tiles, r=14)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            inner = tk.Frame(c, bg=CARD)
            inner.pack(fill="x", padx=16, pady=(14, 12))
            label(inner, t, 8, MUTED, True).pack(anchor="w")
            v = label(inner, "—", 20, bold=True)
            v.pack(anchor="w")
            sub = label(inner, "", 9, MUTED)
            sub.pack(anchor="w")
            sp = Spark(inner, 190, 38, color)
            sp.pack(anchor="w", pady=(6, 0))
            self.tiles[k] = (v, sub, sp)

        recent = sorted(self.games, key=lambda g: -self.playtime.get(g.appid, (0, 0))[1])[:5]
        if recent:
            label(body, "Недавно играли", 13, bold=True).pack(anchor="w", pady=(18, 8))
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x")
            for g in recent:
                img = ImageTk.PhotoImage(rounded(art.load_pil(self.root_dir, g.appid, g.name, HEADER, "header"),
                                                 10, BG))
                self.images.append(img)
                cell = tk.Frame(row, bg=BG, cursor="hand2")
                cell.pack(side="left", padx=(0, 12))
                pic = tk.Label(cell, image=img, bg=BG, cursor="hand2")
                pic.pack()
                mins = self.playtime.get(g.appid, (0, 0))[0]
                label(cell, g.name, 9, TEXT, True, wraplength=HEADER[0], justify="left").pack(anchor="w", pady=(4, 0))
                label(cell, library.fmt_hours(mins), 8, MUTED).pack(anchor="w")
                for w in (cell, pic):
                    w.bind("<Button-1>", lambda e, g=g: GameWindow(self, g))
        return f

    def _paint_ring(self, hover):
        img = ring_image(self.score, 210, hover)
        self.ring.itemconfigure(self.ring_img, image=img)

    def refresh_score(self):
        def work():
            st = system_tweaks.status()
            opt = sum(1 for g in self.games if games.is_optimized(g))
            gpu_done = any(e.get("kind") == "nvidia" or "4d36e968" in str(e.get("path", "")).lower()
                           for e in journal.load())
            self.after(0, lambda: self._apply_score(st, opt, gpu_done))

        threading.Thread(target=work, daemon=True).start()

    def _apply_score(self, st, opt, gpu_done):
        self.sys_status = st
        n_sys, n_games = sum(st.values()), len(self.games)
        frac_games = opt / n_games if n_games else 1
        self.score = round(10 + 45 * n_sys / max(1, len(st)) + 25 * gpu_done + 15 * frac_games
                           + 5 * bool(self.cfg.get("timer")))
        self.ring.itemconfigure(self.ring_score, text=str(self.score))
        self._paint_ring(False)
        self.hero_title.configure(text="ПК разогнан по максимуму" if self.score >= 95 else
                                  "Почти готово" if self.score >= 70 else "Выжми максимум FPS")
        vals = {"sys": (f"{n_sys}/{len(st)}", n_sys == len(st)),
                "gpu": ("настроен" if gpu_done else "не настроен", gpu_done),
                "games": (f"{opt}/{n_games}", opt == n_games),
                "timer": ("0,5 мс" if self.cfg.get("timer") else "выкл", bool(self.cfg.get("timer")))}
        for k, (text, good) in vals.items():
            dot, val = self.checks[k]
            dot.configure(fg=OK if good else WARN)
            val.configure(text=text)
        for k, (v, _) in self.sys_rows.items():
            on = st.get(k)
            v.configure(text="✓ включено" if on else "выключено", fg=OK if on else DIM)

    def tick(self):
        m, last = self.mon, sysmon.last
        cpu, ram = last(m.cpu), last(m.ram)
        t = self.tiles
        t["cpu"][0].configure(text=f"{cpu:.0f}%")
        t["cpu"][1].configure(text=f"{os.cpu_count()} потоков")
        t["cpu"][2].draw(m.cpu)
        t["ram"][0].configure(text=f"{m.ram_used:.1f} ГБ")
        t["ram"][1].configure(text=f"из {m.ram_total:.0f} ГБ · {ram:.0f}%")
        t["ram"][2].draw(m.ram)
        if m.has_gpu:
            t["gpu"][0].configure(text=f"{last(m.gpu):.0f}%")
            t["gpu"][1].configure(text=f"VRAM {m.vram_used:.1f} / {m.vram_total:.0f} ГБ")
            t["gpu"][2].draw(m.gpu)
            t["temp"][0].configure(text=f"{m.gpu_temp:.0f}°C",
                                   fg=OK if m.gpu_temp < 70 else WARN if m.gpu_temp < 83 else DANGER)
            t["temp"][1].configure(text="норма" if m.gpu_temp < 70 else "тепло" if m.gpu_temp < 83 else "горячо")
            t["temp"][2].draw(m.temp, 100)
            self.side_gpu.configure(text=f"GPU {last(m.gpu):.0f}%  ·  {m.gpu_temp:.0f}°C")
        else:
            for k in ("gpu", "temp"):
                t[k][1].configure(text="нужна NVIDIA (nvidia-smi)")
        self.side_cpu.configure(text=f"CPU {cpu:.0f}%  ·  RAM {ram:.0f}%")
        if hasattr(self, "ram_big"):
            self.ram_big.configure(text=f"{m.ram_used:.1f} / {m.ram_total:.0f} ГБ")
        self.after(1000, self.tick)

    # ---------- Игры ----------
    def _page_games(self):
        f = self.page("Библиотека", "Нажми на обложку: окно игры с фишками. ☆ добавляет в избранное")
        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", padx=32, pady=(0, 10))
        sbox = Card(bar, r=10, fill=CARD)
        sbox.pack(side="left")
        si = tk.Frame(sbox, bg=CARD)
        si.pack(padx=10, pady=6)
        label(si, "⌕", 12, MUTED).pack(side="left")
        self.search = tk.StringVar()
        e = tk.Entry(si, textvariable=self.search, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat",
                     font=(FONT, 11), width=26, bd=0)
        e.pack(side="left", padx=(6, 0), ipady=3)
        self.search.trace_add("write", lambda *a: self.layout_cards(force=True))

        seg = Card(bar, r=10, fill=CARD)
        seg.pack(side="left", padx=12)
        segi = tk.Frame(seg, bg=CARD)
        segi.pack(padx=4, pady=4)
        self.sort_btns = {}
        for key, text in (("recent", "Недавние"), ("name", "А–Я"), ("time", "Время"), ("size", "Размер")):
            b = tk.Label(segi, text=text, bg=CARD, fg=MUTED, font=(FONT, 9, "bold"), padx=12, pady=5,
                         cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, k=key: self.set_sort(k))
            self.sort_btns[key] = b
        self.fav_only = tk.BooleanVar(value=False)
        favrow = tk.Frame(bar, bg=BG)
        favrow.pack(side="left", padx=4)
        Toggle(favrow, self.fav_only, lambda: self.layout_cards(force=True)).pack(side="left")
        label(favrow, "Только избранное", 9, MUTED, True).pack(side="left", padx=8)
        self.count_lbl = label(bar, "", 9, DIM, True)
        self.count_lbl.pack(side="right")

        self.banner = tk.Label(f, bg="#33270f", fg=WARN, font=(FONT, 10), anchor="w", padx=16, pady=8,
                               text="Steam запущен: параметры запуска игр запишутся только после его закрытия")
        self.scroll = Scroll(f)
        self.scroll.pack(fill="both", expand=True, padx=(26, 12), pady=(0, 12))
        self.scroll.on_resize = lambda w: self.layout_cards(width=w)
        self.cards, self.cols, self.badges, self.stars = [], 0, {}, {}
        for g in self.games:
            self.cards.append(self._make_card(g))
        if not self.games:
            label(self.scroll.inner, "Steam или игры не найдены", 12, MUTED).pack(pady=40)
        self.set_sort(self.cfg.get("sort", "recent"), save=False)
        return f

    def set_sort(self, key, save=True):
        self.sort = key
        for k, b in self.sort_btns.items():
            b.configure(bg=CARD_HI if k == key else CARD, fg=TEXT if k == key else MUTED)
        if save:
            self.cfg["sort"] = key
            settings.save(self.cfg)
        self.layout_cards(force=True)

    def _check_steam_banner(self):
        if steam.is_steam_running():
            self.banner.pack(fill="x", padx=32, pady=(0, 8), before=self.scroll)
        else:
            self.banner.pack_forget()

    def _make_card(self, g):
        img = ImageTk.PhotoImage(rounded(art.load_pil(self.root_dir, g.appid, g.name, COVER), 10, CARD))
        self.images.append(img)
        card = Card(self.scroll.inner, r=14, fill=CARD, outline=LINE)
        cover = tk.Label(card, image=img, bg=CARD, cursor="hand2", bd=0)
        cover.pack(padx=12, pady=(12, 8))
        star = tk.Label(card, bg="#0d0f16", font=(FONT, 11), cursor="hand2", padx=4, pady=0)
        star.place(in_=cover, relx=1.0, x=-6, y=6, anchor="ne")
        star.bind("<Button-1>", lambda e: self.toggle_fav(g.appid))
        self.stars[g.appid] = star
        name = tk.Label(card, text=g.name, bg=CARD, fg=TEXT, font=(FONT, 10, "bold"), wraplength=150,
                        height=2, justify="center", cursor="hand2")
        name.pack(padx=8)
        mins = self.playtime.get(g.appid, (0, 0))[0]
        meta = label(card, f"{library.fmt_hours(mins)}  ·  {library.fmt_size(self.sizes.get(g.appid, 0))}", 8, MUTED)
        meta.pack()
        badge = tk.Label(card, bg=CARD, font=(FONT, 8, "bold"))
        badge.pack(pady=(2, 6))
        self.badges[g.appid] = badge
        row = tk.Frame(card, bg=CARD)
        row.pack(pady=(0, 14))
        Btn(row, "▶  Играть", lambda: self.play(g), "primary", 9, padx=14, pady=6).pack(side="left")
        Btn(row, "⚡", lambda: self.run_task(lambda: games.optimize(g, self.root_dir)),
            "ghost", 10, padx=11, pady=5).pack(side="left", padx=(6, 0))
        for w in (cover, name):
            w.bind("<Button-1>", lambda e: GameWindow(self, g))
        for w in (card, cover, name, badge, meta, row):
            w.bind("<Enter>", lambda e, c=card: c.set_outline(ACCENT), add="+")
            w.bind("<Leave>", lambda e, c=card: self._unhover(c), add="+")
        self._refresh_badge(g)
        self._paint_star(g.appid)
        return card, g

    @staticmethod
    def _inside(widget) -> bool:
        """Leave приходит и при переходе мыши на дочерний виджет: проверяем, где курсор на самом деле."""
        x, y = widget.winfo_pointerxy()
        w = widget.winfo_containing(x, y)
        while w is not None and w is not widget:
            w = w.master
        return w is widget

    def _unhover(self, card):
        if not self._inside(card):
            card.set_outline(LINE)

    def _paint_star(self, appid):
        on = appid in self.cfg["favorites"]
        self.stars[appid].configure(text="★" if on else "☆", fg=WARN if on else "#c9cfdd")

    def toggle_fav(self, appid) -> bool:
        favs = self.cfg["favorites"]
        on = appid not in favs
        if on:
            favs.append(appid)
        else:
            favs.remove(appid)
        settings.save(self.cfg)
        if appid in self.stars:
            self._paint_star(appid)
        self.layout_cards(force=True)
        return on

    def _refresh_badge(self, g):
        done = games.is_optimized(g)
        self.badges[g.appid].configure(text="✓ ОПТИМИЗИРОВАНО" if done else "НЕ ОПТИМИЗИРОВАНО",
                                       fg=OK if done else DIM)

    def _sorted(self):
        pt, favs = self.playtime, set(self.cfg["favorites"])
        keyf = {"recent": lambda c: -pt.get(c[1].appid, (0, 0))[1],
                "name": lambda c: c[1].name.lower(),
                "time": lambda c: -pt.get(c[1].appid, (0, 0))[0],
                "size": lambda c: -self.sizes.get(c[1].appid, 0)}[getattr(self, "sort", "recent")]
        return sorted(self.cards, key=lambda c: (c[1].appid not in favs, keyf(c)))

    def layout_cards(self, width=None, force=False):
        if not hasattr(self, "scroll"):
            return
        width = width or self.scroll.canvas.winfo_width()
        cols = max(1, width // CARD_W)
        if cols == self.cols and not force:
            return
        self.cols = cols
        self.scroll.canvas.yview_moveto(0)
        q = self.search.get().strip().lower()
        favs = set(self.cfg["favorites"])
        shown = 0
        for card, g in self._sorted():
            card.grid_forget()
            if q in g.name.lower() and (not self.fav_only.get() or g.appid in favs):
                card.grid(row=shown // cols, column=shown % cols, padx=6, pady=6, sticky="n")
                shown += 1
        self.count_lbl.configure(text=f"{shown} из {len(self.games)}")

    def play(self, g):
        if self.cfg.get("autoboost"):
            exes = [e for e in self.cfg.get("close_list", []) if e]

            def work():
                ctx.log(f"Игровой буст перед {g.name}:")
                if exes:
                    boost.close_programs([e for e, _, _ in boost.background_running() if e in exes])
                mb = boost.clean_ram()
                ctx.log(f"  память: освобождено {mb:.0f} МБ")

            self.run_task(work, lambda: (os.startfile(f"steam://rungameid/{g.appid}"),
                                         toast(self, f"Буст готов, запускаю {g.name}")))
        else:
            os.startfile(f"steam://rungameid/{g.appid}")
            toast(self, f"Запускаю {g.name}")

    # ---------- Буст ----------
    def _page_boost(self):
        f = self.page("Буст", "Освободить ресурсы прямо перед игрой")
        sc = Scroll(f)
        sc.pack(fill="both", expand=True, padx=(0, 12))
        body = tk.Frame(sc.inner, bg=BG)
        body.pack(fill="x", padx=32)
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        top.columnconfigure((0, 1), weight=1, uniform="b")

        ram = Card(top, r=16)
        ram.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ri = tk.Frame(ram, bg=CARD)
        ri.pack(fill="both", expand=True, padx=20, pady=18)
        label(ri, "🧹  Очистка памяти", 13, bold=True).pack(anchor="w")
        label(ri, "Сжимает память фоновых процессов и чистит кэш standby (как ISLC). Помогает от "
                  "фризов, когда ОЗУ мало.", 9, MUTED, wraplength=380, justify="left").pack(anchor="w", pady=(2, 10))
        self.ram_big = label(ri, "—", 22, bold=True)
        self.ram_big.pack(anchor="w")
        label(ri, "занято сейчас", 9, MUTED).pack(anchor="w", pady=(0, 12))
        Btn(ri, "🧹  Очистить память", self.do_clean_ram, "primary", 10).pack(anchor="w")

        tm = Card(top, r=16)
        tm.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ti = tk.Frame(tm, bg=CARD)
        ti.pack(fill="both", expand=True, padx=20, pady=18)
        label(ti, "⏱  Точный таймер 0,5 мс", 13, bold=True).pack(anchor="w")
        label(ti, "Windows по умолчанию «тикает» раз в 15,6 мс. Пока открыта программа, таймер 0,5 мс: "
                  "ровнее кадры и меньше задержка ввода. Закрыл программу: всё как было.", 9, MUTED,
              wraplength=380, justify="left").pack(anchor="w", pady=(2, 12))
        self.timer_var = tk.BooleanVar(value=bool(self.cfg.get("timer")))
        toggle_row(ti, self.timer_var, "Включить точный таймер", command=self.apply_timer)
        self.autoboost_var = tk.BooleanVar(value=bool(self.cfg.get("autoboost")))
        toggle_row(ti, self.autoboost_var, "Авто-буст при «Играть»",
                   "Перед запуском игры чистить память и закрывать отмеченные программы",
                   command=self.save_autoboost, wrap=330)

        bgc = Card(body, r=16)
        bgc.pack(fill="x", pady=(16, 0))
        bi = tk.Frame(bgc, bg=CARD)
        bi.pack(fill="x", padx=20, pady=18)
        head = tk.Frame(bi, bg=CARD)
        head.pack(fill="x")
        label(head, "🗂  Фоновые программы", 13, bold=True).pack(side="left")
        Btn(head, "Обновить", self.refresh_bg, "ghost", 9, padx=12, pady=5).pack(side="right")
        label(bi, "Браузеры, лаунчеры и облака едят память и диск во время игры. Отметь, что закрывать. "
                  "Отмеченное запоминается для авто-буста.", 9, MUTED, wraplength=820,
              justify="left").pack(anchor="w", pady=(2, 8))
        self.bg_list = tk.Frame(bi, bg=CARD)
        self.bg_list.pack(fill="x")
        self.bg_vars = {}
        Btn(bi, "Закрыть отмеченные", self.close_bg, "danger", 10).pack(anchor="w", pady=(12, 0))
        return f

    def refresh_bg(self):
        def work():
            items = boost.background_running()
            self.after(0, lambda: self._fill_bg(items))

        threading.Thread(target=work, daemon=True).start()

    def _fill_bg(self, items):
        for w in self.bg_list.winfo_children():
            w.destroy()
        keep = set(self.cfg.get("close_list", []))
        self.bg_vars = {}
        if not items:
            label(self.bg_list, "Ничего лишнего не запущено 👍", 10, OK).pack(anchor="w", pady=4)
            return
        for exe, title, mb in items:
            v = tk.BooleanVar(value=exe in keep)
            self.bg_vars[exe] = v
            toggle_row(self.bg_list, v, title, exe, (f"{mb:.0f} МБ", WARN if mb > 500 else MUTED),
                       command=self.save_close_list)

    def save_close_list(self):
        keep = set(self.cfg.get("close_list", []))
        for exe, v in self.bg_vars.items():
            (keep.add if v.get() else keep.discard)(exe)
        self.cfg["close_list"] = sorted(keep)
        settings.save(self.cfg)

    def close_bg(self):
        exes = [e for e, v in self.bg_vars.items() if v.get()]
        if not exes:
            toast(self, "Отметь программы, которые закрыть", "warn")
            return
        self.run_task(lambda: boost.close_programs(exes),
                      lambda: (self.after(800, self.refresh_bg), toast(self, f"Закрыто программ: {len(exes)}")))

    def do_clean_ram(self):
        res = {}

        def work():
            ctx.log("Очистка памяти:")
            res["mb"] = boost.clean_ram()
            ctx.log(f"  освобождено {res['mb']:.0f} МБ")

        self.run_task(work, lambda: toast(self, f"Освобождено {res.get('mb', 0) / 1024:.1f} ГБ памяти"))

    def apply_timer(self):
        on = self.timer_var.get() if hasattr(self, "timer_var") else bool(self.cfg.get("timer"))
        try:
            ms = boost.set_timer(on)
            if on:
                toast(self, f"Таймер Windows: {ms:.1f} мс")
        except Exception as e:
            toast(self, f"Таймер не включён: {e}", "err")
            on = False
        self.cfg["timer"] = on
        settings.save(self.cfg)
        self.refresh_score()

    def save_autoboost(self):
        self.cfg["autoboost"] = self.autoboost_var.get()
        settings.save(self.cfg)

    # ---------- Оверлей ----------
    def _page_overlay(self):
        f = self.page("Оверлей", "Свой прицел и монитор железа поверх игры. Работает в режиме «окно без рамки»")
        body = tk.Frame(f, bg=BG)
        body.pack(fill="x", padx=32)
        body.columnconfigure(0, weight=3, uniform="o")
        body.columnconfigure(1, weight=2, uniform="o")
        ch = self.cfg["crosshair"]

        cc = Card(body, r=16)
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ci = tk.Frame(cc, bg=CARD)
        ci.pack(fill="both", expand=True, padx=20, pady=18)
        head = tk.Frame(ci, bg=CARD)
        head.pack(fill="x")
        label(head, "⌖  Прицел", 13, bold=True).pack(side="left")
        label(head, overlay.HOTKEYS["crosshair"][0], 9, ACCENT2, True).pack(side="right")
        self.ch_on = tk.BooleanVar(value=bool(ch.get("enabled")))
        toggle_row(ci, self.ch_on, "Показывать прицел поверх игры",
                   "Для игр без своего прицела и снайперок без скоупа", command=self.apply_crosshair, wrap=380)

        split = tk.Frame(ci, bg=CARD)
        split.pack(fill="x", pady=(8, 0))
        prev_bg = ImageTk.PhotoImage(rounded(gradient((200, 200), "#2d3b4f", "#141a24"), 12, CARD))
        self.images.append(prev_bg)
        self.preview = tk.Canvas(split, width=200, height=200, bg=CARD, highlightthickness=0)
        self.preview.create_image(0, 0, image=prev_bg, anchor="nw")
        self.preview.pack(side="left")
        ctl = tk.Frame(split, bg=CARD)
        ctl.pack(side="left", fill="x", expand=True, padx=(18, 0))
        self.ch_style = tk.StringVar(value=ch["style"])
        label(ctl, "Форма", 9, MUTED, True).pack(anchor="w")
        cb = ttk.Combobox(ctl, textvariable=self.ch_style, values=overlay.STYLES, state="readonly", width=22)
        cb.pack(anchor="w", pady=(2, 8))
        cb.bind("<<ComboboxSelected>>", lambda e: self.update_crosshair())
        label(ctl, "Цвет", 9, MUTED, True).pack(anchor="w")
        sw = tk.Frame(ctl, bg=CARD)
        sw.pack(anchor="w", pady=(2, 8))
        self.ch_color = ch["color"]
        self.swatches = {}
        for name, col in overlay.COLORS.items():
            s = tk.Label(sw, bg=col, width=2, height=1, cursor="hand2", highlightthickness=2,
                         highlightbackground=CARD)
            s.pack(side="left", padx=(0, 6))
            s.bind("<Button-1>", lambda e, c=col: self.set_ch_color(c))
            self.swatches[col] = s
        self.ch_vars = {}
        for key, title, lo, hi in (("size", "Длина", 2, 30), ("thick", "Толщина", 1, 6), ("gap", "Зазор", 0, 15)):
            row = tk.Frame(ctl, bg=CARD)
            row.pack(fill="x")
            label(row, title, 9, MUTED, True, width=8, anchor="w").pack(side="left")
            v = tk.IntVar(value=int(ch[key]))
            self.ch_vars[key] = v
            val = label(row, str(v.get()), 9, TEXT, True, width=3)

            def moved(x, val=val):
                val.configure(text=str(x))
                self.update_crosshair()

            Slider(row, v, lo, hi, 170, moved).pack(side="left", pady=4)
            val.pack(side="left", padx=(8, 0))
        self.ch_outline = tk.BooleanVar(value=bool(ch.get("outline")))
        toggle_row(ctl, self.ch_outline, "Чёрная обводка", command=self.update_crosshair)

        mc = Card(body, r=16)
        mc.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        mi = tk.Frame(mc, bg=CARD)
        mi.pack(fill="both", expand=True, padx=20, pady=18)
        head = tk.Frame(mi, bg=CARD)
        head.pack(fill="x")
        label(head, "📈  Монитор", 13, bold=True).pack(side="left")
        label(head, overlay.HOTKEYS["monitor"][0], 9, ACCENT2, True).pack(side="right")
        self.mo_on = tk.BooleanVar(value=bool(self.cfg["monitor"].get("enabled")))
        toggle_row(mi, self.mo_on, "Показывать поверх игры", "Загрузка CPU и GPU, температура, память",
                   command=self.apply_monitor, wrap=230)
        label(mi, "Угол экрана", 9, MUTED, True).pack(anchor="w", pady=(10, 2))
        self.mo_corner = tk.StringVar(value=self.cfg["monitor"]["corner"])
        cb = ttk.Combobox(mi, textvariable=self.mo_corner, values=overlay.CORNERS, state="readonly", width=22)
        cb.pack(anchor="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_monitor())
        demo = tk.Frame(mi, bg="#06070b")
        demo.pack(fill="x", pady=(16, 0))
        self.mo_demo = tk.Label(demo, text="", bg="#06070b", fg="#7CFFB2", font=("Consolas", 10, "bold"),
                                anchor="w", padx=10, pady=8)
        self.mo_demo.pack(fill="x")
        label(mi, "Горячие клавиши работают и внутри игры. В эксклюзивном полноэкранном режиме Windows "
                  "не даёт рисовать поверх игры: включи «окно без рамки» в настройках игры или в фишках.",
              9, MUTED, wraplength=320, justify="left").pack(anchor="w", pady=(14, 0))
        self.update_crosshair(save=False)
        self._demo_tick()
        return f

    def _demo_tick(self):
        self.mo_demo.configure(text=self.monitor_ov.text() if hasattr(self, "monitor_ov") else "")
        self.after(1000, self._demo_tick)

    def _ch_cfg(self):
        return {"style": self.ch_style.get(), "color": self.ch_color, "outline": self.ch_outline.get(),
                "enabled": self.ch_on.get(), **{k: v.get() for k, v in self.ch_vars.items()}}

    def set_ch_color(self, col):
        self.ch_color = col
        self.update_crosshair()

    def update_crosshair(self, save=True):
        cfg = self._ch_cfg()
        for col, s in self.swatches.items():
            s.configure(highlightbackground="#ffffff" if col == self.ch_color else CARD)
        overlay.draw(self.preview, cfg, 100)
        if hasattr(self, "crosshair") and self.crosshair.visible:
            self.crosshair.show(cfg)
        if save:
            self.cfg["crosshair"] = cfg
            settings.save(self.cfg)

    def apply_crosshair(self):
        cfg = self._ch_cfg()
        if cfg["enabled"]:
            self.crosshair.show(cfg)
        else:
            self.crosshair.hide()
        self.cfg["crosshair"] = cfg
        settings.save(self.cfg)

    def apply_monitor(self):
        on, corner = self.mo_on.get(), self.mo_corner.get()
        if on:
            self.monitor_ov.show(corner)
        else:
            self.monitor_ov.hide()
        self.cfg["monitor"] = {"enabled": on, "corner": corner}
        settings.save(self.cfg)

    # ---------- Видеокарта ----------
    def _checklist(self, parent, settings_list, store):
        box = Card(parent, r=16)
        box.pack(fill="x", padx=32)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(fill="x", padx=20, pady=14)
        for st in settings_list:
            v = tk.BooleanVar(value=True)
            store[st.key] = v
            toggle_row(inner, v, st.title, st.desc)

    def _page_gpu(self):
        g = self.gpus[0] if self.gpus else None
        vendor = g.vendor if g else "other"
        f = self.page("Видеокарта", (g.name + "  ·  драйвер " + g.driver) if g else "Видеокарта не определена")
        sc = Scroll(f)
        sc.pack(fill="both", expand=True, padx=(0, 12))
        body = sc.inner
        self.gpu_vars = {}
        if vendor == "nvidia":
            label(body, "Панель управления NVIDIA  ›  Управление параметрами 3D  ›  Глобальные параметры",
                  10, MUTED).pack(anchor="w", padx=32, pady=(0, 8))
            self._checklist(body, gpu.NVIDIA, self.gpu_vars)
            note = ("Применяется через NVIDIA Profile Inspector (скачивается с GitHub при первом запуске). "
                    "Откат возвращает значения драйвера по умолчанию.")
            panel = ("Открыть панель NVIDIA", gpu.open_nvidia_panel)
        elif vendor == "amd":
            label(body, "AMD Software: Adrenalin Edition  ›  Игры  ›  Графика (глобально)",
                  10, MUTED).pack(anchor="w", padx=32, pady=(0, 8))
            self._checklist(body, gpu.AMD, self.gpu_vars)
            note = ("Пишется в настройки драйвера в реестре, нужна перезагрузка. Экспериментально: "
                    "Adrenalin может перезаписать значения своими.")
            panel = ("Открыть AMD Adrenalin", gpu.open_amd_panel)
        else:
            label(body, "Для этой видеокарты настройка драйвера не поддерживается. Системные и игровые "
                        "оптимизации работают.", 11, MUTED, wraplength=700, justify="left").pack(anchor="w", padx=32)
            return f
        label(body, note, 9, WARN, wraplength=820, justify="left").pack(anchor="w", padx=32, pady=(10, 0))
        btns = tk.Frame(body, bg=BG)
        btns.pack(anchor="w", padx=32, pady=16)
        Btn(btns, "⚡  Применить", self.apply_gpu, "primary", 11, padx=22, pady=10).pack(side="left")
        Btn(btns, panel[0], panel[1], "ghost", 10, pady=10).pack(side="left", padx=8)
        return f

    def apply_gpu(self):
        keys = {k for k, v in self.gpu_vars.items() if v.get()}
        g = self.gpus[0]
        self.run_task(lambda: core.run(set(), [], g, False, keys))
        self.show("log")

    # ---------- Система ----------
    def _page_system(self):
        f = self.page("Система", "Что именно будет изменено в Windows. Справа: что уже включено")
        sc = Scroll(f)
        sc.pack(fill="both", expand=True, padx=(0, 12))
        box = Card(sc.inner, r=16)
        box.pack(fill="x", padx=32)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(fill="x", padx=20, pady=14)
        items = [(t.id, t.title, t.desc, t.revertible) for t in system_tweaks.TWEAKS]
        items += [("_gpu", "Драйвер видеокарты (NVIDIA / AMD)", "Максимальная производительность, V-Sync выкл", True),
                  ("_rp", "Создать точку восстановления", "Рекомендуется перед первым запуском", True)]
        self.sys_rows = {}
        for key, title, desc, rev in items:
            v = tk.BooleanVar(value=rev)
            self.tweak_vars[key] = v
            row = toggle_row(inner, v, title, desc + ("" if rev else "  (необратимо, по умолчанию выключено)"))
            if key in system_tweaks.CHECKS:
                st = label(row, "—", 9, DIM, True)
                st.pack(side="right")
                self.sys_rows[key] = (st, None)
        Btn(sc.inner, "Применить выбранное", self.apply_system, "primary", 11, padx=22, pady=10).pack(
            anchor="w", padx=32, pady=18)
        return f

    # ---------- Журнал ----------
    def _page_log(self):
        f = self.page("Журнал", "Что делала программа. Все изменения откатываются одной кнопкой")
        Btn(f, "Откатить всё", self.undo, "danger", 10).pack(anchor="w", padx=32, pady=(0, 12))
        box = Card(f, r=16)
        box.pack(fill="both", expand=True, padx=32, pady=(0, 24))
        self.log = tk.Text(box, bg=CARD, fg=TEXT, relief="flat", font=("Consolas", 10), wrap="word",
                           state="disabled", padx=8, pady=8, insertbackground=TEXT, bd=0, highlightthickness=0)
        self.log.pack(fill="both", expand=True, padx=12, pady=12)
        return f

    # ---------- действия ----------
    def pump(self):
        while not self.q.empty():
            msg = self.q.get()
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
            if msg.strip():
                self.status_var.set(msg.strip()[:110])
        self.after(100, self.pump)

    def run_task(self, fn, done=None):
        if self.busy:
            toast(self, "Подожди, предыдущая задача ещё выполняется", "warn")
            return
        self.busy = True
        self.topbar.place(x=0, y=0, relwidth=1)
        self.topbar.start(10)
        self.progress.pack(anchor="w", pady=(8, 0))
        self.progress.start(12)
        self.btn_all.set_enabled(False)
        self.btn_undo.set_enabled(False)

        def work():
            try:
                fn()
            except steam.SteamRunning as e:
                self.q.put(f"! {e}")
            except Exception as e:
                self.q.put(f"Ошибка: {e}")
            finally:
                self.after(0, lambda: self._finish(done))

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, done):
        self.busy = False
        self.topbar.stop()
        self.topbar.place_forget()
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_all.set_enabled(True)
        self.btn_undo.set_enabled(True)
        for g in self.games:
            self._refresh_badge(g)
        self.refresh_score()
        if done:
            done()

    def optimize_all(self):
        ids = {t.id for t in system_tweaks.TWEAKS if t.revertible}
        gp = self.gpus[0] if self.gpus else None
        self.run_task(lambda: core.run(ids, self.games, gp, True),
                      lambda: toast(self, "Буст завершён. Перезагрузи ПК, чтобы применилось всё"))

    def apply_system(self):
        ids = {k for k, v in self.tweak_vars.items() if v.get() and not k.startswith("_")}
        gp = self.gpus[0] if self.gpus and self.tweak_vars["_gpu"].get() else None
        rp = self.tweak_vars["_rp"].get()
        self.run_task(lambda: core.run(ids, [], gp, rp))
        self.show("log")

    def undo(self):
        self.run_task(core.undo, lambda: toast(self, "Все изменения откачены"))


def main():
    App().mainloop()
