"""Main loop: follow nvstats, rotate screens, push only the changed pixels to the LCD."""
import argparse
import math
import signal
import threading
import time

from . import __version__
from .config import Config
from .lcd import Display, LcdError, Turzx, find_port
from .render import RENDERERS, View
from .source import State, follow


def log(msg):
    print(f"turzx-nvtop: {msg}", flush=True)


def make_state(cfg):
    pw = 471 - 8 + 1
    # enough samples to fill the graph at the fastest rate nvstats allows (0.25 s)
    hist_len = int(pw / max(0.1, cfg.f("graph", "px_per_second")) / 0.25) + 2
    limits = {"power_max_w": cfg.f("limits", "power_max_w"), "temp_max_c": cfg.f("limits", "temp_max_c")}
    return State(limits, hist_len)


def demo_state(cfg):
    """Synthetic data so screens can be previewed without nvstats or hardware."""
    st = make_state(cfg)
    for i in range(240):
        st.push(t=time.monotonic() - (239 - i), s={
            "host": "DEMO-HOST", "seq": i,
            "gpu": {"name": "AMD Radeon 8060S Graphics", "driver": "7.1.9", "util": 50 + 45 * math.sin(i / 17),
                    "mem_used": 30000 + 20000 * math.sin(i / 53), "mem_total": 79872,
                    "temp": 52 + 14 * math.sin(i / 29), "power_w": 60 + 40 * math.sin(i / 11),
                    "power_cap_w": None, "clock_gfx": 2100, "clock_gfx_max": 2900},
            "sys": {"cpu": 20 + 15 * math.sin(i / 7), "ram_used": 40 * 2**30, "ram_total": 92 * 2**30, "load1": 1.2},
            "llm": {"llama": [{"name": "llama-server", "alias": "llama-3-8b-instruct", "port": "8082",
                               "rss_kb": 3400000, "ctx": 262144, "parallel": 2, "cpu_pct": 12.0}],
                    "ollama": [{"name": "ollama", "port": None, "rss_kb": 40000}], "ollama_models": []},
        })
    return st


class Scheduler:
    """Which screen is up now, and when to redraw it."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.names = cfg.screens()
        self.idx = 0
        self.since = time.monotonic()

    def current(self, now):
        name = self.names[self.idx]
        dur = self.cfg.f("screens", f"{name}_seconds")
        if len(self.names) > 1 and now - self.since >= dur:
            self.idx = (self.idx + 1) % len(self.names)
            self.since = now
            return self.names[self.idx], True
        return name, False

    def refresh(self, name):
        return self.cfg.f(name, "refresh_seconds")


def connect(cfg, stop):
    """Open the panel, retrying until it appears."""
    port_cfg = cfg.s("display", "port")
    while not stop.is_set():
        try:
            path = None if port_cfg == "auto" else port_cfg
            if path is None and find_port() is None:
                raise LcdError("display not found (USB 1a86:5722)")
            lcd = Turzx(path)
            if cfg.b("display", "sync_on_start"):
                lcd.sync()
            lcd.set_orientation(cfg.orientation())
            lcd.set_brightness(cfg.i("display", "brightness"))
            lcd.screen_on()
            log(f"display ready on {lcd.path}")
            return lcd
        except LcdError as e:
            log(f"{e}; retrying in 5 s")
            stop.wait(5)
    return None


def run(cfg):
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    state = make_state(cfg)
    threading.Thread(target=follow, args=(cfg.s("nvstats", "url"), cfg.s("nvstats", "token"), state, stop),
                     daemon=True).start()
    log(f"v{__version__}, nvstats at {cfg.s('nvstats', 'url')}, config {cfg.path or '(defaults)'}")
    sched = Scheduler(cfg)
    full_every = cfg.f("display", "full_refresh_seconds")
    lcd = None
    try:
        while not stop.is_set():
            if lcd is None:
                lcd = connect(cfg, stop)
                if lcd is None:
                    break
                disp = Display(lcd)
                last_full = time.monotonic()
            t0 = time.monotonic()
            name, switched = sched.current(t0)
            if full_every and t0 - last_full >= full_every:
                disp.invalidate()
                last_full = t0
            sample, hist, age, err = state.snapshot()
            img = RENDERERS[name](View(cfg, sample, hist, age, err))
            try:
                disp.present(img)
            except LcdError as e:
                log(f"lost the display ({e}); reconnecting")
                lcd.close()
                lcd = None
                continue
            took = time.monotonic() - t0
            if cfg.verbose:
                log(f"{name}: {disp.stats_pixels} px in {disp.stats_rects} rects, {took * 1000:.0f} ms")
            stop.wait(max(0.05, sched.refresh(name) - took))
    finally:
        if lcd is not None:
            try:
                if cfg.b("display", "screen_off_on_exit"):
                    lcd.screen_off()
            except LcdError:
                pass
            lcd.close()
        log("stopped")


def preview(cfg, screen, out, demo):
    if demo:
        state = demo_state(cfg)
    else:
        state = make_state(cfg)
        stop = threading.Event()
        threading.Thread(target=follow, args=(cfg.s("nvstats", "url"), cfg.s("nvstats", "token"), state, stop),
                         daemon=True).start()
        for _ in range(100):
            if state.sample:
                break
            time.sleep(0.1)
        if not state.sample:
            raise SystemExit(f"no sample from {cfg.s('nvstats', 'url')} ({state.error}); try --demo")
        stop.set()
    sample, hist, age, err = state.snapshot()
    RENDERERS[screen](View(cfg, sample, hist, age, err)).save(out)
    log(f"wrote {out}")


def lcd_cmd(cfg, what):
    lcd = Turzx(None if cfg.s("display", "port") == "auto" else cfg.s("display", "port"))
    try:
        if what == "sync":
            lcd.sync()
        elif what == "on":
            lcd.screen_on()
        elif what == "off":
            lcd.screen_off()
    finally:
        lcd.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="turzx-nvtop", description=__doc__)
    ap.add_argument("-c", "--config", help="config.ini path (default: ~/.config/turzx-nvtop/config.ini, /etc/turzx-nvtop/config.ini)")
    ap.add_argument("--version", action="version", version=f"turzx-nvtop {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true", help="log pixels/rects/ms for every frame")
    ap.add_argument("--rotate", choices=("0", "180"), help="override [display] rotation")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="run the display loop (default)")
    p = sub.add_parser("preview", help="render a screen to a PNG without touching the hardware")
    p.add_argument("screen", choices=sorted(RENDERERS))
    p.add_argument("out", nargs="?", default="preview.png")
    p.add_argument("--demo", action="store_true", help="use synthetic data instead of nvstats-service")
    for n, h in (("sync", "flush zeros to un-wedge a desynchronised panel"), ("on", "screen on"), ("off", "screen off")):
        sub.add_parser(n, help=h)
    a = ap.parse_args(argv)
    cfg = Config(a.config)
    cfg.verbose = a.verbose
    if a.rotate:
        cfg.cp.set("display", "rotation", a.rotate)
    if a.cmd in (None, "run"):
        run(cfg)
    elif a.cmd == "preview":
        preview(cfg, a.screen, a.out, a.demo)
    else:
        lcd_cmd(cfg, a.cmd)
