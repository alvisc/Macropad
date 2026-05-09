#!/usr/bin/env python3
"""
Send MacroPad LED mode command to VID:PID 514c:8851.

LED FRAME FORMAT (Extended format, FE marker):
    Byte 0:        Report ID (0x03)
    Byte 1:        Marker (0xFE = extended report)
    Byte 2:        LED action code (0xB0)
    Byte 3:        Layer (0x01 = layer 1)
    Byte 4:        Key Type (0x08 = LED)
    Byte 5..10:    Reserved (0x00)
    Byte 11:       Count indicator (0x01)
    Byte 12:       Mode + Color byte (combined)

MODE + COLOR BYTE MAPPINGS (from captured examples):
    Examples observed:
    - 0x14 = Mode 4, Red
    - 0x44 = Mode 4, Green
    - 0x64 = Mode 4, Blue
    
    Pattern: likely (mode << 4) | color or similar encoding
    Test other values by experimenting with --mode-color

LED SEQUENCE:
    Frame 1: LED command (fe b0 marker, mode+color byte)
    Frame 2: Finalize (fd fe ff control frame)

Captured examples:

    Red Mode 4:    03 fe b0 01 08 00 00 00 00 00 01 00 14
    Green Mode 4:  03 fe b0 01 08 00 00 00 00 00 01 00 44
    Blue Mode 4:   03 fe b0 01 08 00 00 00 00 00 01 00 64
Dependencies:
    pip install hid
"""

from __future__ import annotations

import argparse
import sys
import time

import hid


# Mode + Color byte lookup table (from captures)
LED_PRESETS = {
    "red_mode4": 0x14,
    "green_mode4": 0x44,
    "blue_mode4": 0x64,
}


def make_led_frame(
    report_id: int = 0x03,
    layer: int = 0x01,
    mode_color: int = 0x44,
) -> bytes:
    """Create an LED command frame (extended FE format).
    
    Args:
        report_id: HID report ID (default 0x03)
        layer: Device layer (default 0x01 for layer 1)
        mode_color: Combined mode + color byte (default 0x44 for green mode 4)
    
    Returns:
        65-byte HID frame
    """
    frame = bytearray(65)
    frame[0] = report_id & 0xFF
    frame[1] = 0xFE  # Extended marker
    frame[2] = 0xB0  # LED action code
    frame[3] = layer & 0xFF
    frame[4] = 0x08  # Key Type LED
    # frame[5..10] stay 0x00
    frame[11] = 0x01  # Count/data indicator
    frame[12] = mode_color & 0xFF
    return bytes(frame)


def make_finalize_frame(report_id: int = 0x03) -> bytes:
    """Create finalize/apply control frame."""
    frame = bytearray(65)
    frame[0] = report_id & 0xFF
    frame[1] = 0xFD  # Host-command marker
    frame[2] = 0xFE  # Special finalize action
    frame[3] = 0xFF  # Broadcast layer
    # frame[4..] stay 0x00
    return bytes(frame)


def to_hex(frame: bytes) -> str:
    return " ".join(f"{b:02x}" for b in frame)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send LED mode command to MacroPad 514c:8851")
    parser.add_argument("--vid", type=lambda v: int(v, 0), default=0x514C, help="Vendor ID (default: 0x514C)")
    parser.add_argument("--pid", type=lambda v: int(v, 0), default=0x8851, help="Product ID (default: 0x8851)")
    parser.add_argument("--report-id", type=lambda v: int(v, 0), default=0x03, help="Report ID (default: 0x03)")
    parser.add_argument("--layer", type=lambda v: int(v, 0), default=0x01, help="Layer (default: 0x01)")
    parser.add_argument(
        "--preset",
        choices=list(LED_PRESETS.keys()),
        help=f"Use preset (available: {', '.join(LED_PRESETS.keys())})",
    )
    parser.add_argument(
        "--mode-color",
        type=lambda v: int(v, 0),
        help="Mode+Color byte (overrides --preset, default: 0x44 = green mode 4)",
    )
    parser.add_argument("--interval-ms", type=int, default=10, help="Delay between writes in ms")
    parser.add_argument("--dry-run", action="store_true", help="Print frames only, do not send")
    args = parser.parse_args()

    # Resolve mode_color
    if args.mode_color is not None:
        mode_color = args.mode_color
    elif args.preset:
        mode_color = LED_PRESETS[args.preset]
    else:
        mode_color = 0x44  # Default: green mode 4

    led_frame = make_led_frame(args.report_id, args.layer, mode_color)
    finalize_frame = make_finalize_frame(args.report_id)

    print(f"Target VID:PID = {args.vid:04x}:{args.pid:04x}")
    print(f"LED Frame:       {to_hex(led_frame)}")
    print(f"Finalize Frame:  {to_hex(finalize_frame)}")

    if args.dry_run:
        print("Dry-run enabled, nothing sent.")
        return 0

    dev = hid.device()
    try:
        dev.open(args.vid, args.pid)
        print("Device opened.")

        for frame, name in [(led_frame, "LED"), (finalize_frame, "Finalize")]:
            written = dev.write(frame)
            if written != len(frame):
                print(f"Write failed on {name}: wrote {written} of {len(frame)} bytes", file=sys.stderr)
                return 2
            print(f"{name} frame sent ({written} bytes)")
            if args.interval_ms > 0:
                time.sleep(args.interval_ms / 1000.0)

        print("LED sequence completed.")
        return 0
    except OSError as ex:
        print(f"HID open/write failed: {ex}", file=sys.stderr)
        return 1
    finally:
        try:
            dev.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
