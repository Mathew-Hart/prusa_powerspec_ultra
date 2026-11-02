#!/usr/bin/env python3
"""Normalize PrusaSlicer output for PowerSpec Ultra / Sailfish-style firmware."""

from __future__ import annotations

import re
import sys
from pathlib import Path


TEMP_WAIT_RE = re.compile(r"^M(109|190)\b(.*)$")


def normalize_line(line: str) -> list[str]:
    stripped = line.strip()

    # This firmware's known-good left-extruder files use M104/M140 plus M6 T1,
    # not RepRap waits.
    match = TEMP_WAIT_RE.match(stripped)
    if match:
        code, rest = match.groups()
        if code == "109":
            return [f"M104{rest} T1\n", "M6 T1\n"]
        return [f"M140{rest}\n"]

    # Keep the file in the same simple dialect as the known-good PowerPrint output.
    if stripped.startswith("M82"):
        return []
    if stripped == "T0":
        return ["M108 T1\n"]

    return [line]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: powerspec_ultra_postprocess.py <gcode-file>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    normalized: list[str] = []
    in_config_dump = False
    for line in original:
        if line.startswith("; prusaslicer_config = begin"):
            in_config_dump = True
            continue
        if in_config_dump:
            if line.startswith("; prusaslicer_config = end"):
                in_config_dump = False
            continue
        normalized.extend(normalize_line(line))

    path.write_text("".join(normalized), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
