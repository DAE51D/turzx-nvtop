#!/usr/bin/env python3
"""Hardware framing torture test (needs the panel). Run:  python3 tests/hw_striptest.py

Draws odd-sized rectangles at odd offsets. Every strip must show a readable label, an intact
yellow outline, a red "\\" at the left end and a green "/" at the right end. Anything scrambled
means the write segmentation is wrong (try a different CHUNK in turzx_nvtop/lcd.py).
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image, ImageDraw  # noqa: E402

from turzx_nvtop.lcd import LANDSCAPE, Display, Turzx  # noqa: E402
from turzx_nvtop.render import font  # noqa: E402


def strip(w, h, label):
    img = Image.new("RGB", (w, h), "navy")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h - 1), outline="yellow")
    d.line((0, 0, h - 1, h - 1), fill="red")
    d.line((w - 1, 0, w - h, h - 1), fill="lime")
    d.text((34, 5), label, font=font(13), fill="white")
    return img


def main():
    lcd = Turzx()
    try:
        lcd.sync()
        lcd.set_orientation(LANDSCAPE)
        lcd.set_brightness(70)
        lcd.screen_on()
        disp = Display(lcd)
        canvas = Image.new("RGB", (480, 320), "black")
        disp.present(canvas)                      # full frame first
        y = 4
        for w, h, x in ((260, 30, 100), (259, 31, 101), (256, 30, 96), (37, 23, 3), (333, 29, 77), (260, 30, 100)):
            canvas.paste(strip(w, h, "x%d y%d w%d h%d" % (x, y, w, h)), (x, y))
            t = time.time()
            n = disp.present(canvas)              # delta path: sends just the new strip
            print(f"strip {w}x{h}@{x},{y}: {n} px, {disp.stats_rects} rects, {time.time() - t:.3f}s")
            y += h + 10
        ImageDraw.Draw(canvas).text((100, y), "striptest done", font=font(14, True), fill="orange")
        disp.present(canvas)
    finally:
        lcd.close()


if __name__ == "__main__":
    main()
