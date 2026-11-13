# 01 — Device identification

## What Windows reports (observed 2026-11-13)

| Property | Value |
|---|---|
| PnP instance ID | `USB\VID_1A86&PID_5722\USB35INCHIPSV2` |
| USB Vendor ID | `0x1A86` (QinHeng / WCH) |
| USB Product ID | `0x5722` |
| USB serial number string | `USB35INCHIPSV2` |
| Bus-reported device description | `UsbMonitor` |
| Windows friendly name | `USB Serial Device (COM5)` |
| Windows driver / service | `usbser` (Microsoft in-box CDC-ACM driver — no vendor driver) |
| Modem lines when open | CTS = low, DSR = low, CD = low (the device does not drive them) |

So the device is a standard **USB CDC-ACM virtual serial port**. Nothing about it is HID or display-class,
despite the vendor app's assembly being called `usb_hid`.

## Hardware (from public sources, not opened/inspected by me)

* Sold as "Turzx" / "Turing Smart Screen" 3.5" IPS, 320 × 480 native (portrait), USB-C.
* MCU reported as WCH **CH552T** (8-bit 8051, USB full-speed, 64-byte bulk packets). This matters:
  full-speed bulk is why a full frame takes ~1.8 s and why 64-byte boundaries matter (see protocol doc).
* The open-source project calls this model **"Turing Smart Screen 3.5" — revision A"**, serial IDs
  `USB35INCHIPS` and `USB35INCHIPSV2`.
* Sub-revision probe: sending six `0x45` bytes (`HELLO`) gets **no reply** from this unit. Per the
  open-source library, units that reply `01 01 01 01 01 01` / `02…` / `03…` are the "UsbMonitor"
  3.5"/5"/7" sub-revisions; no reply = plain "Turing 3.5"". This unit: no reply, 320 × 480.

## Vendor software in this folder

| File | Notes |
|---|---|
| `UsbMonitor.exe` | .NET Framework 4.5 WinForms app, assembly name `usb_hid`, obfuscated with Dotfuscator (identifiers renamed to CJK characters). It holds the COM port open exclusively while running. |
| `config\*.data` | Vendor theme files (background + widget layout). Format not analysed — not needed to drive the display. |
| `3.5\*.png` | Stock background images, usable as-is as backgrounds on Linux. |
| `code.ini` | Contains `64`; vendor troubleshooting says to change to `0` or `8192` if stuck initialising. Meaning unknown (not analysed). |

I started an IL-level disassembly of `UsbMonitor.exe` to cross-check the command bytes, but abandoned it
once the protocol was confirmed directly on the device; nothing in these notes comes from the vendor binary.

## Finding it on Linux (expected — not yet run on Linux)

```bash
lsusb -d 1a86:5722
```

```bash
ls -l /dev/serial/by-id/
```

```bash
sudo dmesg | grep -i -E 'cdc_acm|ttyACM|1a86'
```

Expected: a `cdc_acm` line and a `/dev/ttyACM0` (number may differ), plus a stable symlink like
`/dev/serial/by-id/usb-…USB35INCHIPSV2…-if00`.

Full descriptor dump (worth saving into this folder once on Linux — endpoint sizes confirm the
64-byte packet assumption):

```bash
sudo lsusb -v -d 1a86:5722
```
