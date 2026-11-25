# SmartCool / QTKeJi 3.5" USB LCD (USB 2a55:9990)

A second supported panel. It is sold as an "AIDA64 secondary screen" and shows a built-in demo
("SmartCool LCD for AIDA64") as soon as it is powered, until a host program sends a frame.

## Identification

```
ID 2a55:9990 QTKeJi.Ltd SmatCool      serial 20221212, bcdDevice 2.00, USB 1.1 full speed
Interface 0: class 0xDC / 0xA0 / 0xB0 (vendor), 2 endpoints:
  0x01 bulk OUT, 0x81 bulk IN, 64-byte packets
```

No kernel driver binds, no tty appears. Linux treats it as an unclaimed vendor device, so the driver talks
to it from user space with libusb (`pyusb`, `apt install python3-usb`). Panel: 480x320 landscape.

## Protocol

It speaks the AX206 "dpf-ax" dialect: USB mass-storage bulk-only framing carrying a vendor CDB.

1. **CBW**, 31 bytes to EP 0x01: `"USBC"`, tag `de ad be ef`, `LE32 data_length`, flags `00` (data out),
   LUN `00`, CDB length `10`, then the 16-byte CDB.
2. **CDB** for BLIT: `cd 00 00 00 00 06 12`, then `x0, y0, x1-1, y1-1` as little-endian 16-bit, padding.
3. **Pixels** to EP 0x01: `width*height` RGB565 **big-endian** (the Turzx is little-endian).
4. **CSW**, 13 bytes from EP 0x81: `"USBS"`, tag, `LE32 residue`, status (`0` = OK). It sometimes needs a
   few read attempts; the driver tries up to 5 times.

## Firmware quirks (verified on hardware)

- **BLIT is the only usable command.** SETPROPERTY (brightness) and GETLCD are reported to wedge the
  endpoint on this firmware family, so the driver never sends them: no brightness control, and "screen off"
  is a black frame.
- **Whole frames only.** Partial-rectangle updates are documented to crash this firmware (SimHub disables
  them for it). A 480x320 frame (307,200 bytes) takes ~0.42 s, about 2.4 fps. The driver only sends a frame
  when the image changed.
- **Abandoned transactions wedge it.** If a frame is interrupted before the CSW is read, the next write
  times out. Recovery needs no replug: mass-storage reset (class request `0xFF`), clear halt on both
  endpoints, then a USB port reset. The driver does this and retries the frame once.
- **Clear halts on open**, or the first transaction after a previous owner may fail.
- **Single owner.** Only one program can hold it, so stop other users (AIDA64, lcd4linux...) first.
- **No autosuspend.** The udev rule sets `power/control=on`.

## Prior art

dreamlayers/dpf-ax (AX206 command set), SimHub's AX206 notes (SmartCool lacks partial draws), and the
AIDA64 forum threads that identify `2A55-9990` as the "SmartCool LCD" module (rated 800x480 there; the unit
tested here is 480x320).

## In this project

`turzx_nvtop/smartcool.py`: `SmartCool` (wire protocol, same surface as `lcd.Turzx`) and
`FullFrameDisplay` (full-frame presenter with software 180-degree rotation). `[display] backend = auto`
picks whichever panel is plugged in, preferring the Turzx if both are.
