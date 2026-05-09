#!/usr/bin/env python3
"""
Decode 65-byte MacroPad HID frames from hex dumps.

FRAME FORMAT (65 bytes total):
    Byte 0:        Report ID (device address, typically 0x03)
    Byte 1:        Marker
                   - 0xFD = host-command (PC sends to device)
                   - 0xFA = device-event (device sends to PC)
                   - 0xFE = extended/control
    Byte 2:        Action / Event ID
                   - 0x00..0x02 = button/action slots
                   - 0xFE = special finalize/apply control
    Byte 3:        Layer (0x01 = layer 1, 0xFF = broadcast/special)
    Byte 4:        Key Type (0x01 = basic keyboard, 0x02 = multimedia, 0x03 = mouse)
    Byte 5..9:     Reserved / Delay (typically 0x00)
    Byte 10:       Count (number of key/modifier pairs: 0x00 or 0x01)
    Byte 11:       Modifier mask (0x00 = none, 0x01 = Ctrl, 0x02 = Shift, 0x04 = Alt, 0x08 = Win)
    Byte 12:       Key Code (HID code: 0x04=A, 0x05=B, 0x06=C, 0x07=D, 0x25=K, 0x26=L)
    Byte 13..64:   Padding / Additional entries

EXAMPLE BREAKDOWN (user's captured frame):
    03 fd 02 01 01 00 00 00 00 00 01 00 05 [rest zeros]
    
    03 = ReportId
    fd = Extended-ähnlicher Marker/Header (host-command)
    02 = Action (vorher war es 01)
    01 = Layer
    01 = KeyType Basic
    00 00 = Delay
    00 00 00 = Reserved
    01 = Count (ein Key-Eintrag)
    00 05 = (Modifier=0x00, KeyCode=0x05)

Input format examples:
    - 03fd010101000000000001000400... (130 hex chars)
    - 03 fd 01 01 01 00 00 ...
    - Lines containing prefixes like "Leftover Capture Data: ..."
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable, List


HEX_RE = re.compile(r"[0-9a-fA-F]{2}")


def extract_hex_bytes(text: str) -> bytes:
    pairs = HEX_RE.findall(text)
    if not pairs:
        return b""
    return bytes(int(p, 16) for p in pairs)


def fmt_bytes(data: Iterable[int]) -> str:
    return " ".join(f"{b:02x}" for b in data)


def decode_fd(payload: bytes) -> List[str]:
    # fd frame layout observed in captures:
    # [0]=fd marker, [1]=action, [2]=layer, [3]=key_type,
    # [4..8]=reserved/delay-ish, [9]=count, then pairs at [10..]
    out = []
    action = payload[1]
    layer = payload[2]
    key_type = payload[3]
    count = payload[9]

    out.append("kind: host-command (fd)")
    out.append(f"action: 0x{action:02x} ({action})")
    out.append(f"layer: 0x{layer:02x} ({layer})")
    out.append(f"key_type: 0x{key_type:02x} ({key_type})")
    out.append(f"count: 0x{count:02x} ({count})")

    # Parse count pairs modifier/keycode
    pairs = []
    for i in range(count):
        base = 10 + (i * 2)
        if base + 1 >= len(payload):
            break
        mod = payload[base]
        key = payload[base + 1]
        pairs.append((i, mod, key))

    if pairs:
        out.append("entries:")
        for idx, mod, key in pairs:
            out.append(f"  - #{idx}: modifier=0x{mod:02x} key=0x{key:02x}")

    # common special trailer frame in captures: fd fe ff ...
    if action == 0xFE and layer == 0xFF:
        out.append("note: special finalize/apply-style control frame")

    return out


def decode_fa(payload: bytes) -> List[str]:
    # fa frame layout appears very similar to fd, but originates device->host.
    out = []
    action = payload[1]
    layer = payload[2]
    key_type = payload[3]
    count = payload[9]

    out.append("kind: device-event (fa)")
    out.append(f"event/action: 0x{action:02x} ({action})")
    out.append(f"layer: 0x{layer:02x} ({layer})")
    out.append(f"key_type: 0x{key_type:02x} ({key_type})")
    out.append(f"count: 0x{count:02x} ({count})")

    pairs = []
    for i in range(count):
        base = 10 + (i * 2)
        if base + 1 >= len(payload):
            break
        mod = payload[base]
        key = payload[base + 1]
        pairs.append((i, mod, key))

    if pairs:
        out.append("entries:")
        for idx, mod, key in pairs:
            out.append(f"  - #{idx}: modifier=0x{mod:02x} key=0x{key:02x}")

    return out


def decode_legacy(payload: bytes) -> List[str]:
    # Legacy KeyFunctionReport-like layout:
    # [0]=mapped action, [1]=type|layerbits, [2]=seq_len, [3]=index,
    # [4]=modifier, [5]=key
    action = payload[0]
    typelayer = payload[1]
    seq_len = payload[2]
    index = payload[3]
    mod = payload[4]
    key = payload[5]

    return [
        "kind: legacy-like report",
        f"action: 0x{action:02x} ({action})",
        f"type+layer: 0x{typelayer:02x}",
        f"sequence_len: 0x{seq_len:02x} ({seq_len})",
        f"sequence_index: 0x{index:02x} ({index})",
        f"modifier: 0x{mod:02x}",
        f"key: 0x{key:02x}",
    ]


def decode_frame(frame: bytes) -> List[str]:
    if len(frame) < 2:
        return ["invalid frame (too short)"]

    rid = frame[0]
    payload = frame[1:]
    marker = payload[0] if payload else None

    out = [
        f"report_id: 0x{rid:02x} ({rid})",
        f"marker: 0x{marker:02x} ({marker})" if marker is not None else "marker: <none>",
    ]

    if len(payload) < 11:
        out.append(f"payload too short: {len(payload)} bytes")
        return out

    if marker == 0xFD:
        out.extend(decode_fd(payload))
    elif marker == 0xFA:
        out.extend(decode_fa(payload))
    elif marker == 0xFE:
        out.append("kind: extended report (fe)")
        out.append(f"action: 0x{payload[1]:02x} ({payload[1]})")
        out.append(f"layer: 0x{payload[2]:02x} ({payload[2]})")
        out.append(f"key_type: 0x{payload[3]:02x} ({payload[3]})")
        out.append(f"count: 0x{payload[9]:02x} ({payload[9]})")
    else:
        out.extend(decode_legacy(payload))

    out.append(f"raw_frame: {fmt_bytes(frame)}")
    return out


def split_frames(blob: bytes) -> List[bytes]:
    # Expected frame size is 65 bytes (1 report id + 64 payload).
    # If the blob is larger, chunk into 65-byte frames.
    frame_size = 65
    if len(blob) == frame_size:
        return [blob]
    if len(blob) < frame_size:
        return [blob]

    frames = []
    i = 0
    while i < len(blob):
        frames.append(blob[i : i + frame_size])
        i += frame_size
    return frames


def read_inputs(args: argparse.Namespace) -> List[str]:
    lines: List[str] = []

    if args.frame:
        lines.extend(args.frame)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            lines.extend(f.readlines())

    if not lines and not sys.stdin.isatty():
        lines.extend(sys.stdin.read().splitlines())

    return [line.strip() for line in lines if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode MacroPad HID frame hex dumps")
    parser.add_argument(
        "-f",
        "--frame",
        action="append",
        help="hex frame line (can be repeated)",
    )
    parser.add_argument(
        "-i",
        "--file",
        help="text file with captured hex lines",
    )
    args = parser.parse_args()

    lines = read_inputs(args)
    if not lines:
        print("No input provided. Use --frame, --file, or pipe text to stdin.", file=sys.stderr)
        return 1

    frame_no = 1
    for line in lines:
        data = extract_hex_bytes(line)
        if not data:
            continue

        for frame in split_frames(data):
            print(f"Frame #{frame_no}")
            for row in decode_frame(frame):
                print(f"  {row}")
            print()
            frame_no += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
