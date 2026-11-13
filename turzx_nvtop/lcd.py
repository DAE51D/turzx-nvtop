"""Driver for the Turzx / "Turing Smart Screen" 3.5" USB LCD (USB 1a86:5722, revision A protocol).

The panel is a USB CDC-ACM serial device.  Drawing = a 6-byte command followed by raw RGB565
little-endian pixels for a rectangle.  See docs/protocol/02-protocol.md.

Two layers:

* ``Turzx``   - the wire protocol (raw termios port, framing rules, commands).
* ``Display`` - keeps a shadow copy of what the panel currently shows, and ``present()`` only
  transmits the rectangles that differ from it.  The link carries ~150k pixels/s and the panel
  repaints top-to-bottom, so sending only what changed is what makes live graphs usable.
"""
import glob
import os
import time

import numpy as np

CMD_RESET = 101
CMD_CLEAR = 102
CMD_TO_BLACK = 103
CMD_SCREEN_OFF = 108
CMD_SCREEN_ON = 109
CMD_SET_BRIGHTNESS = 110
CMD_SET_ORIENTATION = 121
CMD_DISPLAY_BITMAP = 197

PORTRAIT, REVERSE_PORTRAIT, LANDSCAPE, REVERSE_LANDSCAPE = 0, 1, 2, 3
NATIVE_W, NATIVE_H = 320, 480
USB_PACKET = 64          # full-speed bulk packet; pixel writes must be multiples of this
CHUNK = 4096             # multiple of USB_PACKET

USB_ID = ("1a86", "5722")


class LcdError(OSError):
    """The port vanished, timed out, or refused data."""


def pack_cmd(cmd, x=0, y=0, ex=0, ey=0):
    """6-byte command: four 10-bit big-endian fields + command byte."""
    return bytes([
        (x >> 2) & 0xFF,
        (((x & 3) << 6) + (y >> 4)) & 0xFF,
        (((y & 15) << 4) + (ex >> 6)) & 0xFF,
        (((ex & 63) << 2) + (ey >> 8)) & 0xFF,
        ey & 0xFF,
        cmd,
    ])


def pack_orientation(orientation):
    w, h = (NATIVE_H, NATIVE_W) if orientation >= 2 else (NATIVE_W, NATIVE_H)
    b = bytearray(16)
    b[5] = CMD_SET_ORIENTATION
    b[6] = orientation + 100
    b[7], b[8] = w >> 8, w & 0xFF
    b[9], b[10] = h >> 8, h & 0xFF
    return bytes(b)


def to_rgb565(img):
    """PIL image -> (H, W) uint16 array of RGB565 values."""
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    return ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)


def rgb565_bytes(arr):
    """(H, W) uint16 array -> little-endian row-major bytes (what the wire wants)."""
    return np.ascontiguousarray(arr).astype("<u2", copy=False).tobytes()


# ---- port discovery / transport -----------------------------------------------------------
def find_port():
    """Return the device node of the display, or None."""
    for pattern in ("/dev/turzx-lcd", "/dev/serial/by-id/*USB35INCHIPSV2*"):
        for p in glob.glob(pattern):
            return p
    for tty in sorted(glob.glob("/sys/class/tty/ttyACM*")):
        try:
            usb = os.path.realpath(os.path.join(tty, "device", ".."))
            with open(os.path.join(usb, "idVendor")) as f:
                vid = f.read().strip()
            with open(os.path.join(usb, "idProduct")) as f:
                pid = f.read().strip()
        except OSError:
            continue
        if (vid, pid) == USB_ID:
            return "/dev/" + os.path.basename(tty)
    return None


class _RawPort:
    """Raw termios port. Every write() is drained before returning so it leaves as its own transfer."""

    def __init__(self, dev):
        import termios
        self._termios = termios
        try:
            self.fd = os.open(dev, os.O_RDWR | os.O_NOCTTY)
        except OSError as e:
            raise LcdError(f"cannot open {dev}: {e}") from e
        a = termios.tcgetattr(self.fd)
        a[0] = 0                                             # no input translation / XON-XOFF
        a[1] = 0                                             # no OPOST (no \n -> \r\n)
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # 8N1, no RTS/CTS
        a[3] = 0                                             # raw: no echo, no canonical mode
        a[4] = a[5] = termios.B115200                        # ignored by CDC-ACM
        a[6][termios.VMIN] = 0
        a[6][termios.VTIME] = 5
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def write(self, data):
        mv = memoryview(data)
        try:
            while mv:
                n = os.write(self.fd, mv)
                mv = mv[n:]
            self._termios.tcdrain(self.fd)
        except OSError as e:
            raise LcdError(f"write failed: {e}") from e

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class Turzx:
    """Wire-protocol driver. Not thread-safe; one owner at a time."""

    def __init__(self, port=None, chunk=CHUNK):
        assert chunk % USB_PACKET == 0, "chunk must be a multiple of 64"
        port = port or find_port()
        if not port:
            raise LcdError("display not found (USB 1a86:5722) - plugged in? see `lsusb`")
        self.path = port
        self.chunk = chunk
        self.port = _RawPort(port)
        self.orientation = None

    def close(self):
        self.port.close()

    @property
    def size(self):
        if self.orientation is not None and self.orientation >= 2:
            return NATIVE_H, NATIVE_W
        return NATIVE_W, NATIVE_H

    def command(self, cmd, x=0, y=0, ex=0, ey=0):
        self.port.write(pack_cmd(cmd, x, y, ex, ey))     # a command is always its own write

    def set_orientation(self, orientation):
        self.port.write(pack_orientation(orientation))
        self.orientation = orientation
        time.sleep(0.1)

    def set_brightness(self, percent):
        percent = max(0, min(100, percent))
        self.command(CMD_SET_BRIGHTNESS, 255 - int(round(percent * 255 / 100)))   # 0 = brightest

    def screen_on(self):
        self.command(CMD_SCREEN_ON)

    def screen_off(self):
        self.command(CMD_SCREEN_OFF)

    def draw_raw(self, x, y, w, h, data):
        assert len(data) == w * h * 2, "pixel buffer size mismatch"
        self.command(CMD_DISPLAY_BITMAP, x, y, x + w - 1, y + h - 1)
        for o in range(0, len(data), self.chunk):
            self.port.write(data[o:o + self.chunk])

    def sync(self, nbytes=NATIVE_W * NATIVE_H * 2 + USB_PACKET):
        """Flush zero packets: completes any half-received bitmap; zero 'commands' are ignored."""
        z = bytes(USB_PACKET) * (self.chunk // USB_PACKET)
        for _ in range(-(-nbytes // len(z))):
            self.port.write(z)


class Display:
    """Shadow-framebuffer wrapper: ``present(img)`` sends only the pixels that changed."""

    def __init__(self, lcd, band=16):
        self.lcd = lcd
        self.band = band
        self.shadow = None
        self.stats_pixels = 0     # pixels sent by the last present()
        self.stats_rects = 0

    @property
    def size(self):
        return self.lcd.size

    def invalidate(self):
        """Forget what is on the panel; the next present() repaints everything."""
        self.shadow = None

    def present(self, img):
        w, h = self.lcd.size
        if img.size != (w, h):
            raise ValueError(f"image is {img.size}, display is {(w, h)}")
        new = to_rgb565(img)
        pixels = rects = 0
        if self.shadow is None:
            self.lcd.draw_raw(0, 0, w, h, rgb565_bytes(new))
            pixels, rects = w * h, 1
        else:
            diff = new != self.shadow
            for y0 in range(0, h, self.band):
                d = diff[y0:y0 + self.band]
                cols = np.flatnonzero(d.any(axis=0))
                if cols.size == 0:
                    continue
                rows = np.flatnonzero(d.any(axis=1))
                xa, xb = int(cols[0]), int(cols[-1])
                ya, yb = y0 + int(rows[0]), y0 + int(rows[-1])
                self.lcd.draw_raw(xa, ya, xb - xa + 1, yb - ya + 1,
                                  rgb565_bytes(new[ya:yb + 1, xa:xb + 1]))
                pixels += (xb - xa + 1) * (yb - ya + 1)
                rects += 1
        # only trust the shadow once the whole frame went out without an error
        self.shadow = new
        self.stats_pixels, self.stats_rects = pixels, rects
        return pixels
