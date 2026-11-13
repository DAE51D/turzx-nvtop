# turzx-nvtop

GPU/system stats on the **Turzx 3.5" USB LCD** (USB `1a86:5722`, a.k.a. "Turing Smart Screen" 3.5" rev A),
in the same style as [knvtop](https://github.com/DAE51D/knvtop) and [onvtop](https://github.com/DAE51D/openchamber-onvtop).
It is a client of [nvstats-service](https://github.com/DAE51D/nvstats-service) and is otherwise self-contained:
its own USB-serial driver, no third-party screen library, no pyserial.

![gauges screen](docs/6-panel.jpg)
![graph screen](docs/nvtop-graph.jpg)

Screens (rotating; order and durations configurable):

| Screen | Shows |
| --- | --- |
| `graph`  | GPU / GTT / TMP / PWR / CPU history lines with live values (default 15 s) |
| `gauges` | six ring gauges: GPU, GTT, TMP, PWR, CPU, RAM (default 5 s) |
| `llm`    | running llama.cpp / Ollama / vLLM / SGLang / TGI engines (off by default) |


## Turzx 3.5 USB LCD

You can [find these](https://www.ebay.com/sch/i.html?_nkw=3.5%20Inch%20Type%E2%80%91C%20IPS%20Secondary%20Screen%20320*480%20USB&_sacat=0&_sop=15) on eBay for $20 or so. [This is a nice kit](https://www.ebay.com/itm/145206664084?var=444390238227) too.


![6-panels](docs/6-panel.jpg)  ![nvtop-graph](docs/nvtop-graph.jpg)


## Smoothness

The graph scrolls continuously: every point is placed by the time it arrived (`px_per_second`), so lines glide
at 4 fps between samples instead of jumping once per sample. nvstats-service samples once a second by default;
for livelier numbers run it with `./install.sh --http --poll 0.5` (nvstats-service 0.3.0 or newer).

## How it stays fast

The panel takes ~1.8 s for a full frame and repaints top to bottom. So each screen is rendered in memory,
compared with a shadow copy of what the panel shows, and only the changed rectangles are sent. Steady state is
about 3-6k pixels and 45-90 ms per update. A screen *switch* is a near-full repaint (~1.6 s), which is why
switches are slow and visible.

## Requirements

Linux, Python 3.8+, Pillow and numpy, a running [nvstats-service](https://github.com/DAE51D/nvstats-service) with HTTP enabled (`./install.sh --http` there).
No distro-specific code: it talks to `/dev/ttyACM*` with plain termios.

## Install

```sh
git clone https://github.com/DAE51D/turzx-nvtop.git && cd turzx-nvtop
./install.sh                                   # user service + udev rule (asks for sudo for the rule)
sudo ./install.sh --system --run-as USER       # headless host: system service
```

The udev rule (`packaging/70-turzx-lcd.rules`, installed to `/etc/udev/rules.d/`) does three things:

- gives the display a stable name, `/dev/turzx-lcd`;
- grants access to whoever is logged in at the machine (`uaccess`), so no group membership is needed on a desktop.
  Headless or system-service use goes through the serial group instead (`dialout`, or `uucp` on Arch-family distros;
  the installer picks the one your distro has);
- tells ModemManager to leave the port alone. It otherwise probes it with AT commands, which the panel parses as
  drawing commands and can wedge until re-plugged.

The file name matters: it has to sort before `73-seat-late.rules` (applies `uaccess`) and `77-mm-*.rules`
(ModemManager), which is why it starts with `70-`. Only the rule is needed? `./install.sh --udev-only`, then re-plug.

**Unplugging is fine.** The daemon logs it once, waits quietly, and redraws as soon as the display is back.

## Configure

`~/.config/turzx-nvtop/config.ini` (or `/etc/turzx-nvtop/config.ini`); see [config.example.ini](config.example.ini).
Upside down because of your cable? `rotation = 180` under `[display]` (or `--rotate 180`). Landscape only.

## Commands

```sh
python3 -m turzx_nvtop --version
python3 -m turzx_nvtop                 # run in the foreground (-v prints pixels/rects/ms per frame)
python3 -m turzx_nvtop preview gauges out.png [--demo]   # render a screen to PNG, no hardware needed
python3 -m turzx_nvtop sync | on | off # recover a wedged panel / screen on / off
python3 -m unittest discover -s tests  # unit tests
python3 tests/hw_striptest.py          # framing torture test on the real panel
```

## Protocol notes

Reverse-engineering notes are in [docs/protocol](docs/protocol). Key rules: a command is its own write, pixel
data goes out in multiples of 64 bytes, and never kill the writer mid-frame without running `sync` after
(the daemon does this at start).
