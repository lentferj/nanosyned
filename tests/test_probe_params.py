# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""The probe harness's safety contract, against a fake unit that writes bits.

``tools/probe_params.py`` promises two things that a green verdict cannot
prove on its own: that the edit buffer comes back byte for byte, and that
**opcode ``00`` never reaches the wire** -- the store that would overwrite
somebody's user program. So the fake below, :class:`Firmware`, keeps a log
of every frame it is asked to send and applies each ``10`` to its buffer
with plain bit arithmetic of its own, never through
:func:`nano.records.encode_bit_field`: a fake that shared the encoder's
idea of an address could not disagree with it, and disagreement is exactly
what the wrong-address test has to be able to see.

No port is opened here, no hardware is needed, and no Alesis content
appears: the buffer starts zeroed and every name involved is invented.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

import pytest

from nano import messages as m
from nano import params
from nano import records as rec

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "probe_params.py")


def _tool():
    """The tool, loaded by path as ``tests/test_extract_pdf.py`` does."""
    spec = importlib.util.spec_from_file_location("probe_params", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so that the module's own dataclasses
    # resolve against a real module, the way they do under an import.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()

#: The store encoder and the bridge's store method, as *words*. The scan's
#: ``\b`` matters: ``edit_program_dump`` -- the **load** this tool builds
#: for ``--backup-dir`` -- contains ``program_dump``, but ``_`` is a word
#: character, so there is no boundary before ``program`` inside it and the
#: load cannot be mistaken for the store by this pattern.
_FORBIDDEN = re.compile(r"\b(write_program|program_dump)\b")

_MODE_BY_NUMBER = {number: name for name, number in params.MODE_NUMBERS.items()}

#: Three signed Global rows whose complement at a zeroed buffer is inside
#: the range -- the happy path's selection, and the reason for it is here
#: rather than in a comment nobody reads: a row whose flip would leave the
#: range reports ``partial`` by design, and that is a different test.
GLOBAL_THREE = [
    params.at("global", 0, 0, 2),  # Pitch transpose, -12..12, 8 bits
    params.at("global", 0, 0, 3),  # Pitch fine tune, -99..99, 8 bits
    params.at("global", 0, 1, 2),  # Keyboard Transpose, -12..12, 8 bits
]

#: Five rows across all four modes for the ``flip_value`` spot-check: a
#: signed Global field, a Mix channel field, an Effects field, a Program
#: name digit and a program sound-block template.
FLIP_ROWS = [
    params.at("global", 0, 0, 2),
    params.at("mix", 1, 0, 0),
    params.at("effects", 0, 1, 1, sound=0),
    params.at("program", 8, 0, 0),
    params.at("program", 1, 0, 0),
]


class Firmware:
    """A stand-in unit that applies the field itself, bit by bit.

    ``shift`` moves every field the fake writes one bit (or however many)
    away from the address the table claims -- the shape a *wrong table
    address* has on a real unit, where the tool expects the table's bits
    and something else moves. ``corrupt_from`` is the index of the first
    ``write_edit_program`` whose load the fake stores wrongly: ``0``
    corrupts the pre-flight restore itself, ``1`` lets the pre-flight pass
    and then breaks the restore after the first probe.
    """

    def __init__(self, *, shift: int = 0, corrupt_from: int | None = None) -> None:
        self.buffer = bytearray(rec.PROGRAM_BYTES)
        self.shift = shift
        self.corrupt_from = corrupt_from
        #: Every frame the tool asked to send, as built messages.
        self.sent: list[bytes] = []
        #: The order of calls, so "the mode was selected before the
        #: buffer was read" can be asserted rather than assumed.
        self.events: list[str] = []
        self.edits: list[tuple[int, int, int, int, int, int, int]] = []
        self.modes: list[bool] = []
        self.writes = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def read_edit_program(self, *, timeout: float | None = None) -> bytes:
        self.events.append("read")
        return bytes(self.buffer)

    def write_edit_program(
        self, record: bytes, *, edit: int = 0, timeout: float | None = None
    ) -> None:
        # The load path, and nothing else: this fake has no method that
        # stores, so a tool that called one would fail here with an
        # AttributeError rather than quietly overwriting a bank.
        rec.check_size(record, rec.PROGRAM_BYTES, "a program")
        self.events.append("write")
        self.sent.append(m.edit_program_dump(record, edit=edit))
        stored = bytearray(bytes(record)[: rec.PROGRAM_BYTES])
        if self.corrupt_from is not None and self.writes >= self.corrupt_from:
            stored[0] ^= 0x01  # a load that did not land as sent
        self.writes += 1
        self.buffer[:] = stored

    def midi_edit(  # noqa: PLR0913 -- the body is the spec's seven fields
        self,
        mode: int,
        function: int,
        page: int,
        pot: int,
        value: int,
        *,
        sound: int = 0,
        channel: int = 0,
        timeout: float | None = None,
    ) -> None:
        self.events.append("edit")
        self.sent.append(
            m.midi_edit(mode, function, page, pot, value, sound=sound, channel=channel)
        )
        found = params.at(
            _MODE_BY_NUMBER.get(mode, ""),
            function,
            page,
            pot,
            sound=sound,
            channel=channel,
        )
        if found is None:
            return
        stored = params.stored_for(found, found.clamp(value))
        # Plain arithmetic, most significant bit first, byte ``at >> 3``
        # and bit ``at & 7`` -- deliberately *not* encode_bit_field, so
        # that this fake and the tool's expected_bits can disagree.
        top = found.bit_address + self.shift + found.bits - 1
        for step in range(found.bits):
            at = top - step
            byte, bit = at >> 3, at & 7
            mask = 1 << bit
            if (stored >> (found.bits - 1 - step)) & 1:
                self.buffer[byte] |= mask
            else:
                self.buffer[byte] &= ~mask & 0xFF
        self.edits.append((mode, function, page, pot, value, sound, channel))

    def mode_select(self, mix_mode: bool) -> None:
        self.events.append("mode")
        self.sent.append(m.mode_select(mix_mode))
        self.modes.append(mix_mode)


def _functions(firmware: Firmware) -> list[int]:
    """Every frame's opcode, in the order the tool sent it."""
    parsed = [m.parse(frame) for frame in firmware.sent]
    assert all(packet is not None for packet in parsed)
    return [packet.function for packet in parsed if packet is not None]


def _flip(record: bytearray, bits) -> bytes:
    """A copy of ``record`` with ``bits`` toggled, by hand."""
    after = bytearray(record)
    for at in bits:
        after[at >> 3] ^= 1 << (at & 7)
    return bytes(after)


class TestChangedBitsAndExpectedBits:
    def test_changed_bits_are_absolute_and_ascending(self):
        before = bytes(4)
        after = bytearray(before)
        after[0] = 0b0000_0101  # bits 0 and 2
        after[2] = 0x80  # bit 16 + 7
        assert tool.changed_bits(before, bytes(after)) == (0, 2, 23)

    def test_identical_records_have_no_changed_bits(self):
        record = bytes(range(16))
        assert tool.changed_bits(record, record) == ()

    def test_expected_bits_run_from_the_low_address_up(self):
        row = params.at("global", 0, 1, 0)  # Keyboard scaling: 7 bits at 24
        assert tool.expected_bits(row) == (24, 25, 26, 27, 28, 29, 30)

    def test_a_field_that_crosses_a_byte_is_one_contiguous_range(self):
        row = params.at("effects", 4, 1, 0, sound=0)  # 8 bits at 108
        assert row is not None
        assert tool.expected_bits(row) == tuple(range(108, 116))
        assert 108 >> 3 != 115 >> 3  # it really does cross the boundary


class TestClassify:
    """The four verdicts, on records built by hand rather than by a run."""

    def setup_method(self):
        self.row = params.at("global", 0, 1, 0)  # 7 bits at 24
        assert self.row is not None
        self.before = bytes(rec.PROGRAM_BYTES)
        self.expected = tool.expected_bits(self.row)

    def test_nothing_moving_is_no_change(self):
        verdict = tool.classify(self.row, self.before, self.before, target=0)
        assert verdict == "no-change"

    def test_exactly_the_fields_bits_is_confirmed(self):
        after = _flip(bytearray(self.before), self.expected)
        assert tool.classify(self.row, self.before, after, target=127) == "confirmed"

    def test_a_subset_that_decodes_to_the_target_is_confirmed(self):
        """A field wider than its legal range cannot always flip every bit.

        Only part of the field moved, but nothing outside it did, and the
        field holds the value that was sent -- which is the address
        confirmed, not a fault.
        """
        after = _flip(bytearray(self.before), self.expected[1:])
        assert tool.classify(self.row, self.before, after, target=126) == "confirmed"

    def test_a_subset_that_decodes_elsewhere_is_partial(self):
        after = _flip(bytearray(self.before), self.expected[1:])
        assert tool.classify(self.row, self.before, after, target=127) == "partial"

    def test_one_bit_landing_one_position_off_is_mismatch(self):
        # The field shifted up by one: the top bit now sits at 31, which
        # is outside the row -- the signature a wrong table address has.
        shifted = tuple(at + 1 for at in self.expected)
        after = _flip(bytearray(self.before), shifted)
        assert tool.classify(self.row, self.before, after, target=127) == "mismatch"

    def test_one_extra_bit_outside_the_field_is_mismatch(self):
        after = _flip(bytearray(self.before), (*self.expected, 40))
        assert tool.classify(self.row, self.before, after, target=255) == "mismatch"


class TestHappyPathRun:
    def test_three_rows_confirm_and_the_buffer_came_back(self):
        firmware = Firmware()
        reference = bytes(firmware.buffer)
        probes = tool.run(firmware, GLOBAL_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["confirmed"] * 3
        assert [p.restored for p in probes] == [True] * 3
        assert tool.succeeded(probes) is True
        # Byte-identical to the reference, not merely "close enough".
        assert bytes(firmware.buffer) == reference

    def test_the_mode_is_selected_before_the_buffer_is_read(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert firmware.events[0] == "mode"
        assert firmware.events.index("mode") < firmware.events.index("read")
        # Program mode for global rows: mode_select(False).
        assert firmware.modes == [False]

    def test_every_probe_restores_and_the_run_ends_on_a_restore(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE, settle=0.0)
        # Per probe: edit, read, restore-write, restore-read.
        assert firmware.events[4:8] == ["edit", "read", "write", "read"]
        # ...and the run's final check is a restore too.
        assert firmware.events[-2:] == ["write", "read"]
        assert firmware.closed is False

    def test_a_probe_moves_every_bit_it_claims(self):
        firmware = Firmware()
        probes = tool.run(firmware, GLOBAL_THREE, settle=0.0)
        for result in probes:
            assert result.changed == tool.expected_bits(result.param)


class TestTheWrongAddressTable:
    """A field the unit writes one bit away from the table's claim."""

    def test_the_verdict_is_mismatch_and_the_run_reports_failure(self):
        firmware = Firmware(shift=1)
        probes = tool.run(firmware, GLOBAL_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["mismatch"] * 3
        # Not silently passing: the run completes (a mismatch is a
        # finding, not an exception) and then fails.
        assert tool.succeeded(probes) is False
        # The restore still worked -- only the address is wrong.
        assert [p.restored for p in probes] == [True] * 3


class TestARestoreThatDoesNotVerify:
    def test_it_aborts_the_run_immediately(self, monkeypatch):
        firmware = Firmware(corrupt_from=1)  # pre-flight passes, then breaks
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert excinfo.value.preflight is False
        # It stopped at the first probe rather than probing the rest.
        assert firmware.edits == [
            (
                0,
                GLOBAL_THREE[0].function,
                GLOBAL_THREE[0].page,
                GLOBAL_THREE[0].pot,
                -1,
                0,
                0,
            )
        ]

    def test_the_cli_exit_would_be_non_zero(self, monkeypatch):
        monkeypatch.setattr(
            tool, "EditingDemo", lambda *, modes=(): Firmware(corrupt_from=1)
        )
        argv = ["--demo", "--mode", "global", "--limit", "3", "--settle", "0"]
        assert tool.main(argv) == 1


class TestThePreflightRefusal:
    def test_it_refuses_before_probing_anything(self):
        firmware = Firmware(corrupt_from=0)  # even the pre-flight load fails
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert excinfo.value.preflight is True
        assert firmware.edits == []
        assert 0x10 not in _functions(firmware)

    def test_the_cli_exits_two_for_a_preflight_refusal(self, monkeypatch):
        monkeypatch.setattr(
            tool, "EditingDemo", lambda *, modes=(): Firmware(corrupt_from=0)
        )
        argv = ["--demo", "--mode", "global", "--limit", "3", "--settle", "0"]
        assert tool.main(argv) == 2


class TestNoStoreOnTheWire:
    def test_a_probe_sends_only_the_edit_and_the_load(self):
        firmware = Firmware()
        tool.probe(firmware, GLOBAL_THREE[0], -1, settle=0.0)
        sent = _functions(firmware)
        assert sent, "the probe sent nothing, so it proved nothing"
        assert set(sent) <= {0x10, 0x02}
        assert 0x00 not in sent

    def test_a_whole_run_never_puts_the_store_opcode_on_the_wire(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE, settle=0.0)
        sent = set(_functions(firmware))
        assert 0x00 not in sent
        # 0x0D is mode_select: a mode change, never a store (rule 6).
        assert sent <= {0x10, 0x02, 0x0D}

    def test_the_source_never_names_a_store(self):
        # A source scan, not only a frame scan: the frames above prove
        # what this run sent, and this proves the store's encoder is not
        # even named in the code that sends -- one accidental import away
        # from a bank overwrite is a failure a green frame list cannot
        # show. The comments in the scan itself say why ``\b`` exempts
        # the load this tool is allowed to build.
        with open(_TOOL, encoding="utf-8") as handle:
            source = handle.read()
        assert _FORBIDDEN.search(source) is None


class TestSkippedRowsNeverReachTheWire:
    def test_a_spare_row_is_skipped_and_the_preflight_still_runs(self):
        firmware = Firmware()
        spare = next(row for row in params.PARAMS if row.function < 0)
        assert tool.probeable(spare) is False
        probes = tool.run(firmware, [spare], settle=0.0)

        assert probes == []
        assert firmware.edits == []
        assert 0x10 not in _functions(firmware)
        # Rule 4: a pre-flight restore with no probe runs anyway.
        assert firmware.events.count("write") == 2


class TestFlipValue:
    def test_the_flip_moves_every_bit_and_stays_inside_the_range(self):
        for param in FLIP_ROWS:
            assert param is not None
            mask = (1 << param.bits) - 1
            full = 0
            for value in range(param.low, param.high + 1):
                current = params.stored_for(param, value)
                # stored_for raises for anything outside low..high, so a
                # flip that left the range fails here rather than passing.
                flipped = params.stored_for(param, tool.flip_value(param, current))
                if flipped == current ^ mask:
                    full += 1
            assert full > 0, f"{param.label} never flips its whole field"

    def test_a_row_at_high_does_not_probe_itself_back(self):
        param = FLIP_ROWS[0]
        assert param is not None
        high_stored = params.stored_for(param, param.high)
        # Whichever end flip_value lands on, it must not be the value
        # already in the field: re-sending it would read "no-change".
        assert tool.flip_value(param, high_stored) != params.value_from_stored(
            param, high_stored
        )


class TestTheDemoWalkThrough:
    def test_three_confirmed_restored_rows_and_the_outputs(self, tmp_path, capsys):
        json_path = tmp_path / "probes.json"
        backup_dir = tmp_path / "backups"
        code = tool.main(
            [
                "--demo",
                "--mode",
                "global",
                "--limit",
                "3",
                "--settle",
                "0",
                "--json",
                str(json_path),
                "--backup-dir",
                str(backup_dir),
            ]
        )

        assert code == 0
        out = capsys.readouterr().out
        assert out.count("confirmed restored") == 3

        payload = json.loads(json_path.read_text())
        assert len(payload) == 3
        assert [row["verdict"] for row in payload] == ["confirmed"] * 3
        assert all(row["restored"] for row in payload)
        assert set(payload[0]) == {
            "mode",
            "function",
            "page",
            "pot",
            "sound",
            "channel",
            "label",
            "value",
            "target_stored",
            "verdict",
            "restored",
        }

        # The backup is the reference as an Edit Program Dump: opcode 02,
        # a load, with the 350-byte record packed inside it.
        packet = m.parse((backup_dir / "edit-buffer.syx").read_bytes())
        assert packet is not None
        assert packet.function == m.Function.EDIT_PROGRAM_DUMP
        assert packet.number == 0
        assert packet.data() == tool.EditingDemo(modes=("global",)).read_edit_program()

    def test_a_real_port_without_yes_sends_nothing(self, monkeypatch, capsys):
        def explode(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the port was opened without --yes")

        monkeypatch.setattr(tool.b.NanoBridge, "open", explode)
        assert tool.main(["--port", "X:1", "--mode", "global", "--limit", "3"]) == 0
        assert "dry run" in capsys.readouterr().out
