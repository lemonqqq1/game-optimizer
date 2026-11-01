"""Окно программы: тёмная тема, боковое меню, карточки игр, окно каждой игры."""
import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from . import __version__, art, core, ctx, games, gpu, journal, steam, system_tweaks

BG, SIDE, CARD, CARD_HI = "#0e1117", "#141923", "#1a2030", "#232b40"
ACCENT, ACCENT_HI = "#3d7bff", "#5b91ff"
TEXT, MUTED, OK, WARN, DANGER = "#e8ecf4", "#8a93a8", "#34d399", "#f5a524", "#ef5b5b"
FONT = "Segoe UI"
COVER = (150, 225)
CARD_W = 184


def dark_titlebar(win):
    try:
        win.update()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
    except Exception:
        pass


class Btn(tk.Label):
    """Плоская кнопка с наведением."""
    KINDS = {"primary": (ACCENT, ACCENT_HI, "#ffffff"), "ghost": (CARD_HI, "#2d3752", TEXT),
             "danger": ("#3a2227", "#52292f", "#ff9a9a"), "ok": ("#16382e", "#1d4a3c", OK)}

    def __init__(self, parent, text, command, kind="primary", size=10, **kw):
        self.bg, self.hi, fg = self.KINDS[kind]
        super().__init__(parent, text=text, bg=self.bg, fg=fg, font=(FONT, size, "bold"),
                         padx=kw.pop("padx", 14), pady=kw.pop("pady", 7), cursor="hand2", **kw)
        self.command, self.enabled = command, True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=self.hi))
        self.bind("<Leave>", lambda e: self.configure(bg=self.bg))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())

    def set_enabled(self, v: bool):
        self.enabled = v
        self.configure(cursor="hand2" if v else "arrow", bg=self.bg if v else "#2a2f3d",
                       fg=self["fg"] if v else "#6a7185")


class Scroll(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
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
        self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")

    def _resize(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        if self.on_resize:
            self.on_resize(e.width)


def label(parent, text, size=10, color=TEXT, bold=False, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", parent["bg"]), fg=color,
                    font=(FONT, size, "bold" if bold else "normal"), **kw)


class GameWindow(tk.Toplevel):
    """Отдельное окно игры: обложка, что будет изменено, кнопки «Играть» и «Оптимизировать»."""

    def __init__(self, app, game):
        super().__init__(app, bg=BG)
        self.app, self.game = app, game
        self.title(game.name)
        self.geometry("780x500")
        self.resizable(False, False)
        self.profile = games.PROFILES.get(game.appid)
        self.exe = games.find_exe(game, self.profile)
        dark_titlebar(self)

        self.cover = art.load(app.root_dir, game.appid, game.name, (240, 360))
        tk.Label(self, image=self.cover, bg=BG).pack(side="left", padx=20, pady=20, anchor="n")

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 20), pady=20)
        label(right, game.name, 18, bold=True, wraplength=440, justify="left").pack(anchor="w")
        self.badge = label(right, "", 10, bold=True)
        self.badge.pack(anchor="w", pady=(4, 10))

        info = tk.Frame(right, bg=CARD)
        info.pack(fill="x")
        for k, v in (("Steam AppID", game.appid), ("Папка", str(game.path)),
                     ("Запускаемый файл", self.exe.name if self.exe else "не найден")):
            row = tk.Frame(info, bg=CARD)
            row.pack(fill="x", padx=12, pady=3)
            label(row, k, 9, MUTED, bg=CARD, width=16, anchor="w").pack(side="left")
            label(row, v, 9, bg=CARD, wraplength=290, justify="left", anchor="w").pack(side="left")

        label(right, "Что будет сделано", 11, bold=True).pack(anchor="w", pady=(14, 4))
        for line in self.plan():
            label(right, "•  " + line, 9, MUTED, wraplength=440, justify="left").pack(anchor="w")

        self.status = label(right, "", 9, WARN, wraplength=440, justify="left")
        self.status.pack(anchor="w", pady=(10, 0))

        btns = tk.Frame(right, bg=BG)
        btns.pack(side="bottom", fill="x")
        Btn(btns, "▶  Играть", self.play, "ok", 11, padx=22, pady=10).pack(side="left")
        self.opt_btn = Btn(btns, "⚡  Оптимизировать", self.optimize, "primary", 11, padx=22, pady=10)
        self.opt_btn.pack(side="left", padx=8)
        Btn(btns, "Папка", lambda: os.startfile(game.path), "ghost", 10, pady=10).pack(side="left")
        self.refresh()

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
            items.append("Отдельного профиля у игры нет: применяются только общие настройки")
        return items

    def refresh(self):
        done = games.is_optimized(self.game)
        self.badge.configure(text="✓ Оптимизировано" if done else "Не оптимизировано",
                             fg=OK if done else MUTED)

    def play(self):
        os.startfile(f"steam://rungameid/{self.game.appid}")
        self.status.configure(text="Запускаю через Steam...", fg=OK)

    def optimize(self):
        if self.profile and self.profile.launch and steam.is_steam_running():
            self.status.configure(text="Steam открыт: параметры запуска не запишутся. Закрой Steam и повтори, "
                                       "остальные настройки применятся сейчас.", fg=WARN)
        else:
            self.status.configure(text="Применяю...", fg=MUTED)
        self.app.run_task(lambda: games.optimize(self.game, self.app.root_dir), self.after_optimize)

    def after_optimize(self):
        if self.winfo_exists():
            self.refresh()
            self.status.configure(text="Готово. Всё можно откатить на вкладке «Журнал».", fg=OK)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Game Optimizer {__version__}")
        self.geometry("1120x740")
        self.minsize(940, 620)
        self.configure(bg=BG)
        self.icon = ImageTk.PhotoImage(art.app_icon(64))
        self.iconphoto(True, self.icon)
        self.q: queue.Queue = queue.Queue()
        ctx.set_logger(self.q.put)
        self.busy = False
        self.images = []
        self.tweak_vars = {}

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Vertical.TScrollbar", background=CARD_HI, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=CARD_HI, darkcolor=CARD_HI)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD,
                        bordercolor=CARD, lightcolor=ACCENT, darkcolor=ACCENT)

        self.gpus = gpu.detect()
        self.root_dir = steam.steam_root()
        self.games = steam.installed_games(self.root_dir) if self.root_dir else []

        self._build_sidebar()
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)
        self.pages = {
            "home": self._page_home(), "games": self._page_games(),
            "gpu": self._page_gpu(), "system": self._page_system(), "log": self._page_log(),
        }
        self.show("home")
        dark_titlebar(self)
        self.after(100, self.pump)

    # ---------- каркас ----------
    def _build_sidebar(self):
        side = tk.Frame(self, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        label(side, "GAME", 17, ACCENT, True).pack(anchor="w", padx=22, pady=(24, 0))
        label(side, "OPTIMIZER", 17, TEXT, True).pack(anchor="w", padx=22, pady=(0, 24))
        self.nav = {}
        for key, text in (("home", "🏠  Главная"), ("games", "🎮  Игры"),
                          ("gpu", "🖥  Видеокарта"), ("system", "⚙  Система"), ("log", "📜  Журнал")):
            b = tk.Label(side, text=text, bg=SIDE, fg=MUTED, font=(FONT, 11, "bold"),
                         anchor="w", padx=22, pady=11, cursor="hand2")
            b.pack(fill="x")
            b.bind("<Button-1>", lambda e, k=key: self.show(k))
            b.bind("<Enter>", lambda e, k=key: self.nav[k].configure(bg=CARD) if k != self.current else None)
            b.bind("<Leave>", lambda e, k=key: self.nav[k].configure(bg=SIDE) if k != self.current else None)
            self.nav[key] = b
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        label(side, f"v{__version__}", 9, MUTED).pack(side="bottom", anchor="w", padx=22, pady=(0, 18))
        label(side, "● Администратор" if admin else "● Нет прав админа", 9,
              OK if admin else WARN).pack(side="bottom", anchor="w", padx=22)
        self.current = None

    def show(self, key):
        for k, p in self.pages.items():
            p.pack_forget()
            self.nav[k].configure(bg=SIDE, fg=MUTED)
        self.pages[key].pack(fill="both", expand=True)
        self.nav[key].configure(bg=CARD_HI, fg=TEXT)
        self.current = key
        if key == "games":
            self._check_steam_banner()
        if key == "home":
            self.refresh_stats()

    def page(self, title, subtitle=""):
        f = tk.Frame(self.content, bg=BG)
        label(f, title, 22, bold=True).pack(anchor="w", padx=32, pady=(26, 0))
        if subtitle:
            label(f, subtitle, 10, MUTED).pack(anchor="w", padx=32, pady=(2, 14))
        return f

    # ---------- Главная ----------
    def _page_home(self):
        f = self.page("Главная", "Один клик: драйвер видеокарты, система и все игры Steam")
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=32)
        row.columnconfigure((0, 1, 2), weight=1, uniform="c")
        g = self.gpus[0] if self.gpus else None
        vendor = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}.get(g.vendor if g else "", "")
        self.stat_vars = {}
        for i, (key, title, val, sub) in enumerate((
                ("gpu", "ВИДЕОКАРТА", g.name if g else "не определена",
                 f"{vendor}  ·  драйвер {g.driver}" if g else ""),
                ("games", "ИГРЫ STEAM", str(len(self.games)), "найдено в библиотеках"),
                ("changes", "ИЗМЕНЕНИЙ ПРИМЕНЕНО", "0", "можно откатить"))):
            c = tk.Frame(row, bg=CARD)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            label(c, title, 8, MUTED, True).pack(anchor="w", padx=16, pady=(14, 2))
            v = tk.StringVar(value=val)
            self.stat_vars[key] = v
            tk.Label(c, textvariable=v, bg=CARD, fg=TEXT, font=(FONT, 15, "bold"),
                     wraplength=270, justify="left").pack(anchor="w", padx=16)
            label(c, sub, 9, MUTED).pack(anchor="w", padx=16, pady=(2, 14))

        hero = tk.Frame(f, bg=CARD)
        hero.pack(fill="x", padx=32, pady=22)
        label(hero, "Выжать максимум FPS", 16, bold=True).pack(anchor="w", padx=24, pady=(22, 2))
        label(hero, "Перед началом создаётся точка восстановления Windows. Каждое изменение записывается "
                    "в журнал, поэтому всё откатывается одной кнопкой.", 10, MUTED, wraplength=760,
              justify="left").pack(anchor="w", padx=24)
        btns = tk.Frame(hero, bg=CARD)
        btns.pack(anchor="w", padx=24, pady=18)
        self.btn_all = Btn(btns, "⚡  Оптимизировать всё", self.optimize_all, "primary", 13, padx=30, pady=13)
        self.btn_all.pack(side="left")
        self.btn_undo = Btn(btns, "Откатить всё", self.undo, "danger", 11, padx=20, pady=13)
        self.btn_undo.pack(side="left", padx=10)
        self.progress = ttk.Progressbar(hero, mode="indeterminate", length=400)
        self.status_var = tk.StringVar(value="Готов к работе")
        tk.Label(hero, textvariable=self.status_var, bg=CARD, fg=MUTED, font=(FONT, 9),
                 anchor="w").pack(fill="x", padx=24, pady=(0, 6))
        tk.Frame(hero, bg=CARD, height=14).pack()
        self.progress_parent = hero
        return f

    def refresh_stats(self):
        self.stat_vars["changes"].set(str(len(journal.load())))

    # ---------- Игры ----------
    def _page_games(self):
        f = self.page("Игры", "Нажми на обложку, чтобы открыть окно игры")
        top = tk.Frame(f, bg=BG)
        top.pack(fill="x", padx=32, pady=(0, 8))
        self.search = tk.StringVar()
        e = tk.Entry(top, textvariable=self.search, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat",
                     font=(FONT, 11), width=30)
        e.pack(side="left", ipady=7, ipadx=8)
        self.search.trace_add("write", lambda *a: self.layout_cards(force=True))
        label(top, "поиск по названию", 9, MUTED).pack(side="left", padx=10)
        self.banner = tk.Label(f, bg="#3a2e12", fg=WARN, font=(FONT, 10), anchor="w", padx=16, pady=8,
                               text="Steam запущен: параметры запуска игр запишутся только после его закрытия")
        self.scroll = Scroll(f)
        self.scroll.pack(fill="both", expand=True, padx=(32, 18), pady=(0, 12))
        self.scroll.on_resize = lambda w: self.layout_cards(width=w)
        self.cards, self.cols, self.badges = [], 0, {}
        for g in self.games:
            self.cards.append(self._make_card(g))
        if not self.games:
            label(self.scroll.inner, "Steam или игры не найдены", 12, MUTED).pack(pady=40)
        return f

    def _check_steam_banner(self):
        if steam.is_steam_running():
            self.banner.pack(fill="x", padx=32, pady=(0, 8), before=self.scroll)
        else:
            self.banner.pack_forget()

    def _make_card(self, g):
        img = art.load(self.root_dir, g.appid, g.name, COVER)
        self.images.append(img)
        card = tk.Frame(self.scroll.inner, bg=CARD, width=CARD_W - 12)
        cover = tk.Label(card, image=img, bg=CARD, cursor="hand2")
        cover.pack(padx=12, pady=(12, 8))
        name = tk.Label(card, text=g.name, bg=CARD, fg=TEXT, font=(FONT, 10, "bold"), wraplength=150,
                        height=2, justify="center", cursor="hand2")
        name.pack(padx=8)
        badge = tk.Label(card, bg=CARD, font=(FONT, 8, "bold"))
        badge.pack(pady=(0, 6))
        self.badges[g.appid] = badge
        row = tk.Frame(card, bg=CARD)
        row.pack(pady=(0, 12))
        Btn(row, "▶", lambda: os.startfile(f"steam://rungameid/{g.appid}"), "ok", 11, padx=14, pady=5).pack(side="left")
        Btn(row, "⚡", lambda: self.run_task(lambda: games.optimize(g, self.root_dir)),
            "primary", 11, padx=14, pady=5).pack(side="left", padx=(6, 0))
        for w in (cover, name):
            w.bind("<Button-1>", lambda e: GameWindow(self, g))
        for w in (card, cover, name, badge):
            w.bind("<Enter>", lambda e, c=card: self._hover(c, CARD_HI))
            w.bind("<Leave>", lambda e, c=card: self._hover(c, CARD))
        self._refresh_badge(g)
        return card, g

    def _hover(self, card, color):
        for w in (card, *card.winfo_children()):
            if isinstance(w, (tk.Frame, tk.Label)) and not isinstance(w, Btn):
                w.configure(bg=color)
                for c in w.winfo_children():
                    if isinstance(c, tk.Frame):
                        c.configure(bg=color)

    def _refresh_badge(self, g):
        done = games.is_optimized(g)
        self.badges[g.appid].configure(text="✓ ОПТИМИЗИРОВАНО" if done else "НЕ ОПТИМИЗИРОВАНО",
                                       fg=OK if done else MUTED)

    def layout_cards(self, width=None, force=False):
        width = width or self.scroll.canvas.winfo_width()
        cols = max(1, width // CARD_W)
        if cols == self.cols and not force:
            return
        self.cols = cols
        self.scroll.canvas.yview_moveto(0)
        q = self.search.get().strip().lower()
        shown = 0
        for card, g in self.cards:
            card.grid_forget()
            if q in g.name.lower():
                card.grid(row=shown // cols, column=shown % cols, padx=6, pady=6, sticky="n")
                shown += 1

    # ---------- Видеокарта ----------
    def _checklist(self, parent, settings, store):
        box = tk.Frame(parent, bg=CARD)
        box.pack(fill="x", padx=32)
        for st in settings:
            v = tk.BooleanVar(value=True)
            store[st.key] = v
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=14, pady=5)
            tk.Checkbutton(row, variable=v, bg=CARD, activebackground=CARD, selectcolor=CARD_HI,
                           fg=TEXT, activeforeground=TEXT, bd=0, highlightthickness=0).pack(side="left")
            col = tk.Frame(row, bg=CARD)
            col.pack(side="left", fill="x")
            label(col, st.title, 10, bold=True).pack(anchor="w")
            label(col, st.desc, 9, MUTED).pack(anchor="w")

    def _page_gpu(self):
        g = self.gpus[0] if self.gpus else None
        vendor = g.vendor if g else "other"
        f = self.page("Видеокарта", (g.name + "  ·  драйвер " + g.driver) if g else "Видеокарта не определена")
        sc = Scroll(f)
        sc.pack(fill="both", expand=True, padx=(0, 18))
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
        label(body, note, 9, WARN, wraplength=760, justify="left").pack(anchor="w", padx=32, pady=(10, 0))
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
        f = self.page("Система", "Что именно будет изменено в Windows")
        box = tk.Frame(f, bg=CARD)
        box.pack(fill="x", padx=32)
        items = [(t.id, t.title, t.desc, t.revertible) for t in system_tweaks.TWEAKS]
        items += [("_gpu", "Драйвер видеокарты (NVIDIA / AMD)", "Максимальная производительность, V-Sync выкл", True),
                  ("_rp", "Создать точку восстановления", "Рекомендуется перед первым запуском", True)]
        for key, title, desc, rev in items:
            v = tk.BooleanVar(value=rev)
            self.tweak_vars[key] = v
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=14, pady=5)
            tk.Checkbutton(row, variable=v, bg=CARD, activebackground=CARD, selectcolor=CARD_HI,
                           fg=TEXT, activeforeground=TEXT, bd=0, highlightthickness=0).pack(side="left")
            col = tk.Frame(row, bg=CARD)
            col.pack(side="left", fill="x")
            label(col, title, 10, bold=True).pack(anchor="w")
            label(col, desc + ("" if rev else "  (необратимо, по умолчанию выключено)"), 9,
                  MUTED if rev else WARN).pack(anchor="w")
        Btn(f, "Применить выбранное", self.apply_system, "primary", 11, padx=22, pady=10).pack(
            anchor="w", padx=32, pady=18)
        return f

    # ---------- Журнал ----------
    def _page_log(self):
        f = self.page("Журнал", "Что делала программа")
        Btn(f, "Откатить всё", self.undo, "danger", 10).pack(anchor="w", padx=32, pady=(0, 10))
        self.log = tk.Text(f, bg=CARD, fg=TEXT, relief="flat", font=("Consolas", 10), wrap="word",
                           state="disabled", padx=14, pady=12, insertbackground=TEXT)
        self.log.pack(fill="both", expand=True, padx=32, pady=(0, 24))
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
            return
        self.busy = True
        self.progress.pack(anchor="w", padx=24, pady=(0, 20))
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
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_all.set_enabled(True)
        self.btn_undo.set_enabled(True)
        self.refresh_stats()
        for g in self.games:
            self._refresh_badge(g)
        if done:
            done()

    def optimize_all(self):
        ids = {t.id for t in system_tweaks.TWEAKS if t.revertible}
        gp = self.gpus[0] if self.gpus else None
        self.run_task(lambda: core.run(ids, self.games, gp, True))

    def apply_system(self):
        ids = {k for k, v in self.tweak_vars.items() if v.get() and not k.startswith("_")}
        gp = self.gpus[0] if self.gpus and self.tweak_vars["_gpu"].get() else None
        rp = self.tweak_vars["_rp"].get()
        self.run_task(lambda: core.run(ids, [], gp, rp))
        self.show("log")

    def undo(self):
        self.run_task(core.undo)


def main():
    App().mainloop()
