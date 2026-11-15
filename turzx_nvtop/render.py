"""Screen renderers. Each returns a full-size PIL image; Display.present() works out what changed."""
import functools
import os
import time

from PIL import Image, ImageDraw, ImageFont

from . import __version__
from .source import SERIES

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

BG = (14, 18, 24)
PANEL = (24, 30, 39)
GRID = (42, 51, 64)
TEXT = (228, 234, 242)
DIM = (128, 140, 156)
BAD = (235, 87, 87)
OK = (62, 207, 142)

COLORS = {                        # identical to knvtop / onvtop / nvstats-service README (one palette everywhere)
    "gpu": (0x4D, 0x9F, 0xFF),    # #4d9fff
    "gtt": (0xE8, 0xC3, 0x3A),    # #e8c33a
    "tmp": (0xB0, 0x7F, 0xE8),    # #b07fe8
    "pwr": (0x3D, 0xDC, 0x84),    # #3ddc84
    "cpu": (0xFF, 0x8C, 0x42),    # #ff8c42
    "npu": (0xEC, 0x60, 0xA0),    # #ec60a0
    "ram": (0x89, 0x92, 0x9C),    # #89929c
}
LABELS = {"gpu": "GPU", "gtt": "GTT", "tmp": "TMP", "pwr": "PWR", "cpu": "CPU", "ram": "RAM", "npu": "NPU"}

STALE_AFTER = 5.0                 # seconds without a sample before we say NO DATA


@functools.lru_cache(maxsize=None)
def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.load_default(size)


def mix(c, t, k):
    """Blend colour c toward t by k (0..1)."""
    return tuple(int(a + (b - a) * k) for a, b in zip(c, t))


def ctext(d, cx, y, s, f, fill):
    d.text((cx, y), s, font=f, fill=fill, anchor="mt")


def rtext(d, rx, y, s, f, fill):
    d.text((rx, y), s, font=f, fill=fill, anchor="rt")


def gib(v_mib):
    return f"{v_mib / 1024:.1f}"


class View:
    """What a renderer needs: latest sample, history, freshness, config."""

    def __init__(self, cfg, sample, history, age, error):
        self.sample = sample or {}
        self.history = history
        self.age = age
        self.error = error
        self.live = sample is not None and age is not None and age < STALE_AFTER
        self.mem_label = cfg.s("limits", "mem_label")
        self.power_max = cfg.f("limits", "power_max_w")
        self.temp_max = cfg.f("limits", "temp_max_c")
        self.pps = cfg.f("graph", "px_per_second")      # graph scroll speed, pixels per second
        self.now = time.monotonic()
        self.smooth = cfg.b("graph", "smooth")
        self.gpu = self.sample.get("gpu") or {}
        self.sys = self.sample.get("sys") or {}
        # NPU: every NPU element is hidden unless the host reports one. Present but unreadable
        # keeps the box and shows N/A, so the chip can be diagnosed later.
        self.npu = self.sample.get("npu") or {}
        self.has_npu = bool(self.npu.get("present"))
        self.npu_ok = self.has_npu and bool(self.npu.get("readable"))
        self.series = SERIES + ("npu",) if self.has_npu else SERIES

    # -- derived values (None when unknown) --
    def val(self, key):
        g, s = self.gpu, self.sys
        if not self.live:
            return None
        if key == "gpu":
            return g.get("util")
        if key == "gtt":
            return g["mem_used"] / g["mem_total"] * 100 if g.get("mem_total") else None
        if key == "tmp":
            return g.get("temp")
        if key == "pwr":
            return g.get("power_w")
        if key == "cpu":
            return s.get("cpu")
        if key == "ram":
            return s["ram_used"] / s["ram_total"] * 100 if s.get("ram_total") else None
        if key == "npu":
            return self.npu.get("util") if self.npu_ok else None
        return None

    def text(self, key):
        v = self.val(key)
        if key == "npu" and self.live and self.has_npu and not self.npu_ok:
            return "N/A"
        if v is None:
            return "--"
        if key == "tmp":
            return f"{v:.0f}°"
        if key == "pwr":
            return f"{v:.0f}W"
        return f"{v:.0f}%"

    def frac(self, key):
        v = self.val(key)
        if v is None:
            return 0.0
        if key == "tmp":
            v = v / self.temp_max * 100
        elif key == "pwr":
            v = v / (self.gpu.get("power_cap_w") or self.power_max) * 100
        return max(0.0, min(1.0, v / 100))


def header(d, v, title):
    d.rectangle((0, 0, 479, 25), fill=PANEL)
    host = v.sample.get("host") or "nvtop"
    d.text((10, 13), host, font=font(14, True), fill=TEXT, anchor="lm")
    d.text((10 + d.textlength(host, font=font(14, True)) + 10, 14), title, font=font(11), fill=DIM, anchor="lm")
    if v.live:
        label, col = "LIVE", OK
    else:
        label, col = "NO DATA", BAD
    f = font(11, True)
    w = d.textlength(label, font=f)
    d.text((470, 13), label, font=f, fill=col, anchor="rm")
    d.ellipse((470 - w - 16, 8, 470 - w - 8, 16), fill=col)


# ---- screen 1: graph -----------------------------------------------------------------------
GX0, GY0, GX1, GY1 = 8, 64, 471, 282          # graph panel (inclusive)


def render_graph(v):
    img = Image.new("RGB", (480, 320), BG)
    d = ImageDraw.Draw(img)
    header(d, v, v.gpu.get("name") or "GPU telemetry")

    # legend: one coloured current value per series (NPU only on hosts that have one)
    slot = 464 / len(v.series)
    for i, k in enumerate(v.series):
        x = 8 + slot * i
        d.rounded_rectangle((x, 32, x + 3, 58), radius=1, fill=COLORS[k])
        d.text((x + 9, 31), LABELS[k], font=font(10), fill=DIM)
        d.text((x + 9, 42), v.text(k), font=font(17, True), fill=COLORS[k] if v.live else DIM)

    # graph panel, drawn 3x and scaled down for smooth lines
    pw, ph, S = GX1 - GX0 + 1, GY1 - GY0 + 1, 3
    big = Image.new("RGB", (pw * S, ph * S), PANEL)
    g = ImageDraw.Draw(big)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = int(round((1 - frac) * (ph * S - 8 * S)) + 4 * S)
        g.line((0, y, pw * S, y), fill=GRID, width=S)
    top, span = 4 * S, ph * S - 8 * S
    for k in reversed(v.series):                     # draw GPU last so it sits on top
        hist = v.history.get(k) or []
        if len(hist) < 2 or (k == "npu" and not v.npu_ok):
            continue
        times = v.history.get("t") or []
        # each point sits at x = right edge - age * px/s, so the whole line slides left continuously
        # and rigidly between samples; with smooth=no it only moves when a sample arrives
        newest = times[-1] if times else 0
        pts = [((pw - 3 - ((v.now if v.smooth else newest) - t) * v.pps) * S, top + (1 - val / 100) * span)
               for t, val in zip(times, hist)]
        if v.smooth:
            pts.append(((pw - 3) * S, pts[-1][1]))          # hold the newest value out to the edge
        # keep one point beyond the left edge so the line's end slides out instead of snapping
        first = next((i for i, p in enumerate(pts) if p[0] >= 0), len(pts) - 1)
        pts = pts[max(0, first - 1):]
        if len(pts) >= 2:
            g.line(pts, fill=COLORS[k], width=int(1.6 * S), joint="curve")
    img.paste(big.resize((pw, ph), Image.LANCZOS), (GX0, GY0))

    # footer
    s, gp = v.sys, v.gpu
    if v.live and gp.get("mem_total") and s.get("ram_total"):
        foot = (f"{v.mem_label} {gib(gp['mem_used'])}/{gib(gp['mem_total'])} GiB    "
                f"sys {s['ram_used'] / 2**30:.1f}/{s['ram_total'] / 2**30:.1f} GiB    "
                f"load {s.get('load1', 0):.2f}")
    else:
        foot = v.error or "waiting for nvstats-service..."
    ctext(d, 240, 292, foot, font(12), DIM)
    return img


# ---- screen 2: gauges ----------------------------------------------------------------------
def ring(diameter, thick, frac, color):
    """Anti-aliased ring (RGBA) drawn at 4x and scaled down."""
    S = 4
    D = diameter * S
    im = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    g = ImageDraw.Draw(im)
    box = (0, 0, D - 1, D - 1)
    g.arc(box, 0, 360, fill=mix(color, PANEL, 0.80) + (255,), width=thick * S)
    if frac > 0.004:
        g.arc(box, -90, -90 + 360 * frac, fill=color + (255,), width=thick * S)
    return im.resize((diameter, diameter), Image.LANCZOS)


def gauge_sub(v, key):
    g, s = v.gpu, v.sys
    if not v.live:
        return ""
    if key == "gpu":
        return f"{g['clock_gfx']} MHz" if g.get("clock_gfx") else ""
    if key == "gtt":
        return f"{gib(g['mem_used'])} / {gib(g['mem_total'])} GiB" if g.get("mem_total") else ""
    if key == "tmp":
        return f"limit {v.temp_max:.0f}°C"
    if key == "pwr":
        return f"of {g.get('power_cap_w') or v.power_max:.0f} W"
    if key == "cpu":
        return f"load {s.get('load1', 0):.2f}"
    if key == "ram":
        return f"{s['ram_used'] / 2**30:.1f} / {s['ram_total'] / 2**30:.1f} GiB" if s.get("ram_total") else ""
    if key == "npu":
        n = v.npu
        if not v.npu_ok:
            return (n.get("reason") or "unreadable").split(":")[0][:18]
        return f"{n['clock_mhz']} MHz" if n.get("clock_mhz") else ""
    return ""


def render_gauges(v):
    img = Image.new("RGB", (480, 320), BG)
    d = ImageDraw.Draw(img)
    header(d, v, "system")
    keys = ("gpu", "gtt", "tmp", "pwr", "cpu", "ram") + (("npu",) if v.has_npu else ())
    # 3 columns normally; with an NPU there are 7 boxes, so 4 + 3 (the short row is centred)
    cols = 4 if len(keys) > 6 else 3
    gap = 4
    cw, ch = (464 - gap * (cols - 1)) // cols, 126
    x0, y0 = 8, 32
    for i, k in enumerate(keys):
        row_n = min(cols, len(keys) - (i // cols) * cols)
        row_off = (cols - row_n) * (cw + gap) // 2
        cx = x0 + row_off + (i % cols) * (cw + gap)
        cy = y0 + (i // cols) * (ch + gap)
        col = COLORS[k]
        d.rounded_rectangle((cx, cy, cx + cw - 1, cy + ch - 1), radius=10, fill=PANEL,
                            outline=mix(col, PANEL, 0.62), width=1)
        diam = 78
        rx, ry = cx + (cw - diam) // 2, cy + 8
        r = ring(diam, 9, v.frac(k), col)
        img.paste(r, (rx, ry), r)
        # centre the digit height (measured on "0", so it is stable between values) on the ring centre
        vf = font(21, True)
        t, b = d.textbbox((0, 0), "0", font=vf, anchor="ls")[1::2]
        d.text((cx + cw // 2, round(ry + diam / 2 - (t + b) / 2)), v.text(k), font=vf,
               fill=TEXT if v.live else DIM, anchor="ms")
        ctext(d, cx + cw // 2, cy + 90, LABELS[k] if k != "gtt" else v.mem_label, font(12, True), col)
        ctext(d, cx + cw // 2, cy + 106, gauge_sub(v, k), font(10), DIM)
    if v.live:
        bits = []
        if v.gpu.get("driver"):
            bits.append(f"driver {v.gpu['driver']}")
        if v.sample.get("version"):
            bits.append(f"nvstats {v.sample['version']}")
        bits.append(f"turzx-nvtop {__version__}")
        foot = "  \u00b7  ".join(bits)
    else:
        foot = v.error or ""
    ctext(d, 240, 302, foot, font(10), DIM)
    return img


# ---- screen 3: running LLMs ----------------------------------------------------------------
# same engine colors as knvtop / onvtop
ENGINE_COLORS = {"llama": COLORS["gpu"], "ollama": COLORS["gtt"], "vllm": COLORS["tmp"],
                 "sglang": COLORS["pwr"], "tgi": COLORS["cpu"], "flm": COLORS["npu"]}


def llm_rows(v):
    rows = []
    llm = v.sample.get("llm") or {}
    for engine in ("llama", "ollama", "vllm", "sglang", "tgi", "flm"):
        for p in llm.get(engine) or []:
            name = p.get("alias") or p.get("model") or p.get("name") or engine
            name = os.path.basename(str(name))
            bits = []
            if p.get("port"):
                bits.append(f":{p['port']}")
            if p.get("rss_kb"):
                bits.append(f"RSS {p['rss_kb'] / 2**20:.1f} GiB")
            if p.get("ctx"):
                bits.append(f"ctx {p['ctx']}")
            if p.get("parallel"):
                bits.append(f"np {p['parallel']}")
            if engine == "flm" and v.npu_ok and p.get("gpu_pct") is not None:
                bits.append(f"npu {p['gpu_pct']:.0f}%")
            if p.get("cpu_pct"):
                bits.append(f"cpu {p['cpu_pct']:.0f}%")
            rows.append((engine, name, "  ".join(bits)))
    for m in llm.get("ollama_models") or []:
        if isinstance(m, dict):
            name = m.get("name") or m.get("model") or "model"
            size = m.get("size_vram") or m.get("size")
            rows.append(("ollama", name, f"loaded  {size / 2**30:.1f} GiB" if size else "loaded"))
    return rows


def render_llm(v):
    img = Image.new("RGB", (480, 320), BG)
    d = ImageDraw.Draw(img)
    header(d, v, "running LLMs")
    rows = llm_rows(v) if v.live else []
    if not rows:
        ctext(d, 240, 150, "no LLM engines running" if v.live else "no data", font(16, True), DIM)
    y = 34
    for engine, name, detail in rows[:6]:
        col = ENGINE_COLORS.get(engine, DIM)
        d.rounded_rectangle((8, y, 471, y + 40), radius=8, fill=PANEL)
        d.rounded_rectangle((8, y, 12, y + 40), radius=2, fill=col)
        d.text((22, y + 4), name[:34], font=font(15, True), fill=TEXT)
        d.text((22, y + 24), detail[:62], font=font(11), fill=DIM)
        # only hosts with an NPU get a device tag, so GPU-only setups stay uncluttered
        tag = engine
        if v.has_npu:
            tag = f"{engine} \u00b7 {'NPU' if engine == 'flm' else 'GPU'}"
        rtext(d, 464, y + 6, tag, font(11, True), col)
        y += 45
    if len(rows) > 6:
        ctext(d, 240, 306, f"+{len(rows) - 6} more", font(10), DIM)
    return img


RENDERERS = {"graph": render_graph, "gauges": render_gauges, "llm": render_llm}
