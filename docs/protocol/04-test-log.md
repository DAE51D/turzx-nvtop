# 04 — Test log (Windows 11, 2026-11-13)

All tests used `tools/turzx.ps1` (PowerShell 7, `System.IO.Ports.SerialPort`, 115200 8N1, no handshake,
RTS+DTR asserted) on `COM5`. Results marked "photo" were confirmed from phone photos of the display.

## Method

1. Identified the device from PnP data (`VID_1A86&PID_5722`, serial `USB35INCHIPSV2`, driver `usbser`).
2. Took the candidate protocol from the open-source `turing-smart-screen-python` project
   (`library/lcd/lcd_comm_rev_a.py`), since the IDs match its "revision A".
3. Stopped `UsbMonitor.exe` (it holds the port exclusively) and sent commands directly.
4. Compared what appeared on the screen with what was sent.

## Timeline and results

| # | What was sent | Result |
|---|---|---|
| 1 | Killed `UsbMonitor.exe` (while it was live-updating), `HELLO` (6 × 0x45) | No reply (0 bytes in 800 ms) |
| 2 | Orientation 2, brightness 100 %, then a full 480×320 frame in 3840-byte chunks | A write **during the full frame** failed with "A device attached to the system is not functioning"; afterwards **every write timed out**. Device still enumerated, did not re-enumerate. Locked up. (The identical sequence worked in steps 8 and 10 after the re-plug.) |
| 3 | Tried handshake None / RTS, DTR on / off | All writes time out → firmware hung, not a flow-control issue |
| 4 | **User re-plugged the device** | Port accepts data again |
| 5 | `HELLO` | No reply |
| 6 | 280×30 strip at (20,40), default orientation | Accepted (not photographed) |
| 7 | Full portrait frame 320×480 | Accepted, 2.28 s (not photographed) |
| 8 | Orientation 2 → full 480×320 test pattern | **Photo: correct.** Landscape, not mirrored, yellow border on all four edges, corner labels in the right corners, R/G/B/W bars match labels → RGB565 little-endian confirmed |
| 9 | 260×30 strips at (100,230) and (100,270), 2080-byte chunks | **Photo: positioned correctly, right background colour, but contents scrambled** |
| 10 | Brightness 20 % for 2 s, then 100 % | Accepted, device healthy |
| 11 | Strip experiment 1 (table below) | **Photo** |
| 12 | Strip experiment 2 (table below) | **Photo** |
| 13 | Screen off (108), 1.5 s, screen on (109), orientation 3, full test pattern + 400×30 strip | Accepted. This is what was left on screen at the end — it should read "REVERSE LANDSCAPE (orient=3)" and be upside-down relative to the earlier landscape tests. Not photographed. |
| 14 | Throughput: five full frames with different chunk sizes | 1.83–1.88 s each |

### Strip experiment 1 — what breaks partial updates?

Each strip: navy bar, yellow 1-px outline, red `\` at left, green `/` at right, white label.
"gdi" = pixels converted by GDI+ `LockBits(Format16bppRgb565)`, "man" = converted by hand per pixel.

| Strip | x | w × h | Write chunk (bytes) | chunk mod 64 | Conversion | Result |
|---|---|---|---|---|---|---|
| A | 0 | 260 × 30 | 2080 | 32 | gdi | scrambled |
| B | 100 | 260 × 30 | 2080 | 32 | gdi | scrambled |
| C | 100 | 260 × 30 | 2080 | 32 | man | scrambled |
| D | 100 | 256 × 30 | 2048 | 0 | man | **clean** |
| E | 96 | 256 × 32 | 2048 | 0 | man | **clean** |
| F | 100 | 260 × 30 | 15600 (single write) | — | man | **clean** |
| G | 100 | 260 × 30 | 64 | 0 | man | **clean** |
| H | 101 | 259 × 31 | 2072 | 24 | man | scrambled |

Conclusions: not the pixel conversion (B vs C), not the x offset (A vs B), not the width itself
(C vs F vs G: same image, only the chunking differs). The single variable that predicts failure is
**a write whose length is not a multiple of 64 bytes occurring before the end of the image**.
Full-screen frames never showed the problem because 3840 is a multiple of 64.

### Strip experiment 2 — framing details and recovery

| Strip | What | Result |
|---|---|---|
| (bg) | Full black frame as one 307 200-byte write | clean |
| I | 256×30, **command and pixels concatenated in one write** | Drawn, but contents shifted left ~29 px with the left end wrapped round to the right → the 58 bytes sharing the command's packet were dropped |
| — | 4 × 64 zero bytes | (resync) |
| J | 256×30, normal | **clean** → resync worked |
| K | 259×31 at (101,84), single write | **clean** → odd sizes/offsets are fine |
| M | 260×30, 2080-byte chunks (known bad) | scrambled, as expected |
| — | 8 × 64 zero bytes | (resync) |
| N | 260×30, normal | **clean** → resync worked |
| O | 260×30, 4096-byte chunks | **clean** |
| P | 37×23 at (3,250), single write | **clean** |
| Q | 260×30, single write | **clean** |

## Interpretation

* Hypothesis that fits everything: in bitmap mode the firmware consumes its 64-byte USB receive buffer
  per packet regardless of how many bytes the packet really carried, and in command mode it looks only
  at the first 6 bytes of a packet. A short packet in mid-image therefore injects stale bytes (scramble)
  and makes the device finish the image early; the leftover real pixel bytes are then parsed as commands.
  This is an inference from behaviour, not from reading firmware.
* The lock-up in step 2 happened with correctly framed data, so bad chunking was not the trigger there.
  The most plausible cause: `UsbMonitor.exe` had just been killed while live-updating, leaving the device
  part-way through an image; my commands and pixels were then consumed out of alignment and some pixel
  bytes were executed as commands (possibly `RESET`, or something fatal). I did not reproduce the lock-up,
  so this is unconfirmed. Deliberate framing violations in later tests scrambled images but never hung
  the device. Practical rule: **never kill a writer mid-image, and send a zero-flush `sync` before the
  first command of a session.**

## Not tested / open questions

* Orientation 1 (reverse portrait); visual confirmation of orientations 0 and 3.
* `RESET` (101), `CLEAR` (102), `TO_BLACK` (103) — deliberately not sent.
* Whether orientation and brightness persist across a power cycle.
* Whether any command produces a reply (none seen).
* Minimum safe gap between commands (none was needed in these tests).
* Everything Linux-side: device node, ModemManager interference, kernel write segmentation.
* Vendor `.data` theme format and the meaning of `code.ini` (`64`).

## State the machine was left in

* `UsbMonitor.exe` is **not running** (I stopped it to free COM5). Start it again from this folder to get
  the vendor display back.
* The display shows the reverse-landscape test pattern from step 13.
