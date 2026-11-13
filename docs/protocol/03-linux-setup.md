# 03 — Picking this up on Linux (Kubuntu)

Nothing in this file has been run on Linux yet. It is the plan, based on the device being a standard
CDC-ACM serial port and on what was verified on Windows.

## 1. Plug in and locate the port

```bash
lsusb -d 1a86:5722
```

```bash
ls -l /dev/serial/by-id/ /dev/ttyACM*
```

Expected: `/dev/ttyACM0` owned by `root:dialout`, mode `crw-rw----`.
Driver is the in-kernel `cdc_acm`; nothing to install.

## 2. Permissions

Either add yourself to `dialout` (log out/in afterwards):

```bash
sudo usermod -aG dialout "$USER"
```

…or (better) install a udev rule that gives a stable name, grants access, and tells ModemManager to
leave the device alone. ModemManager is installed by default on Kubuntu and probes new ttyACM devices
by writing `AT` commands into them — on this device stray bytes are parsed as display commands, which
can de-synchronise or hang it.

Create `/etc/udev/rules.d/99-turzx-lcd.rules` with this single line:

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", SYMLINK+="turzx-lcd", MODE="0660", GROUP="dialout", TAG+="uaccess", ENV{ID_MM_DEVICE_IGNORE}="1"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Re-plug the display; `/dev/turzx-lcd` should now exist.

## 3. First test with the small tool in this folder

```bash
sudo apt install python3-pil python3-numpy
```

```bash
python3 tools/turzx.py selftest
```

```bash
python3 tools/turzx.py sync
```

```bash
python3 tools/turzx.py test
```

Expected: landscape test pattern — yellow border, `TOP-LEFT 0,0` top-left, four bars whose colours match
their labels RED / GREEN / BLUE / WHITE.

Then the framing torture test — every strip must have a readable label, an intact yellow outline, a red
`\` at the left end and a green `/` at the right end:

```bash
python3 tools/turzx.py striptest
```

If any strip is scrambled, Linux is segmenting the writes differently from what I assumed — see below.

Real use:

```bash
python3 tools/turzx.py --orient 2 image "../3.5/landscape magic blue amd.png"
```

```bash
python3 tools/turzx.py --orient 2 text "CPU 42C" --x 20 --y 200 --size 28 --fg "#00ffff"
```

Always pass `--orient` (or call `orient` first in the same session): the tool cannot ask the device which
orientation it is in.

## Known risk: write segmentation

On Windows I verified that pixel data must arrive in full 64-byte USB packets (only the last packet of an
image may be short) and that a command must be its own packet
([02-protocol.md](02-protocol.md#usb-packet-framing-rules-important)).

On Linux the path is `write()` → tty layer → `cdc_acm` → USB. `turzx.py` writes in 1024-byte chunks and
calls `tcdrain()` after each write, which *should* produce packet boundaries only at multiples of 64.
I have not confirmed how the kernel actually splits them. If `striptest` shows corruption:

* try a different `CHUNK` in `turzx.py` (64, 512, 1280),
* or bypass the tty entirely with **pyusb** (`sudo apt install python3-usb`): detach the kernel driver,
  claim the CDC data interface and do bulk writes to the OUT endpoint — then you control packetisation
  exactly. Get the endpoint address from `sudo lsusb -v -d 1a86:5722`.

A USB capture settles any doubt:

```bash
sudo modprobe usbmon
```

then capture the bus with Wireshark and look at the lengths of the bulk OUT transfers.

## If the device hangs

Symptom: writes block / time out; nothing changes on screen.

1. `python3 tools/turzx.py sync` (only helps if it is merely de-synchronised).
2. Re-plug the USB cable.
3. Possibly, without touching the cable (untested), unbind/rebind the USB device via
   `/sys/bus/usb/drivers/usb/unbind` and `bind`. This only resets the host side; if the MCU itself is
   stuck it needs a power cycle.

## 4. Or: use the existing project

<https://github.com/mathoudebine/turing-smart-screen-python> already does CPU/GPU/RAM/network/disk
themes on Linux. In its `config.yaml`:

```yaml
config:
  COM_PORT: "/dev/turzx-lcd"   # or AUTO
display:
  REVISION: A
  RESET_ON_STARTUP: false      # wiki recommends this for some variants of this model
```

Check the current README/wiki for the exact keys — I read its protocol source and hardware-revision
wiki page, not its configuration docs. Watch for garbled small text/number fields: its `width × 8` chunking
is the pattern that failed on this unit under Windows. If that happens, the fix is a one-liner in
`library/lcd/lcd_comm_rev_a.py` — use a fixed chunk size that is a multiple of 64 instead of `width * 8`.

## 5. Building your own monitor (sketch)

1. On start: open port → `sync` → set orientation → set brightness → send background PNG once.
2. Keep the background as a Pillow image in memory.
3. For each value that changed: crop the background rectangle, draw the text/bar onto the crop,
   send that rectangle. Keep rectangles small — the link carries about 150 000 pixels per second.
4. Read sensors with `psutil` (CPU, RAM, net, disk), `/sys/class/hwmon` or `sensors -j` (temperatures),
   `nvidia-smi --query-gpu=…` or `/sys/class/drm` (GPU).
5. Run as a systemd **user** service; on stop, optionally send screen-off (`108`).
6. Never let two programs write to the port at once, and never kill the writer mid-image without
   running `sync` before the next session.
