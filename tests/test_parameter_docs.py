# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""The generated parameter map agrees with nano.params."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from nano import params

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "gen_parameter_docs.py")
_DOC = os.path.join(os.path.dirname(_HERE), "docs", "PARAMETER_NUMBERS.md")


def _tool():
    spec = importlib.util.spec_from_file_location("gen_parameter_docs", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _tool()


def _section_data_rows(rendered: str, heading: str) -> int:
    count = 0
    in_section = False
    for line in rendered.splitlines():
        if line.strip() == "## " + heading:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.startswith("|"):
            continue
        if line.startswith("| ---") or line.startswith("| function "):
            continue
        count += 1
    return count


def test_render_starts_with_title_and_summary_mentions_modes():
    rendered = gen.render()
    assert rendered.startswith("# ")
    for mode in ("global", "mix", "program", "effects"):
        assert mode in rendered


def test_every_row_appears_once():
    rendered = gen.render()
    for mode in ("global", "mix", "effects", "program"):
        expected = sum(1 for param in params.PARAMS if param.mode == mode)
        assert _section_data_rows(rendered, mode) == expected


def test_committed_doc_equals_render():
    assert Path(_DOC).read_text(encoding="utf-8") == gen.render()


def test_summary_counts_verified_from_the_table():
    """The count is derived, so a promoted row updates the prose too."""
    rendered = gen.render()
    in_summary = False
    total = 0
    for line in rendered.splitlines():
        if line.strip() == "## Summary":
            in_summary = True
            continue
        if in_summary and line.startswith("## "):
            break
        if not in_summary or not line.startswith("|"):
            continue
        if line.startswith("| ---") or line.startswith("| mode "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 3
        mode = cells[0]
        expected = sum(
            1 for param in params.PARAMS if param.mode == mode and param.verified
        )
        assert cells[2] == str(expected), mode
        total += expected
    assert f"{total} of them are verified" in rendered
    if total == 0:
        assert "| yes |" not in rendered
