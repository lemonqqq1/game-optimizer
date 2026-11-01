"""Живой мониторинг: загрузка CPU, память, видеокарта (через nvidia-smi, если есть)."""
import atexit
import ctypes
import shutil
import subprocess
import threading
import time
from collections import deque
from ctypes import wintypes

NO_WINDOW = 0x08000000


class _FT(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MEM(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
        (n, ctypes.c_ulonglong) for n in ("total", "avail", "tpf", "apf", "tv", "av", "aev")]


def memory():
    """(занято ГБ, всего ГБ, процент)."""
    m = _MEM()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    gb = 1024 ** 3
    return (m.total - m.avail) / gb, m.total / gb, m.dwMemoryLoad


def avail_mb() -> float:
    m = _MEM()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.avail / 1024 ** 2


def _times():
    i, k, u = _FT(), _FT(), _FT()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    v = lambda f: (f.hi << 32) | f.lo
    return v(i), v(k), v(u)


def _push(dq, v):
    """Первое значение заполняет всю историю, чтобы график не начинался со ступеньки от нуля."""
    if not dq:
        dq.extend([v] * dq.maxlen)
    else:
        dq.append(v)


def last(dq) -> float:
    return dq[-1] if dq else 0.0


class Monitor:
    """Фоновый сбор раз в секунду. Значения читаются из GUI без блокировок (только чтение)."""

    def __init__(self, history=60):
        self.cpu, self.ram, self.gpu, self.temp = (deque(maxlen=history) for _ in range(4))
        self.ram_used = self.ram_total = 0.0
        self.gpu_temp = self.vram_used = self.vram_total = None
        self.has_gpu = False
        self._smi = None
        threading.Thread(target=self._cpu_loop, daemon=True).start()
        exe = shutil.which("nvidia-smi")
        if exe:
            threading.Thread(target=self._gpu_loop, args=(exe,), daemon=True).start()

    def _cpu_loop(self):
        prev = _times()
        while True:
            time.sleep(1)
            cur = _times()
            idle, kern, user = (c - p for c, p in zip(cur, prev))
            prev = cur
            total = kern + user  # kernel включает idle
            _push(self.cpu, max(0.0, min(100.0, (total - idle) * 100 / total)) if total else 0.0)
            self.ram_used, self.ram_total, pct = memory()
            _push(self.ram, float(pct))

    def _gpu_loop(self, exe):
        q = "utilization.gpu,temperature.gpu,memory.used,memory.total"
        try:
            self._smi = subprocess.Popen([exe, f"--query-gpu={q}", "--format=csv,noheader,nounits", "-lms", "1000"],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         creationflags=NO_WINDOW)
        except OSError:
            return
        atexit.register(self._smi.kill)
        for line in self._smi.stdout:
            parts = [p.strip() for p in line.split(",")]
            try:
                util, temp, used, total = (float(p) for p in parts[:4])
            except ValueError:
                continue
            self.gpu_temp, self.vram_used, self.vram_total = temp, used / 1024, total / 1024
            _push(self.gpu, util)
            _push(self.temp, temp)
            self.has_gpu = True
