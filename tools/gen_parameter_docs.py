#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Generate docs/PARAMETER_NUMBERS.md from nano/params.py.

The parameter tables in nano.params are the single source of truth for the
instrument's parameter addresses, ranges and bit layouts. This tool renders
them as a Markdown map so a human (and the probe run) can read them without
opening Python, and so the document cannot drift from the table it is built
from: every row is transcribed verbatim, and a test regenerates the file and
compares.

No Alesis program name is written here; only the parameter rows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import params

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _escape_label(label: str) -> str:
    """Escape a pipe so a label cannot break a Markdown table cell."""
    return label.replace("|", "\\|")


def _rows_for_mode(mode: str) -> list[params.Param]:
    """The rows of mode, in the documented stable order."""
    rows = [param for param in params.PARAMS if param.mode == mode]
    rows.sort(
        key=lambda param: (
            param.function,
            param.page,
            param.pot,
            param.sound is None,
            param.sound if param.sound is not None else 0,
            param.channel is None,
            param.channel if param.channel is not None else 0,
            param.label,
        )
    )
    return rows


def _mode_order() -> list[str]:
    """Modes in the order they first appear in PARAMS."""
    seen: list[str] = []
    for param in params.PARAMS:
        if param.mode not in seen:
            seen.append(param.mode)
    return seen


def render() -> str:
    """Render the whole document as a single Markdown string."""
    lines: list[str] = []
    lines.append("# Parameter numbers")
    lines.append("")
    lines.append(
        "Rows are transcribed from the published QS6/7/8/R specification. "
        "A row is writable only once a controlled before/after probe "
        "confirms its offset and value law."
    )
    lines.append("")
    verified = sum(1 for param in params.PARAMS if param.verified)
    lines.append(
        "The map holds "
        + str(len(params.PARAMS))
        + " rows across "
        + str(len(_mode_order()))
        + " modes; "
        + str(verified)
        + " of them are verified."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| mode | rows | verified |")
    lines.append("| --- | --- | --- |")
    for mode in _mode_order():
        rows = _rows_for_mode(mode)
        verified = sum(1 for param in rows if param.verified)
        lines.append(
            "| " + mode + " | " + str(len(rows)) + " | " + str(verified) + " |"
        )
    lines.append("")
    for mode in _mode_order():
        lines.append("## " + mode)
        lines.append("")
        lines.append(
            "| function | page | pot | label | bits | bit address | range | "
            "offset | law | verified |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for param in _rows_for_mode(mode):
            status = "yes" if param.verified else "no"
            law = param.value_law or "(inferred)"
            lines.append(
                "| "
                + str(param.function)
                + " | "
                + str(param.page)
                + " | "
                + str(param.pot)
                + " | "
                + _escape_label(param.label)
                + " | "
                + str(param.bits)
                + " | "
                + str(param.bit_address)
                + " | "
                + str(param.low)
                + ".."
                + str(param.high)
                + " | "
                + str(param.offset)
                + " | "
                + law
                + " | "
                + status
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    path = _REPO_ROOT / "docs" / "PARAMETER_NUMBERS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
