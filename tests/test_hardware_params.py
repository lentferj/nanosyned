# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The parameter probe, on the unit, one row per mode.

This is the smallest hardware test that can fail if a promoted row stops
being true: for Global, Mix and Program it runs the probe tool's own
positive control and one probe on a row the 2026-11-01 bench confirmed,
and requires the verdict ``confirmed`` and a byte-identical restore.

**Opt-in twice more than the rest of the suite.** ``--hardware`` (or
``NANOSYNED_HARDWARE=1``) gets the unit open; ``NANOSYNED_HW_PARAMS=1``
gets this file past its own skip, because a probe moves a parameter in
the unit's live buffers. It stores nothing: the probe sends ``10``,
``02``/``0E`` 100 loads and ``0D``, and the restore is read back and
asserted. The global record is the one live setting it touches, and it
is put back one ``10`` at a time.

Program rows are probed in **Mix mode**, in the per-channel edit buffer
the bench found: a program ``10`` is ignored in Program mode.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

from nano import params
from nano import records as rec

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "probe_params.py")


def _tool():
    spec = importlib.util.spec_from_file_location("probe_params_hw", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so the module's dataclasses resolve
    # against a real module, the way they do under an import.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()

#: One row per mode, by the label the bench confirmed. Program rows are
#: templates (``sound=None``) and resolve to sound 1 in the probe.
CASES = {
    "global": "Pitch transpose",
    "mix": "Mix name digit 0",
    "program": "Sound volume",
}


class TestTheVerifiedRowsStillProbe:
    def test_one_confirmed_row_per_mode_probes_and_restores(self, unit) -> None:
        if not os.environ.get("NANOSYNED_HW_PARAMS"):
            pytest.skip(
                "the parameter test needs NANOSYNED_HW_PARAMS=1: a probe "
                "moves a parameter in the unit's live buffers (it stores "
                "nothing, and restores and verifies the record)"
            )
        for mode, label in CASES.items():
            # ``by_label`` returns the table row; a program sound row's
            # address is relative until ``addressed`` resolves it to the
            # sound the 10 names.
            row = tool.addressed(params.by_label(label)[0])
            assert row.mode == mode, (label, row.mode)
            assert row.verified, (
                f"{label} is promoted, so this test may probe it; a row "
                f"that is not verified must not be written"
            )
            buffer = tool.buffer_for(mode, channel=0)
            tool.select_mode(unit, mode)
            reference = buffer.read(unit)
            try:
                tool.positive_control(unit, buffer, reference, [row], settle=0.3)
                value = tool.flip_value(row, rec.decode_bit_field(reference, row))
                result = tool.probe(
                    unit,
                    row,
                    value,
                    settle=0.3,
                    reference=reference,
                    buffer=buffer,
                )
                assert result.verdict == "confirmed", (
                    f"{mode}: {row.label} probed as {result.verdict}, not "
                    f"confirmed; the table or the firmware moved"
                )
                assert result.restored, (
                    f"{mode}: {row.label} did not restore byte for byte"
                )
            finally:
                buffer.restore_row(unit, row, reference)
                assert buffer.read(unit) == reference, (
                    f"{mode}: the record did not come back byte for byte"
                )
            print(f"\n{mode}: {row.label} confirmed and restored")
