import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from turzx_nvtop import lcd  # noqa: E402


class FakeLcd:
    size = (480, 320)

    def __init__(self):
        self.rects = []

    def draw_raw(self, x, y, w, h, data):
        assert len(data) == w * h * 2
        self.rects.append((x, y, w, h))


class Protocol(unittest.TestCase):
    # vectors from docs/protocol/02-protocol.md, verified on the real device
    def test_commands(self):
        self.assertEqual(lcd.pack_cmd(197, 100, 230, 359, 259), bytes([25, 14, 101, 157, 3, 197]))
        self.assertEqual(lcd.pack_cmd(197, 0, 0, 479, 319), bytes([0, 0, 7, 125, 63, 197]))
        self.assertEqual(lcd.pack_cmd(110, 255), bytes([63, 192, 0, 0, 0, 110]))
        self.assertEqual(lcd.pack_cmd(108), bytes([0, 0, 0, 0, 0, 108]))

    def test_orientation(self):
        self.assertEqual(lcd.pack_orientation(2), bytes([0, 0, 0, 0, 0, 121, 102, 1, 224, 1, 64, 0, 0, 0, 0, 0]))
        self.assertEqual(lcd.pack_orientation(0), bytes([0, 0, 0, 0, 0, 121, 100, 1, 64, 1, 224, 0, 0, 0, 0, 0]))

    def test_rgb565(self):
        px = Image.new("RGB", (4, 1))
        px.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])
        self.assertEqual(lcd.rgb565_bytes(lcd.to_rgb565(px)), bytes([0x00, 0xF8, 0xE0, 0x07, 0x1F, 0x00, 0xFF, 0xFF]))


class DeltaPresent(unittest.TestCase):
    def setUp(self):
        self.fake = FakeLcd()
        self.disp = lcd.Display(self.fake)
        self.img = Image.new("RGB", (480, 320), "black")

    def test_first_frame_is_full(self):
        self.assertEqual(self.disp.present(self.img), 480 * 320)
        self.assertEqual(self.fake.rects, [(0, 0, 480, 320)])

    def test_identical_frame_sends_nothing(self):
        self.disp.present(self.img)
        self.fake.rects.clear()
        self.assertEqual(self.disp.present(self.img.copy()), 0)
        self.assertEqual(self.fake.rects, [])

    def test_single_pixel_change_is_a_1x1_rect(self):
        self.disp.present(self.img)
        self.fake.rects.clear()
        self.img.putpixel((123, 45), (255, 255, 255))
        self.assertEqual(self.disp.present(self.img), 1)
        self.assertEqual(self.fake.rects, [(123, 45, 1, 1)])

    def test_changes_in_two_bands_make_two_tight_rects(self):
        self.disp.present(self.img)
        self.fake.rects.clear()
        self.img.paste((255, 0, 0), (10, 5, 20, 8))      # 10x3 at (10,5)
        self.img.paste((0, 255, 0), (300, 200, 310, 204))  # 10x4 at (300,200)
        self.disp.present(self.img)
        self.assertEqual(sorted(self.fake.rects), [(10, 5, 10, 3), (300, 200, 10, 4)])

    def test_invalidate_forces_full_repaint(self):
        self.disp.present(self.img)
        self.fake.rects.clear()
        self.disp.invalidate()
        self.disp.present(self.img)
        self.assertEqual(self.fake.rects, [(0, 0, 480, 320)])

    def test_wrong_size_rejected(self):
        with self.assertRaises(ValueError):
            self.disp.present(Image.new("RGB", (100, 100)))


class Rendering(unittest.TestCase):
    def test_all_screens_render_with_demo_data_and_without_data(self):
        from turzx_nvtop.config import Config
        from turzx_nvtop.daemon import demo_state, make_state
        from turzx_nvtop.render import RENDERERS, View
        cfg = Config(None)
        for state in (demo_state(cfg), make_state(cfg)):
            s, h, age, err = state.snapshot()
            for name, fn in RENDERERS.items():
                img = fn(View(cfg, s, h, age, err))
                self.assertEqual(img.size, (480, 320), name)
                self.assertTrue(np.asarray(img).any(), name)


if __name__ == "__main__":
    unittest.main()
