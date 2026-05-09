#!/usr/bin/env python3
"""
Verify MacroPad frame sequence (frames 3..6) for VID:PID 514c:8851 from captures.

FRAME FORMAT (65 bytes total):
    Byte 0:        Report ID (device address, typically 0x03)
    Byte 1:        Marker
                   - 0xFD = host-command (PC sends to device)
                   - 0xFA = device-event (device sends to PC)
                   - 0xFE = extended/control
    Byte 2:        Action / Event ID
                   - 0x00..0x02 = button/action slots
                   - 0xFE = special finalize/apply control
    Byte 3:        Layer (0x01 = layer 1, 0xFF = broadcast/finalize)
    Byte 4:        Key Type (0x01 = basic keyboard, 0x02 = multimedia, 0x03 = mouse)
    Byte 5..9:     Reserved / Delay (typically 0x00)
    Byte 10:       Count (number of key/modifier pairs: 0x00 or 0x01)
    Byte 11:       Modifier mask (0x00 = none, 0x01 = Ctrl, 0x02 = Shift, 0x04 = Alt, 0x08 = Win)
    Byte 12:       Key Code (HID code: 0x04=A, 0x05=B, 0x06=C, 0x07=D, 0x25=K, 0x26=L)
    Byte 13..64:   Padding / Additional entries

EXAMPLE BREAKDOWN (user's captured frame):
    03 fd 02 01 01 00 00 00 00 00 01 00 05 [rest zeros]
    |  |  |  |  |  |  |  |  |  |  |  |  |
    03 = ReportId
       fd = Extended-ähnlicher Marker/Header (host-command)
          02 = Action (vorher war es 01)
             01 = Layer
                01 = KeyType Basic
                   00 00 = Delay
                      00 00 00 = Reserved
                            01 = Count (ein Key-Eintrag)
                               00 05 = (Modifier=0x00, KeyCode=0x05)

EXPECTED SEQUENCE (to be verified):
    Frame 3: 03 fd 00 01 01 ... count=00              (clear/reset)
    Frame 4: 03 fd 01 01 01 ... count=01 mod=00 key=06  (action 0x01 -> keycode 0x06)
    Frame 5: 03 fd 02 01 01 ... count=01 mod=00 key=07  (action 0x02 -> keycode 0x07)
    Frame 6: 03 fd fe ff 00 ... count=00              (finalize/apply)

Input can be:
    - raw hex frame lines (with or without spaces)
    - lines like "Leftover Capture Data: ..."
    - mixed text; only hex byte pairs are extracted
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


HEX_RE = re.compile(r"[0-9a-fA-F]{2}")
FRAME_SIZE = 65


@dataclass(frozen=True)
class FrameSpec:
    report_id: int
    marker: int
    action: int
    layer: int
    key_type: int
    count: int
    mod: int | None = None
    key: int | None = None


EXPECTED_SEQUENCE: Sequence[FrameSpec] = (
    FrameSpec(0x03, 0xFD, 0x00, 0x01, 0x01, 0x00),
    FrameSpec(0x03, 0xFD, 0x01, 0x01, 0x01, 0x01, mod=0x00, key=0x06),
    FrameSpec(0x03, 0xFD, 0x02, 0x01, 0x01, 0x01, mod=0x00, key=0x07),
    FrameSpec(0x03, 0xFD, 0xFE, 0xFF, 0x00, 0x00),
)


def extract_hex_bytes(text: str) -> bytes:
    pairs = HEX_RE.findall(text)
    return bytes(int(p, 16) for p in pairs)


def chunk_frames(blob: bytes) -> List[bytes]:
    if len(blob) < FRAME_SIZE:
        return []
    return [blob[i : i + FRAME_SIZE] for i in range(0, len(blob) - (len(blob) % FRAME_SIZE), FRAME_SIZE)]


def frame_brief(frame: bytes) -> str:
    if len(frame) < FRAME_SIZE:
        return "<short frame>"
    return (
        f"rid={frame[0]:02x} marker={frame[1]:02x} action={frame[2]:02x} "
        f"layer={frame[3]:02x} type={frame[4]:02x} count={frame[10]:02x} "
        f"mod={frame[11]:02x} key={frame[12]:02x}"
    )


def matches_spec(frame: bytes, spec: FrameSpec) -> bool:
    if len(frame) < FRAME_SIZE:
        return False
    if frame[0] != spec.report_id:
        return False
    if frame[1] != spec.marker:
        return False
    if frame[2] != spec.action:
        return False
    if frame[3] != spec.layer:
        return False
    if frame[4] != spec.key_type:
        return False
    if frame[10] != spec.count:
        return False

    if spec.mod is not None and frame[11] != spec.mod:
        return False
    if spec.key is not None and frame[12] != spec.key:
        return False

    return True


def find_sequence(frames: Sequence[bytes], expected: Sequence[FrameSpec]) -> Tuple[bool, int]:
    if len(frames) < len(expected):
        return False, -1

    last_start = len(frames) - len(expected)
    for start in range(last_start + 1):
        ok = True
        for i, spec in enumerate(expected):
            if not matches_spec(frames[start + i], spec):
                ok = False
                break
        if ok:
            return True, start
    return False, -1


def read_input_lines(args: argparse.Namespace) -> List[str]:
    lines: List[str] = []

    if args.frame:
        lines.extend(args.frame)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            lines.extend(f.readlines())

    if not lines and not sys.stdin.isatty():
        lines.extend(sys.stdin.read().splitlines())

    return [line.strip() for line in lines if line.strip()]


def collect_frames(lines: Iterable[str]) -> List[bytes]:
    frames: List[bytes] = []
    for line in lines:
        raw = extract_hex_bytes(line)
        if not raw:
            continue

        # Typical capture line is exactly one 65-byte frame (130 hex chars).
        # If longer, process in 65-byte chunks.
        if len(raw) >= FRAME_SIZE:
            frames.extend(chunk_frames(raw))

    return frames


def print_expected() -> None:
    print("Expected sequence:")
    for i, spec in enumerate(EXPECTED_SEQUENCE, start=3):
        extras = ""
        if spec.mod is not None or spec.key is not None:
            extras = f", mod={spec.mod:02x}, key={spec.key:02x}"
        print(
            f"  Frame {i}: rid={spec.report_id:02x} marker={spec.marker:02x} "
            f"action={spec.action:02x} layer={spec.layer:02x} type={spec.key_type:02x} "
            f"count={spec.count:02x}{extras}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify 514c:8851 frame sequence from capture text")
    parser.add_argument("-f", "--frame", action="append", help="single hex line/frame (can be repeated)")
    parser.add_argument("-i", "--file", help="capture text file")
    parser.add_argument("--show-frames", action="store_true", help="print parsed frames summary")
    args = parser.parse_args()

    lines = read_input_lines(args)
    if not lines:
        print("No input given. Use --file, --frame, or pipe capture text.", file=sys.stderr)
        return 2

    frames = collect_frames(lines)
    if not frames:
        print("No complete 65-byte frames found in input.", file=sys.stderr)
        return 2

    if args.show_frames:
        print(f"Parsed frames: {len(frames)}")
        for idx, frame in enumerate(frames, start=1):
            print(f"  #{idx}: {frame_brief(frame)}")

    ok, start = find_sequence(frames, EXPECTED_SEQUENCE)
    print_expected()

    if ok:
        print(f"\nVERIFY OK: sequence found starting at parsed frame #{start + 1}.")
        return 0

    print("\nVERIFY FAILED: expected 4-frame sequence not found.", file=sys.stderr)
    print("Tip: use --show-frames to inspect parsed frame fields.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
