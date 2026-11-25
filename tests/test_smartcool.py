import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from turzx_nvtop import smartcool  # noqa: E402


class FakePanel:
    size = (480, 320)
    orientation = 2

    def __init__(self):
        self.frames = []

    def draw_frame(self, data):
        assert len(data) == 480 * 320 * 2
        self.frames.append(data)


class Protocol(unittest.TestCase):
    def test_cbw(self):
        cbw = smartcool.pack_cbw(480 * 320 * 2)
        self.assertEqual(len(cbw), 31)
        self.assertEqual(cbw[:4], b"USBC")
        self.assertEqual(cbw[8:12], (307200).to_bytes(4, "little"))
        self.assertEqual(cbw[12:15], bytes([0x00, 0x00, 0x10]))
        # CDB: cd 00 00 00 00 06 12 | x0 y0 x1-1 y1-1 (LE16)
        self.assertEqual(cbw[15:22], bytes([0xCD, 0, 0, 0, 0, 6, 0x12]))
        self.assertEqual(cbw[22:30], bytes([0, 0, 0, 0, 0xDF, 0x01, 0x3F, 0x01]))

    def test_rgb565_is_big_endian(self):
        px = Image.new("RGB", (2, 1))
        px.putdata([(255, 0, 0), (0, 0, 255)])
        from turzx_nvtop.lcd import to_rgb565

        self.assertEqual(
            smartcool.rgb565_be_bytes(to_rgb565(px)), bytes([0xF8, 0x00, 0x00, 0x1F])
        )


class Presenter(unittest.TestCase):
    def test_skips_unchanged_frames_and_sends_whole_frames(self):
        d = smartcool.FullFrameDisplay(FakePanel())
        img = Image.new("RGB", (480, 320), (10, 20, 30))
        self.assertEqual(d.present(img), 480 * 320)
        self.assertEqual(d.present(img), 0)
        img.putpixel((5, 5), (255, 255, 255))
        self.assertEqual(d.present(img), 480 * 320)
        self.assertEqual(len(d.lcd.frames), 2)
        d.invalidate()
        self.assertEqual(d.present(img), 480 * 320)

    def test_rotation_180(self):
        panel = FakePanel()
        panel.orientation = 3
        d = smartcool.FullFrameDisplay(panel)
        img = Image.new("RGB", (480, 320))
        img.putpixel((0, 0), (255, 0, 0))
        d.present(img)
        a = np.frombuffer(panel.frames[0], dtype=">u2").reshape(320, 480)
        self.assertEqual(int(a[319, 479]), 0xF800)
        self.assertEqual(int(a[0, 0]), 0)
        panel.orientation = 2
        panel.frames.clear()
        d = smartcool.FullFrameDisplay(panel)
        d.present(img)
        a = np.frombuffer(panel.frames[0], dtype=">u2").reshape(320, 480)
        self.assertEqual(int(a[0, 0]), 0xF800)


if __name__ == "__main__":
    unittest.main()
