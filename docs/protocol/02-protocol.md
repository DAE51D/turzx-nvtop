# 02 — Wire protocol

Everything is sent host → device over the CDC serial port. The device sends nothing back
(on this unit even `HELLO` gets no reply), so there are **no acknowledgements** — you cannot detect
errors from the stream; correctness depends on sending exactly the right number of bytes.

## Serial settings

| Setting | Value |
|---|---|
| Baud rate | 115200 (nominal — it is a virtual port, the value is ignored by USB) |
| Framing | 8 data bits, no parity, 1 stop bit |
| Flow control | None needed. Tests here used no handshake with RTS and DTR asserted. The open-source library opens with RTS/CTS enabled; both work on Windows. |
| Mode | **Raw binary**. On Linux the tty must be in raw mode (no `OPOST`, no `ICANON`, no XON/XOFF) or bytes like `0x0A`/`0x11`/`0x13` in pixel data will be altered. pyserial does this for you; `tools/turzx.py` does it by hand. |

## Coordinate system

* Native panel: **320 × 480 (portrait)**.
* After a set-orientation command the device rotates for you; coordinates are then in the rotated space:

| Orientation value | Name | Logical size | Tested |
|---|---|---|---|
| 0 | Portrait | 320 × 480 | sent OK, not photographed |
| 1 | Reverse portrait (180°) | 320 × 480 | not tested |
| 2 | Landscape | 480 × 320 | **verified** |
| 3 | Reverse landscape (180°) | 480 × 320 | **verified sent**, see test log |

* Origin (0,0) is the top-left of the logical screen; x grows right, y grows down.
* All coordinates fit in 10 bits (0–1023).

## The 6-byte command packet

Four 10-bit unsigned fields `x`, `y`, `ex`, `ey` are packed MSB-first into 40 bits (5 bytes), followed by
the command byte:

```
bit:   39........30 29........20 19........10 9..........0
field: [    x     ] [    y     ] [    ex    ] [    ey    ]   + cmd (1 byte)

byte0 =  x >> 2
byte1 = ((x  & 0x03) << 6) | (y  >> 4)
byte2 = ((y  & 0x0F) << 4) | (ex >> 6)
byte3 = ((ex & 0x3F) << 2) | (ey >> 8)
byte4 =   ey & 0xFF
byte5 =   command
```

Fields that a command does not use are sent as 0.

### Command table

| Cmd (dec) | Hex | Name | Arguments | Extra payload | Status |
|---|---|---|---|---|---|
| 69 | 0x45 | HELLO | all six bytes are `0x45` | — | Sent; **no reply** on this unit |
| 101 | 0x65 | RESET | none | — | **Not tested.** Per the open-source lib the device reboots and re-enumerates (close port, wait ~5 s, reopen; port name may change). Its wiki says some variants of this model should *not* be reset at startup. |
| 102 | 0x66 | CLEAR (to white) | none | — | Not tested. The lib notes it only works correctly in portrait, so it switches to portrait first. Drawing a solid rectangle is a safe substitute. |
| 103 | 0x67 | TO_BLACK | none | — | Not tested (also marked untested in the lib) |
| 108 | 0x6C | SCREEN_OFF | none | — | Sent OK |
| 109 | 0x6D | SCREEN_ON | none | — | Sent OK (also used as a harmless "is the port still accepting data" probe) |
| 110 | 0x6E | SET_BRIGHTNESS | `x` = level, **0 = brightest … 255 = darkest** | — | Sent OK |
| 121 | 0x79 | SET_ORIENTATION | none in the 6 bytes | 10 more bytes, see below | **Verified** |
| 197 | 0xC5 | DISPLAY_BITMAP | `x,y` = top-left, `ex,ey` = bottom-right **inclusive** | `w*h*2` bytes of pixels | **Verified** |

Brightness from a percentage: `level = 255 - round(percent * 255 / 100)`.

### SET_ORIENTATION — 16 bytes total, sent as one write

```
offset: 0  1  2  3  4  5    6             7     8     9     10    11..15
value:  00 00 00 00 00 79   100+orient    W_hi  W_lo  H_hi  H_lo  00 00 00 00 00
```

`W`/`H` are the logical size for that orientation (320×480 for 0/1, 480×320 for 2/3), big-endian.

| Orientation | Exact bytes |
|---|---|
| 0 portrait | `00 00 00 00 00 79 64 01 40 01 E0 00 00 00 00 00` |
| 1 reverse portrait | `00 00 00 00 00 79 65 01 40 01 E0 00 00 00 00 00` |
| 2 landscape | `00 00 00 00 00 79 66 01 E0 01 40 00 00 00 00 00` |
| 3 reverse landscape | `00 00 00 00 00 79 67 01 E0 01 40 00 00 00 00 00` |

The orientation only affects subsequent drawing; what is already on screen stays where it is.
The host must remember the orientation — the device cannot be queried. Set it every time you open the port.
(Power-on default appears to be portrait; whether the setting survives a power cycle was not tested.)

### DISPLAY_BITMAP — command + pixels

1. Send the 6-byte command with `x, y, ex = x + w - 1, ey = y + h - 1`.
2. Send exactly `w × h × 2` bytes of pixel data.

Pixel format:

* **RGB565**, 16 bits per pixel: `RRRRR GGGGGG BBBBB` (R in the top 5 bits).
* **Little-endian** on the wire: low byte first. Pure red `0xF800` is sent as `00 F8`.
* Row-major, top row first, left to right, **no row padding**.

```
value = ((R >> 3) << 11) | ((G >> 2) << 5) | (B >> 3)
wire  = [value & 0xFF, value >> 8]
```

| Colour | 565 value | Wire bytes |
|---|---|---|
| Red | 0xF800 | `00 F8` |
| Green | 0x07E0 | `E0 07` |
| Blue | 0x001F | `1F 00` |
| White | 0xFFFF | `FF FF` |
| Black | 0x0000 | `00 00` |

The rectangle may be any size from 1×1 up to the full screen, at any position (odd widths/heights and
odd offsets verified: 259×31 at (101,84), 37×23 at (3,250)). The rectangle must lie inside the logical
screen — clip on the host.

There is no transparency or blending on the device. To put text "over" a background, composite on the
host (crop the background region, draw the text on it, send the result).

## USB packet framing rules (IMPORTANT)

The firmware does not treat the serial data as a pure byte stream; it is sensitive to where USB
packet boundaries fall (full-speed bulk, 64 bytes per packet). Determined experimentally
(see [04-test-log.md](04-test-log.md)):

1. **A command must be its own write.** If pixel data is appended to the same write as the 6-byte
   command, the rest of that first 64-byte packet (58 bytes = 29 pixels) is discarded: the image appears
   shifted/wrapped by 29 pixels and the device is left waiting for 58 more bytes.
2. **Pixel data must reach the device in full 64-byte packets; only the final packet of an image may be
   short.** In practice: write the pixel buffer in chunks whose size is a **multiple of 64 bytes**
   (or as one single write). Chunk sizes of 64, 2048, 3840, 4096, and "everything at once" all work.
   Chunk sizes of 2080 and 2072 (not multiples of 64) scramble the image.
3. After a framing violation the device's idea of "where the next command starts" is wrong, so it may
   interpret pixel bytes as commands. A mis-aligned stream is the most plausible cause of the one
   **lock-up** seen during testing (the device stopped accepting data entirely and needed a physical
   re-plug) — in that case the mis-alignment came from the vendor app being killed mid-image, not from
   bad chunking. See the test log.

Note on the open-source library: it sends pixel data in chunks of `width × 8` bytes. That is a multiple
of 64 only when the width is a multiple of 8 — which is exactly the pattern that failed here
(width 260 → 2080-byte chunks). Whether that bites on Linux depends on how the kernel re-segments
writes; see [03-linux-setup.md](03-linux-setup.md#known-risk-write-segmentation).

### Resynchronising without re-plugging

Writing 64-byte packets of zeros recovers a de-synchronised (but not locked-up) device: zeros complete
any half-received bitmap (as black pixels), and once the device is back in command mode an all-zero
packet is ignored. Verified twice (after a rule-1 violation and after a rule-2 violation the next
image drew cleanly).

Worst case a full-screen bitmap was pending, so a guaranteed resync is 307 200 bytes of zeros
(~1.8 s). `turzx.py sync` does this. Doing it once right after opening the port is a cheap way to
survive a previous program having been killed mid-frame.

If the device stops accepting writes altogether (write times out), only a USB re-plug
(or possibly unbind/rebind of the USB device on Linux) brings it back.

## Timing / throughput (measured on Windows)

| Operation | Time |
|---|---|
| Full frame, 480×320 = 307 200 bytes | ≈ 1.83 s (≈ 168 kB/s), independent of write chunk size |
| Strip 260×30 = 15 600 bytes | ≈ 0.1 s |
| First full frame right after screen-on + orientation change | one run took 6.9 s; not reproduced |

So: ~0.5 fps for full frames. Do what the vendor app does — send the background **once**, then
update only the small rectangles that change (a 100×30 number field is 6 000 bytes ≈ 36 ms).
A budget of roughly 150 000 pixels/s total is realistic.

## Worked examples (exact bytes)

Set landscape, full brightness, then draw a 2×1 image (red, blue) at x=10, y=20:

```
00 00 00 00 00 79 66 01 E0 01 40 00 00 00 00 00      set orientation 2 (one write)
00 00 00 00 00 6E                                    brightness: x=0 (brightest), cmd 110
02 81 40 2C 14 C5                                    bitmap x=10 y=20 ex=11 ey=20, cmd 197
00 F8 1F 00                                          2 pixels: red, blue  (separate write)
```

Other command encodings (useful as unit-test vectors; these are asserted in `turzx.py selftest`):

| Call | Bytes |
|---|---|
| bitmap, full landscape screen (0,0)-(479,319) | `00 00 07 7D 3F C5` |
| bitmap, full portrait screen (0,0)-(319,479) | `00 00 04 FD DF C5` |
| bitmap (100,230)-(359,259) | `19 0E 65 9D 03 C5` |
| brightness darkest (x=255) | `3F C0 00 00 00 6E` |
| screen off / on | `00 00 00 00 00 6C` / `00 00 00 00 00 6D` |

## Minimal pseudo-code

```python
port = open_raw_serial("/dev/ttyACM0")
port.write(bytes(64) * 4801)                       # optional resync
port.write(orientation_packet(2))                  # landscape
port.write(cmd(110, x=0))                          # brightness max
port.write(cmd(197, 0, 0, 479, 319))               # full-screen bitmap header (own write!)
for chunk in chunks(rgb565_le(background), 1024):  # multiples of 64
    port.write(chunk)
# later, repeatedly:
port.write(cmd(197, x, y, x+w-1, y+h-1)); port.write(rgb565_le(patch))
```
