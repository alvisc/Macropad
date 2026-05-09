#!/usr/bin/env python3
"""
Send MacroPad host-command sequence to VID:PID 514c:8851.

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
but only the clear/set/finalize frames are relevant for the key assignment change.

Example:
    --keys A B
    => Key1 / action 0x01 gets HID keycode 0x04
    => Key2 / action 0x02 gets HID keycode 0x05

    --keys Ctrl+A Shift+B Alt+F4
    => Key1 gets modifier 0x01 and keycode 0x04
    => Key2 gets modifier 0x02 and keycode 0x05
    => Key3 gets modifier 0x04 and keycode 0x3d

Raw HID code input:
    --keys 0x04 0x05
    => Key1 gets keycode 0x04, Key2 gets keycode 0x05

    --keys 4 5
    => Key1 gets keycode 0x04, Key2 gets keycode 0x05

    --keys CTRL+0x04 ALT+0x3d
    => Key1 gets modifier 0x01 + keycode 0x04
    => Key2 gets modifier 0x04 + keycode 0x3d

Sequence sent:
    Frame 1: Clear action 0x00 (count=0)
    Frame 2..N: Set action 0x01..0x0c with the requested keycodes
    Final frame: Finalize (action=0xFE, layer=0xFF, count=0)

Dependencies:
    pip install hid

or:
    sudo apt install python3-hid
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Tuple

import hid


LETTER_KEYCODES = {
    chr(ord("A") + index): 0x04 + index
    for index in range(26)
}

FUNCTION_KEYCODES = {
    f"F{index}": 0x3A + (index - 1)
    for index in range(1, 13)
}

DIGIT_KEYCODES = {
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
}

MODIFIER_BITS = {
    "CTRL": 0x01,
    "CONTROL": 0x01,
    "SHIFT": 0x02,
    "ALT": 0x04,
    "WIN": 0x08,
    "META": 0x08,
    "SUPER": 0x08,
}


def parse_base_key_token(token: str) -> int:
    token = token.strip().upper()
    if token in LETTER_KEYCODES:
        return LETTER_KEYCODES[token]
    if token in FUNCTION_KEYCODES:
        return FUNCTION_KEYCODES[token]
    if token in DIGIT_KEYCODES:
        return DIGIT_KEYCODES[token]
    if token.startswith("0X"):
        return int(token, 16)
    if token.isdigit():
        return int(token, 10)
    raise ValueError(f"unsupported key token: {token}")


def parse_key_token(token: str) -> Tuple[int, int]:
    parts = [part.strip().upper() for part in token.split("+") if part.strip()]
    if not parts:
        raise ValueError("empty key token")

    modifier = 0
    for part in parts[:-1]:
        if part not in MODIFIER_BITS:
            raise ValueError(f"unsupported modifier: {part}")
        modifier |= MODIFIER_BITS[part]

    keycode = parse_base_key_token(parts[-1])
    return modifier, keycode


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


def build_sequence(report_id: int, assignments: list[Tuple[int, int]]) -> list[bytes]:
    frames = [
        make_frame(
            report_id=report_id,
            marker=0xFD,
            action=0x00,
            layer=0x01,
            key_type=0x01,
            count=0x00,
        )
    ]

    for index, (modifier, keycode) in enumerate(assignments, start=1):
        frames.append(
            make_frame(
                report_id=report_id,
                marker=0xFD,
                action=index,
                layer=0x01,
                key_type=0x01,
                count=0x01,
                entry_modifier=modifier,
                entry_keycode=keycode,
            )
        )

    frames.append(
        make_frame(
            report_id=report_id,
            marker=0xFD,
            action=0xFE,
            layer=0xFF,
            key_type=0x00,
            count=0x00,
        )
    )

    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign letters or HID keycodes to MacroPad keys")
    parser.add_argument("--vid", type=lambda v: int(v, 0), default=0x514C, help="Vendor ID (default: 0x514C)")
    parser.add_argument("--pid", type=lambda v: int(v, 0), default=0x8851, help="Product ID (default: 0x8851)")
    parser.add_argument("--report-id", type=lambda v: int(v, 0), default=0x03, help="Report ID (default: 0x03)")
    parser.add_argument("--interval-ms", type=int, default=10, help="Delay between writes in ms")
    parser.add_argument(
        "--keys",
        nargs="+",
        required=True,
        help="Keys to assign to Key1, Key2, ...; supports A B C, Ctrl+A, Shift+B, Alt+F4, or raw HID codes like 0x04",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print frames only, do not send")
    args = parser.parse_args()

    try:
        assignments = [parse_key_token(token) for token in args.keys]
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 2

    if len(assignments) > 12:
        print("at most 12 keys can be assigned in one call", file=sys.stderr)
        return 2

    frames = build_sequence(args.report_id, assignments)

    print(f"Target VID:PID = {args.vid:04x}:{args.pid:04x}")
    print("Assignments:")
    for index, (modifier, keycode) in enumerate(assignments, start=1):
        print(f"  Key{index} -> modifier 0x{modifier:02x}, keycode 0x{keycode:02x}")
    for idx, frame in enumerate(frames, start=1):
        print(f"Frame {idx}: {to_hex(frame)}")

    if args.dry_run:
        print("Dry-run enabled, nothing sent.")
        return 0

    dev = hid.device()
    try:
        dev.open(args.vid, args.pid)
        print("Device opened.")

        for idx, frame in enumerate(frames, start=1):
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
