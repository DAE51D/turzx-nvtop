"""Driver for the "SmartCool" / QTKeJi 3.5" USB LCD (USB 2a55:9990, sold as an AIDA64 secondary screen).

Unlike the Turzx (a CDC-ACM serial port) this is a vendor-class device with two bulk endpoints that speaks an
AX206-style USB mass-storage "bulk-only" protocol: one 31-byte CBW carrying a vendor CDB, the pixel payload,
then a 13-byte CSW.  See docs/protocol/05-smartcool.md.

Properties of this firmware that shape the code:

* The only command that works is BLIT (CDB op 0x12).  SETPROPERTY (brightness) and GETLCD *time out and
  wedge the endpoint*, so brightness is a no-op and screen-off is a black frame.
* No partial updates (they crash it), so every update is a whole 480x320 frame (~0.4 s on USB 1.1).  Hence
  ``FullFrameDisplay`` rather than the band-diffing ``Display``: it only decides *whether* to send a frame.
* Pixels are RGB565 **big-endian** (the Turzx is little-endian).
* If a transaction is abandoned before its CSW is read, the endpoint stalls until a mass-storage reset
  plus a port reset.  ``recover()`` does that; a failed frame is retried once after it.
"""

import glob
import os
import struct
import time

import numpy as np

from .lcd import Display, LcdError, to_rgb565

USB_ID = ("2a55", "9990")
VID, PID = 0x2A55, 0x9990
EP_OUT, EP_IN = 0x01, 0x81
NATIVE_W, NATIVE_H = 480, 320
CSW_RETRIES = 5
OP_BLIT = 0x12


def find_device():
    """Sysfs path of the display, or None. Needs no USB library, so it is safe to call everywhere."""
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            with open(os.path.join(d, "idVendor")) as f:
                vid = f.read().strip()
            with open(os.path.join(d, "idProduct")) as f:
                pid = f.read().strip()
        except OSError:
            continue
        if (vid, pid) == USB_ID:
            return d
    return None


def pack_cbw(
    data_len, op=OP_BLIT, x0=0, y0=0, x1=NATIVE_W, y1=NATIVE_H, tag=b"\xde\xad\xbe\xef"
):
    """31-byte CBW for a BLIT of the rectangle [x0,x1) x [y0,y1)."""
    cdb = bytearray(16)
    cdb[0] = 0xCD
    cdb[5] = 0x06
    cdb[6] = op
    struct.pack_into("<HHHH", cdb, 7, x0, y0, x1 - 1, y1 - 1)
    return (
        b"USBC"
        + tag
        + struct.pack("<I", data_len)
        + bytes([0x00, 0x00, 0x10])
        + bytes(cdb)
    )


def rgb565_be_bytes(arr):
    """(H, W) uint16 array -> big-endian row-major bytes (what this panel wants)."""
    return np.ascontiguousarray(arr).astype(">u2", copy=False).tobytes()


class SmartCool:
    """Wire-protocol driver exposing the same surface the daemon uses on ``lcd.Turzx``."""

    def __init__(self, timeout_ms=4000):
        try:
            import usb.core
            import usb.util
        except ImportError as e:
            raise LcdError(
                "pyusb is required for the SmartCool display (apt install python3-usb)"
            ) from e
        self._usb, self._util = usb.core, usb.util
        self.timeout = timeout_ms
        self.orientation = 2
        self.dev = None
        self.path = "usb:2a55:9990"
        self._open()

    # ---- lifecycle ---------------------------------------------------------------------------
    def _open(self):
        dev = self._usb.find(idVendor=VID, idProduct=PID)
        if dev is None:
            raise LcdError(
                "display not found (USB 2a55:9990) - plugged in? see `lsusb`"
            )
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except (NotImplementedError, self._usb.USBError):
            pass
        try:
            dev.set_configuration()
        except self._usb.USBError:
            pass
        try:
            self._util.claim_interface(dev, 0)
        except self._usb.USBError as e:
            raise LcdError(
                f"cannot open the display: {e} (udev rule installed? another program using it?)"
            ) from e
        self.dev = dev
        self._clear_halts()

    def close(self):
        if self.dev is not None:
            try:
                self._util.release_interface(self.dev, 0)
            except self._usb.USBError:
                pass
            self._util.dispose_resources(self.dev)
            self.dev = None

    def _clear_halts(self):
        for ep in (EP_OUT, EP_IN):
            try:
                self.dev.clear_halt(ep)
            except self._usb.USBError:
                pass

    @property
    def size(self):
        return NATIVE_W, NATIVE_H  # rotation is done in software (see FullFrameDisplay)

    # ---- the Turzx-compatible surface ----------------------------------------------------------
    def set_orientation(self, orientation):
        self.orientation = orientation

    def set_brightness(self, percent):
        pass  # SETPROPERTY wedges this firmware; the backlight is fixed

    def screen_on(self):
        pass

    def screen_off(self):
        """No off command exists; show black so an idle panel does not burn in."""
        self.draw_frame(bytes(NATIVE_W * NATIVE_H * 2))

    def sync(self, *_):
        self.recover()

    # ---- transport ------------------------------------------------------------------------------
    def recover(self):
        """Mass-storage reset, clear stalls, reset the port: un-wedges an abandoned transaction."""
        if self.dev is None:
            return
        for step in (
            lambda: self.dev.ctrl_transfer(0x21, 0xFF, 0, 0, None, timeout=500),
            self._clear_halts,
            self.dev.reset,
        ):
            try:
                step()
            except self._usb.USBError:
                pass
        time.sleep(0.3)
        self._clear_halts()

    def _frame_once(self, data):
        self.dev.write(EP_OUT, pack_cbw(len(data)), timeout=self.timeout)
        self.dev.write(EP_OUT, data, timeout=max(self.timeout, 15000))
        last = None
        for _ in range(CSW_RETRIES):
            try:
                csw = bytes(self.dev.read(EP_IN, 13, timeout=2000))
            except self._usb.USBError as e:
                last = e
                continue
            if len(csw) >= 13 and csw[:4] == b"USBS":
                if csw[12] != 0:
                    raise LcdError(f"display reported status {csw[12]}")
                return
            last = LcdError(f"bad CSW {csw.hex()}")
        raise LcdError(f"no CSW from the display: {last}")

    def draw_frame(self, data):
        """Send one whole 480x320 big-endian RGB565 frame; recover and retry once if the endpoint wedged."""
        assert len(data) == NATIVE_W * NATIVE_H * 2, "frame buffer size mismatch"
        if self.dev is None:
            raise LcdError("display is closed")
        try:
            self._frame_once(data)
        except (self._usb.USBError, LcdError) as first:
            try:
                self.recover()
                self._frame_once(data)
            except (self._usb.USBError, LcdError) as e:
                raise LcdError(f"write failed: {first}; after recovery: {e}") from e


class FullFrameDisplay(Display):
    """Like ``lcd.Display`` but for a panel without partial updates: send a whole frame, and only when the
    image changed. The panel has no orientation command, so rotation 180 is done here in software.
    Which way up a panel looks also depends on its cradle / plug position, so it has its own
    ``[display] rotation_smartcool`` setting."""

    def __init__(self, lcd):
        super().__init__(lcd)
        self.rotate = lcd.orientation == 3

    def present(self, img):
        w, h = self.lcd.size
        if img.size != (w, h):
            raise ValueError(f"image is {img.size}, display is {(w, h)}")
        new = to_rgb565(img)
        if self.rotate:
            new = new[::-1, ::-1]
        if self.shadow is not None and np.array_equal(new, self.shadow):
            self.stats_pixels = self.stats_rects = 0
            return 0
        self.lcd.draw_frame(rgb565_be_bytes(new))
        self.shadow = new
        self.stats_pixels, self.stats_rects = w * h, 1
        return w * h
