"""INI configuration (stdlib configparser). Every key is optional; defaults live here."""
import configparser
import os

DEFAULTS = {
    "nvstats": {
        "url": "http://127.0.0.1:8039",   # nvstats-service HTTP API
        "token": "",                      # NVSTATS_TOKEN, if the service requires one
    },
    "display": {
        "port": "auto",                   # auto, or a device path such as /dev/turzx-lcd
        "rotation": "0",                  # 0 or 180 (landscape only): flip if the screen is upside down in your mounting
        "brightness": "70",               # percent
        "sync_on_start": "yes",           # flush zeros so a previously killed writer cannot wedge the panel
        "full_refresh_seconds": "600",    # repaint everything now and then to heal any glitch (0 = never)
        "screen_off_on_exit": "no",
    },
    "screens": {
        "order": "graph, gauges",         # any of: graph, gauges, llm
        "graph_seconds": "15",
        "gauges_seconds": "5",
        "llm_seconds": "5",
    },
    "graph": {
        "px_per_sample": "2",
        "refresh_seconds": "0.25",        # how often the graph screen is redrawn
        "smooth": "yes",                  # scroll continuously between the 1 Hz samples (needs a fast refresh)
    },
    "gauges": {
        "refresh_seconds": "1",
    },
    "llm": {
        "refresh_seconds": "2",
    },
    "limits": {
        "power_max_w": "120",             # 100% of the power gauge/graph (the GPU's own cap is used if it reports one)
        "temp_max_c": "100",
        "mem_label": "GTT",               # what to call GPU memory (GTT on an APU, VRAM on a discrete card)
    },
}

SEARCH = (
    os.environ.get("TURZX_NVTOP_CONFIG", ""),
    os.path.expanduser("~/.config/turzx-nvtop/config.ini"),
    "/etc/turzx-nvtop/config.ini",
)


class Config:
    def __init__(self, path=None):
        self.cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        self.cp.read_dict(DEFAULTS)
        self.path = None
        for p in ([path] if path else SEARCH):
            if p and os.path.isfile(p):
                self.cp.read(p)
                self.path = p
                break
        else:
            if path:
                raise SystemExit(f"config file not found: {path}")

    def s(self, section, key):
        return self.cp.get(section, key).strip()

    def i(self, section, key):
        return self.cp.getint(section, key)

    def f(self, section, key):
        return self.cp.getfloat(section, key)

    def b(self, section, key):
        return self.cp.getboolean(section, key)

    def orientation(self):
        """Device orientation value: 2 = landscape, 3 = landscape rotated 180."""
        r = self.s("display", "rotation")
        if r not in ("0", "180"):
            raise SystemExit(f"[display] rotation must be 0 or 180, not {r!r}")
        return 2 if r == "0" else 3

    def screens(self):
        names = [n.strip() for n in self.s("screens", "order").split(",") if n.strip()]
        bad = [n for n in names if n not in ("graph", "gauges", "llm")]
        if bad or not names:
            raise SystemExit(f"[screens] order: unknown or empty ({bad or names})")
        return names
