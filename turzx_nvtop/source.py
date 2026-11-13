"""nvstats-service client: follows its Server-Sent-Events stream and keeps recent history for the graph."""
import collections
import json
import threading
import time
import urllib.request

SERIES = ("gpu", "gtt", "tmp", "pwr", "cpu")      # graph/legend order


def _num(v, default=0.0):
    return float(v) if isinstance(v, (int, float)) else default


class State:
    """Thread-safe latest sample plus normalised (0-100) history per series."""

    def __init__(self, limits, history_len):
        self.lock = threading.Lock()
        self.sample = None
        self.last_rx = 0.0           # monotonic time of the last sample
        self.history = {k: collections.deque(maxlen=history_len) for k in SERIES}
        self.limits = limits         # dict: power_max_w, temp_max_c
        self.error = None

    def push(self, s):
        g = s.get("gpu") or {}
        sysd = s.get("sys") or {}
        pmax = _num(g.get("power_cap_w")) or self.limits["power_max_w"]
        mem_total = _num(g.get("mem_total"), 0.0)
        norm = {
            "gpu": _num(g.get("util")),
            "gtt": (_num(g.get("mem_used")) / mem_total * 100.0) if mem_total else 0.0,
            "tmp": _num(g.get("temp")) / self.limits["temp_max_c"] * 100.0,
            "pwr": _num(g.get("power_w")) / pmax * 100.0,
            "cpu": _num(sysd.get("cpu")),
        }
        with self.lock:
            self.sample = s
            self.last_rx = time.monotonic()
            self.error = None
            for k in SERIES:
                self.history[k].append(max(0.0, min(100.0, norm[k])))

    def snapshot(self):
        """(sample or None, {series: [values]}, seconds since last sample, error text)."""
        with self.lock:
            age = time.monotonic() - self.last_rx if self.last_rx else None
            return self.sample, {k: list(v) for k, v in self.history.items()}, age, self.error


def follow(url, token, state, stop):
    """Blocking loop: stream samples into ``state`` until ``stop`` (threading.Event) is set."""
    req_url = url.rstrip("/") + "/api/v1/stream?full=1"
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    while not stop.is_set():
        try:
            req = urllib.request.Request(req_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                event, data = None, []
                for raw in resp:
                    if stop.is_set():
                        return
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith(":"):
                        continue                       # keep-alive comment
                    if line == "":
                        if event == "sample" and data:
                            state.push(json.loads("\n".join(data)))
                        event, data = None, []
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
        except Exception as e:                         # network, JSON, HTTP error: retry
            with state.lock:
                state.error = f"{type(e).__name__}: {e}"
            stop.wait(2.0)
