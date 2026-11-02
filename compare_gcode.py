#!/usr/bin/env python3
"""Summarize G-code features that matter for the PowerSpec Ultra profile."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


CMD_RE = re.compile(r"^([GMT]\d+)\b")
AXIS_RE = re.compile(r"\b([XYZE])(-?\d+(?:\.\d+)?)")
FEED_RE = re.compile(r"\bF(\d+(?:\.\d+)?)")


def summarize(path: Path) -> None:
    counts: Counter[str] = Counter()
    mins = {axis: float("inf") for axis in "XYZE"}
    maxs = {axis: float("-inf") for axis in "XYZE"}
    max_feed = 0.0
    first_commands: list[str] = []

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.lstrip().startswith(";"):
            continue
        command = CMD_RE.match(raw)
        if command:
            code = command.group(1)
            counts[code] += 1
            if len(first_commands) < 18:
                first_commands.append(raw)
        if raw.startswith(("G0 ", "G1 ")):
            for axis, value_text in AXIS_RE.findall(raw):
                value = float(value_text)
                mins[axis] = min(mins[axis], value)
                maxs[axis] = max(maxs[axis], value)
            feed = FEED_RE.search(raw)
            if feed:
                max_feed = max(max_feed, float(feed.group(1)))

    def axis_range(axis: str) -> str:
        if mins[axis] == float("inf"):
            return "n/a"
        return f"{mins[axis]:.2f}..{maxs[axis]:.2f}"

    print(f"\n{path}")
    print(f"commands: {' '.join(f'{k}:{counts[k]}' for k in sorted(counts))}")
    print(
        "ranges: "
        f"X {axis_range('X')}  Y {axis_range('Y')}  "
        f"Z {axis_range('Z')}  E {axis_range('E')}  maxF {max_feed:.0f}"
    )
    print("first commands:")
    for line in first_commands:
        print(f"  {line}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: compare_gcode.py <file.g> [file.gcode ...]", file=sys.stderr)
        return 2
    for arg in sys.argv[1:]:
        summarize(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
