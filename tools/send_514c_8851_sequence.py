#!/usr/bin/env python3
"""
Send MacroPad host-command sequence (frames 3..6) to VID:PID 514c:8851.

FRAME FORMAT (65 bytes total):
    Byte 0:        Report ID
    Byte 1:        Marker (0xFD for host-command, 0xFA for device-event, 0xFE for extended)
    Byte 2:        Action (0x00..0x02 = slot/button, 0xFE = special control)
    Byte 3:        Layer (0x01 = layer 1, 0xFF = broadcast/special)
    Byte 4:        Key Type (0x01 = basic keyboard, 0x02 = multimedia, 0x03 = mouse, etc.)
    Byte 5..9:     Reserved / Delay (typically 0x00)
    Byte 10:       Count (number of key entries that follow, typically 0x00 or 0x01)
    Byte 11:       Modifier mask (0x00 = no modifier, 0x01 = Ctrl, 0x02 = Shift, 0x04 = Alt, 0x08 = Win)
    Byte 12:       Key Code (HID keyboard code: 0x04 = A, 0x05 = B, 0x06 = C, 0x07 = D, ...)
    Byte 13..64:   Padding / Additional entries (if count > 1)

EXAMPLE PACKET (Host sends keycode 0x05 to action 0x02, layer 0x01):
    03 fd 02 01 01 00 00 00 00 00 01 00 05 [rest zeros]
    |  |  |  |  |  |           |  |  |  |
    |  |  |  |  |  Reserved    |  |  Keycode (0x05 = B)
    |  |  |  |  Key Type       Count (1 entry)
    |  |  |  Layer (0x01)      Modifier (0x00 = no modifier)
    |  |  Action (0x02)
    |  Marker (0xFD = host-command)
    Report ID (0x03)

Original software sent additional frames before this sequence, 
but only frames 3..6 are relevant for the key assignment change:

SEQUENCE SENT (4 frames):
    Frame 3: Clear action 0x00 (count=0)
    Frame 4: Set action 0x01 with keycode 0x06
    Frame 5: Set action 0x02 with keycode 0x07
    Frame 6: Finalize (action=0xFE, layer=0xFF, count=0)

Dependencies:
    pip install hid

or:
    sudo apt install python3-hid
"""

from __future__ import annotations

import argparse
import sys
import time

import hid


def make_frame(
    report_id: int,
    marker: int,
    action: int,
    layer: int,
    key_type: int,
    count: int,
    entry_modifier: int = 0,
    entry_keycode: int = 0,
) -> bytes:
    # Full HID output report: 1 byte report_id + 64 bytes payload.
    frame = bytearray(65)
    frame[0] = report_id & 0xFF

    frame[1] = marker & 0xFF
    frame[2] = action & 0xFF
    frame[3] = layer & 0xFF
    frame[4] = key_type & 0xFF

    # frame[5..9] stays zero.
    frame[10] = count & 0xFF

    # First entry pair (modifier, keycode) starts at payload index 10,
    # therefore full frame indexes 11 and 12.
    frame[11] = entry_modifier & 0xFF
    frame[12] = entry_keycode & 0xFF

    return bytes(frame)


def to_hex(frame: bytes) -> str:
    return " ".join(f"{b:02x}" for b in frame)


def build_sequence(report_id: int) -> list[bytes]:
    # Frame 3
    f3 = make_frame(
        report_id=report_id,
        marker=0xFD,
        action=0x00,
        layer=0x01,
        key_type=0x01,
        count=0x00,
    )

    # Frame 4 with keycode 0x06
    f4 = make_frame(
        report_id=report_id,
        marker=0xFD,
        action=0x01,
        layer=0x01,
        key_type=0x01,
        count=0x01,
        entry_modifier=0x00,
        entry_keycode=0x06,
    )

    # Frame 5 with keycode 0x07
    f5 = make_frame(
        report_id=report_id,
        marker=0xFD,
        action=0x02,
        layer=0x01,
        key_type=0x01,
        count=0x01,
        entry_modifier=0x00,
        entry_keycode=0x07,
    )

    # Frame 6 finalize/apply
    f6 = make_frame(
        report_id=report_id,
        marker=0xFD,
        action=0xFE,
        layer=0xFF,
        key_type=0x00,
        count=0x00,
    )

    return [f3, f4, f5, f6]


def main() -> int:
    parser = argparse.ArgumentParser(description="Send frames 3..6 to MacroPad 514c:8851")
    parser.add_argument("--vid", type=lambda v: int(v, 0), default=0x514C, help="Vendor ID (default: 0x514C)")
    parser.add_argument("--pid", type=lambda v: int(v, 0), default=0x8851, help="Product ID (default: 0x8851)")
    parser.add_argument("--report-id", type=lambda v: int(v, 0), default=0x03, help="Report ID (default: 0x03)")
    parser.add_argument("--interval-ms", type=int, default=10, help="Delay between writes in ms")
    parser.add_argument("--dry-run", action="store_true", help="Print frames only, do not send")
    args = parser.parse_args()

    frames = build_sequence(args.report_id)

    print(f"Target VID:PID = {args.vid:04x}:{args.pid:04x}")
    for idx, frame in enumerate(frames, start=3):
        print(f"Frame {idx}: {to_hex(frame)}")

    if args.dry_run:
        print("Dry-run enabled, nothing sent.")
        return 0

    dev = hid.device()
    try:
        dev.open(args.vid, args.pid)
        print("Device opened.")

        for idx, frame in enumerate(frames, start=3):
            written = dev.write(frame)
            if written != len(frame):
                print(
                    f"Write failed on frame {idx}: wrote {written} of {len(frame)} bytes",
                    file=sys.stderr,
                )
                return 2
            print(f"Frame {idx} sent ({written} bytes)")
            if args.interval_ms > 0:
                time.sleep(args.interval_ms / 1000.0)

        print("Sequence completed.")
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
