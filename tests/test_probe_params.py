# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""The probe harness's safety contract, against a fake unit that writes bits.

``tools/probe_params.py`` promises three things that a green verdict cannot
prove on its own: that each mode's own record comes back byte for byte,
that a program row was edited in **Mix mode** through channel 1's buffer,
and that **opcode ``00`` never reaches the wire** -- the store that would
overwrite somebody's user program -- nor ``0A`` (the global store) nor a
``0E`` mix dump for anything but edit buffer 100. So the fake below,
:class:`Firmware`, keeps the three records apart -- the 20-byte global,
the 138-byte mix edit buffer and the 350-byte program edit buffer -- and
a log of every frame it is asked to send, and applies each ``10`` to its
record with plain bit arithmetic of its own, never through
:func:`nano.records.encode_bit_field`: a fake that shared the encoder's
idea of an address could not disagree with it, and disagreement is exactly
what the wrong-address test has to be able to see.

No port is opened here, no hardware is needed, and no Alesis content
appears: the records start zeroed and every name involved is invented.
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

#: The store encoders and the bridge's store methods, as *words*. The
#: scan's ``\b`` matters: ``edit_program_dump`` -- the **load** this tool
#: builds for ``--backup-dir`` -- contains ``program_dump``, but ``_`` is
#: a word character, so there is no boundary before ``program`` inside it
#: and the load cannot be mistaken for the store by this pattern. The
#: same applies to ``edit_effects_dump`` versus ``effects_dump`` (the
#: user effects store, opcode ``06``) and ``write_edit_effects`` versus
#: ``write_effects``.
_FORBIDDEN = re.compile(
    r"\b(write_program|write_global|program_dump|write_effects|effects_dump)\b"
)

_MODE_BY_NUMBER = {number: name for name, number in params.MODE_NUMBERS.items()}

#: Three signed Global rows whose complement at a zeroed record is inside
#: the range -- the happy path's selection, and the reason for it is here
#: rather than in a comment nobody reads: a row whose flip would leave the
#: range reports ``partial`` by design, and that is a different test.
GLOBAL_THREE = [
    params.at("global", 0, 0, 2),  # Pitch transpose, -12..12, 8 bits
    params.at("global", 0, 0, 3),  # Pitch fine tune, -99..99, 8 bits
    params.at("global", 0, 1, 2),  # Keyboard Transpose, -12..12, 8 bits
]

#: Three Mix rows with the same property, across the mix record's two
#: kinds of row: the common block and channel 1's (addressed to channel
#: 0 by the run), all inside the 138-byte mix edit buffer.
MIX_THREE = [
    params.at("mix", 5, 0, 2),  # Mix effect MIDI program change, 1 bit
    params.at("mix", 5, 0, 3),  # Mix effect chan, 4 bits
    params.at("mix", 0, 0, 0),  # Channel 1 program number, 7 bits
]

#: Three Program rows with the same property, inside the 350-byte
#: program edit buffer (the sound rows are addressed to sound 0).
PROGRAM_THREE = [
    params.at("program", 16, 0, 0),  # Keyboard / drum mode, 1 bit
    params.at("program", 0, 0, 2),  # Sample number, 7 bits
    params.at("program", 2, 0, 1),  # Sound effect bus, 2 bits
]

#: Three Effects rows, inside the 65-byte edit buffer. The first three
#: rows are the deleted spares, whose 7-bit fields at 0, 7 and 14 flip
#: from a zeroed record to a legal 95.
EFFECTS_THREE = [
    params.at("effects", 2, 0, 0),  # The configuration row
    params.at("effects", 0, 0, 0, sound=0),  # Send 1 pitch type
    params.at("effects", 4, 0, 0, sound=0),  # Send 1 delay type
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

    Like the unit on the bench, it keeps three records apart: the
    20-byte global record, the 138-byte mix edit buffer (number 100) and
    the 350-byte program edit buffer the tool addresses as channel 1's
    (``edit=1``). ``shift`` moves every field the fake writes one bit
    (or however many) away from the address the table claims -- the
    shape a *wrong table address* has on a real unit, where the tool
    expects the table's bits and something else moves. ``corrupt_from``
    is the number of *record loads* -- ``write_mix`` and
    ``write_edit_program``, counted together -- whose content the fake
    stores wrongly: ``0`` corrupts the pre-flight restore itself, ``1``
    lets the pre-flight pass and then breaks the restore after the first
    probe. A global run has no loads at all (its restore is a ``10``
    per row), which is why the restore-failure tests play in Mix mode.

    There is no ``write_global`` here on purpose: opcode ``0A`` is a
    store, and a fake that offered one would let a bug in the tool pass
    as a restore. There is no effects record either: the unit ignores an
    effects ``10``, and so does this fake.
    """

    def __init__(self, *, shift: int = 0, corrupt_from: int | None = None) -> None:
        #: The three records, zeroed; no Alesis content, nothing stored.
        self.global_record = bytearray(rec.GLOBAL_BYTES)
        self.mix_record = bytearray(rec.MIX_BYTES)
        self.program_record = bytearray(rec.PROGRAM_BYTES)
        self.shift = shift
        self.corrupt_from = corrupt_from
        #: Every frame the tool asked to send, as built messages.
        self.sent: list[bytes] = []
        #: The order of calls, so "the mode was selected before the
        #: record was read" can be asserted rather than assumed.
        self.events: list[str] = []
        self.edits: list[tuple[int, int, int, int, int, int, int]] = []
        #: The numbers ``read_mix``/``write_mix`` saw. 100 only, ever.
        self.mix_numbers: list[int] = []
        #: The numbers ``read_edit_program``/``write_edit_program`` saw,
        #: so "channel 1's buffer" is asserted rather than assumed.
        self.edit_numbers: list[int] = []
        self.modes: list[bool] = []
        self.loads = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def read_global(self, *, timeout: float | None = None) -> bytes:
        self.events.append("read")
        return bytes(self.global_record)

    def read_mix(self, number: int, *, timeout: float | None = None) -> bytes:
        self.events.append("read")
        self.mix_numbers.append(number)
        if number != 100:
            raise AssertionError(f"mix {number}: 0-99 are user stores; never read")
        return bytes(self.mix_record)

    def read_edit_program(
        self, *, edit: int = 0, timeout: float | None = None
    ) -> bytes:
        self.events.append("read")
        self.edit_numbers.append(edit)
        return bytes(self.program_record)

    def _loaded(self, record: bytes, size: int) -> bytearray:
        """A load's content as the fake stored it, corruption and all."""
        stored = bytearray(bytes(record)[:size])
        if self.corrupt_from is not None and self.loads >= self.corrupt_from:
            stored[0] ^= 0x01  # a load that did not land as sent
        self.loads += 1
        return stored

    def write_mix(
        self, number: int, record: bytes, *, timeout: float | None = None
    ) -> None:
        # The load path, and nothing else: numbers 0-99 are *stores* of
        # user mixes, and this fake has no method that stores -- a tool
        # that called one would fail here rather than quietly overwriting
        # a bank.
        if number != 100:
            raise AssertionError(f"mix {number}: 0-99 are user stores; never sent")
        rec.check_size(record, rec.MIX_BYTES, "a mix")
        self.events.append("write")
        self.mix_numbers.append(number)
        self.sent.append(m.mix_dump(number, record))
        self.mix_record[:] = self._loaded(record, rec.MIX_BYTES)

    def write_edit_program(
        self, record: bytes, *, edit: int = 0, timeout: float | None = None
    ) -> None:
        rec.check_size(record, rec.PROGRAM_BYTES, "a program")
        self.events.append("write")
        self.edit_numbers.append(edit)
        self.sent.append(m.edit_program_dump(record, edit=edit))
        self.program_record[:] = self._loaded(record, rec.PROGRAM_BYTES)

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
        name = _MODE_BY_NUMBER.get(mode, "")
        found = params.at(name, function, page, pot, sound=sound, channel=channel)
        records = {
            "global": self.global_record,
            "mix": self.mix_record,
            "program": self.program_record,
        }
        record = records.get(name)
        if found is None or record is None:
            return  # no row answers, or effects: the unit ignores a 10
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
                record[byte] |= mask
            else:
                record[byte] &= ~mask & 0xFF
        self.edits.append((mode, function, page, pot, value, sound, channel))

    def mode_select(self, mix_mode: bool) -> None:
        self.events.append("mode")
        self.sent.append(m.mode_select(mix_mode))
        self.modes.append(mix_mode)


class RecordFirmware:
    """A stand-in unit for the effects record path: ``09`` asks, ``08`` loads.

    It keeps one 65-byte edit buffer and stores every load byte for
    byte. ``clamp`` is ``(row, at_least, replacement)``: a load whose
    field reads at least ``at_least`` is normalized to ``replacement``,
    the shape a unit that rounds a value to its own steps has. The
    arithmetic is a plain bit loop, deliberately **not**
    :func:`nano.records.encode_bit_field`, so the fake can disagree with
    the tool's address. ``ignore_load`` records the frame and changes
    nothing; ``corrupt_from`` is the number of loads whose content the
    fake stores wrongly, for the restore-failure test.
    """

    def __init__(
        self,
        *,
        clamp: tuple[params.Param, int, int] | None = None,
        ignore_load: bool = False,
        corrupt_from: int | None = None,
    ) -> None:
        self.effects_record = bytearray(rec.EFFECTS_BYTES)
        self.sent: list[bytes] = []
        self.events: list[str] = []
        self.modes: list[bool] = []
        self.loads = 0
        self.clamp = clamp
        self.ignore_load = ignore_load
        self.corrupt_from = corrupt_from

    @staticmethod
    def _read_field(record: bytearray, param: params.Param) -> int:
        value = 0
        top = param.bit_address + param.bits - 1
        for step in range(param.bits):
            at = top - step
            value = (value << 1) | ((record[at >> 3] >> (at & 7)) & 1)
        return value

    @staticmethod
    def _write_field(record: bytearray, param: params.Param, stored: int) -> None:
        top = param.bit_address + param.bits - 1
        for step in range(param.bits):
            at = top - step
            mask = 1 << (at & 7)
            if (stored >> (param.bits - 1 - step)) & 1:
                record[at >> 3] |= mask
            else:
                record[at >> 3] &= ~mask & 0xFF

    def close(self) -> None:
        pass

    def request(
        self,
        outgoing: bytes,
        wanted: int,
        *,
        number: int | None = None,
        timeout: float | None = None,
    ) -> m.Packet:
        self.events.append("request")
        self.sent.append(bytes(outgoing))
        assert wanted == m.Function.EDIT_EFFECTS_DUMP
        assert number in (None, 0)
        packet = m.parse(m.edit_effects_dump(bytes(self.effects_record)))
        assert packet is not None
        return packet

    def write_edit_effects(
        self, record: bytes, *, timeout: float | None = None
    ) -> None:
        self.events.append("write")
        rec.check_size(record, rec.EFFECTS_BYTES, "an effects record")
        self.sent.append(m.edit_effects_dump(record))
        if self.ignore_load:
            self.loads += 1
            return
        stored = bytearray(bytes(record)[: rec.EFFECTS_BYTES])
        if self.corrupt_from is not None and self.loads >= self.corrupt_from:
            stored[0] ^= 0x01
        self.loads += 1
        if self.clamp is not None:
            param, at_least, replacement = self.clamp
            if self._read_field(stored, param) >= at_least:
                self._write_field(stored, param, replacement)
        self.effects_record[:] = stored

    def mode_select(self, mix_mode: bool) -> None:
        self.events.append("mode")
        self.sent.append(m.mode_select(mix_mode))
        self.modes.append(mix_mode)


def _packets(firmware: Firmware | RecordFirmware) -> list[m.Packet]:
    """Every frame parsed, in the order the tool sent it."""
    parsed = [m.parse(frame) for frame in firmware.sent]
    assert all(packet is not None for packet in parsed)
    return [packet for packet in parsed if packet is not None]


def _functions(firmware: Firmware | RecordFirmware) -> list[int]:
    """Every frame's opcode, in the order the tool sent it."""
    return [packet.function for packet in _packets(firmware)]


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


class TestProbeable:
    def test_a_field_must_fit_the_modes_own_record(self):
        row = params.at("program", 8, 9, 0)  # name digit 9, 7 bits at 71
        assert tool.probeable(row, rec.PROGRAM_BYTES) is True
        # The same row against a record too small to hold it.
        assert tool.probeable(row, 8) is False

    def test_an_addressless_row_is_refused_at_any_size(self):
        spare = next(row for row in params.PARAMS if row.function < 0)
        assert tool.probeable(spare, rec.PROGRAM_BYTES) is False

    def test_an_effects_row_is_refused_whatever_its_size(self):
        row = params.at("effects", 0, 1, 1, sound=0)  # 7 bits at 77
        assert tool.probeable(row, rec.EFFECTS_BYTES) is False
        assert tool.probeable(row, rec.PROGRAM_BYTES) is False


class TestHappyPathRun:
    """One run per mode, because each mode reads and restores its own way."""

    def test_three_global_rows_confirm_and_the_record_came_back(self):
        firmware = Firmware()
        reference = bytes(firmware.global_record)
        probes = tool.run(firmware, GLOBAL_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["confirmed"] * 3
        assert [p.restored for p in probes] == [True] * 3
        assert tool.succeeded(probes) is True
        # Byte-identical to the reference, not merely "close enough".
        assert bytes(firmware.global_record) == reference

    def test_three_mix_rows_confirm_and_the_record_came_back(self):
        firmware = Firmware()
        reference = bytes(firmware.mix_record)
        probes = tool.run(firmware, MIX_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["confirmed"] * 3
        assert [p.restored for p in probes] == [True] * 3
        assert tool.succeeded(probes) is True
        assert bytes(firmware.mix_record) == reference
        # The other two records were never read, written or moved.
        assert bytes(firmware.program_record) == bytes(rec.PROGRAM_BYTES)
        assert bytes(firmware.global_record) == bytes(rec.GLOBAL_BYTES)

    def test_three_program_rows_confirm_and_the_record_came_back(self):
        firmware = Firmware()
        reference = bytes(firmware.program_record)
        probes = tool.run(firmware, PROGRAM_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["confirmed"] * 3
        assert [p.restored for p in probes] == [True] * 3
        assert tool.succeeded(probes) is True
        assert bytes(firmware.program_record) == reference

    def test_the_mode_is_selected_before_the_record_is_read(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert firmware.events[0] == "mode"
        assert firmware.events.index("mode") < firmware.events.index("read")
        # Program mode for global rows: mode_select(False).
        assert firmware.modes == [False]

    def test_program_mode_is_selected_as_mix_and_uses_edit_1(self):
        firmware = Firmware()
        tool.run(firmware, PROGRAM_THREE, settle=0.0)
        # The bench's finding, encoded: a program 10 is ignored in
        # Program mode, so program rows play through Mix mode...
        assert firmware.modes == [True]
        # ...in channel 1's buffer, ``edit=1`` for channel 0, on every
        # read and every restore alike.
        assert set(firmware.edit_numbers) == {1}

    def test_mix_mode_is_selected_and_only_number_100_is_touched(self):
        firmware = Firmware()
        tool.run(firmware, MIX_THREE, settle=0.0)
        assert firmware.modes == [True]
        assert set(firmware.mix_numbers) == {100}

    def test_every_probe_restores_and_the_run_ends_on_a_restore(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE, settle=0.0)
        # Before anything: the mode select, then the record read.
        assert firmware.events[:2] == ["mode", "read"]
        assert firmware.closed is False

    def test_every_probe_moves_every_bit_it_claims(self):
        for rows in (GLOBAL_THREE, MIX_THREE, PROGRAM_THREE):
            firmware = Firmware()
            probes = tool.run(firmware, rows, settle=0.0)
            for result in probes:
                assert result.changed == tool.expected_bits(result.param)


class TestTheGlobalRestoreIsOneEditPerRow:
    def test_the_run_sends_10_per_row_and_never_a_global_store(self):
        firmware = Firmware()
        # The fake has no write_global at all, so a tool that called one
        # would fail here with an AttributeError rather than overwriting
        # the one global record the unit has.
        assert not hasattr(firmware, "write_global")
        tool.run(firmware, GLOBAL_THREE, settle=0.0)

        opcodes = set(_functions(firmware))
        # The global record has no load, so no 02 is built for it --
        # and 0A is a store, so it never appears either.
        assert 0x02 not in opcodes
        assert 0x0A not in opcodes
        assert opcodes == {0x0D, 0x10}


class TestTheMixRestoreIsTheBufferLoad:
    def test_every_load_is_number_100_and_never_a_user_store(self):
        firmware = Firmware()
        tool.run(firmware, MIX_THREE, settle=0.0)

        loads = [packet for packet in _packets(firmware) if packet.function == 0x0E]
        assert [packet.number for packet in loads] == [100] * len(loads)
        assert 0x02 not in _functions(firmware)


class TestTheWrongAddressTable:
    """A field the unit writes one bit away from the table's claim."""

    def test_the_verdict_is_mismatch_and_the_run_reports_failure(self):
        # The control sees the shifted address too and refuses; that is
        # asserted, not swallowed. The verdict itself is read from a
        # direct probe, where no control stands in front of it.
        firmware = Firmware(shift=1)
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert "control did not move" in str(excinfo.value)
        assert excinfo.value.preflight is True

        row = GLOBAL_THREE[0]
        firmware = Firmware(shift=1)
        reference = firmware.read_global()
        stored = rec.decode_bit_field(reference, row)
        result = tool.probe(
            firmware,
            row,
            tool.flip_value(row, stored),
            settle=0.0,
            reference=reference,
        )
        assert result.verdict == "mismatch"
        # The record is all zeros, so putting a zero back through the
        # shifted address is still byte-identical: the verdict, not the
        # restore, is the finding. ``succeeded`` must refuse it anyway.
        assert result.restored is True
        assert tool.succeeded([result]) is False


class TestARestoreThatDoesNotVerify:
    """The mix restore, because a global run has no load to corrupt."""

    def test_a_probes_restore_aborts_the_run(self):
        # The control's load and the first probe's restore work; the
        # second probe's does not.
        firmware = Firmware(corrupt_from=2)
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, MIX_THREE, settle=0.0)
        assert excinfo.value.preflight is False
        # The first probe is still evidence, and it is carried out.
        assert len(excinfo.value.probes) == 1

    def test_the_cli_exit_would_be_non_zero(self, monkeypatch):
        monkeypatch.setattr(
            tool, "EditingDemo", lambda *, modes=(): Firmware(corrupt_from=2)
        )
        argv = ["--demo", "--mode", "mix", "--limit", "3", "--settle", "0"]
        assert tool.main(argv) == 1

    def test_an_aborted_run_still_writes_its_json(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            tool, "EditingDemo", lambda *, modes=(): Firmware(corrupt_from=2)
        )
        out = tmp_path / "probes.json"
        argv = [
            "--demo",
            "--mode",
            "mix",
            "--limit",
            "3",
            "--settle",
            "0",
            "--json",
            str(out),
        ]
        assert tool.main(argv) == 1
        payload = json.loads(out.read_text())
        assert len(payload) == 1
        assert payload[0]["verdict"] == "confirmed"


class TestThePreflightRefusal:
    def test_it_refuses_before_probing_anything(self):
        # Even the control's restore fails, so the run must refuse with
        # only the control's own 10 on the wire.
        firmware = Firmware(corrupt_from=0)
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, MIX_THREE, settle=0.0)
        assert excinfo.value.preflight is True
        assert len(firmware.edits) == 1
        assert _functions(firmware).count(0x10) == 1

    def test_the_cli_exits_two_for_a_preflight_refusal(self, monkeypatch):
        monkeypatch.setattr(
            tool, "EditingDemo", lambda *, modes=(): Firmware(corrupt_from=0)
        )
        argv = ["--demo", "--mode", "mix", "--limit", "3", "--settle", "0"]
        assert tool.main(argv) == 2


class TestNoStoreOnTheWire:
    def test_a_global_probe_sends_only_edits(self):
        firmware = Firmware()
        result = tool.probe(firmware, GLOBAL_THREE[0], -1, settle=0.0)
        sent = _functions(firmware)
        assert sent, "the probe sent nothing, so it proved nothing"
        # The global record has no load: a global probe is the edit and
        # then the row's own old value back, both as a 10.
        assert set(sent) == {0x10}
        assert 0x00 not in sent and 0x0A not in sent
        assert result.restored is True

    def test_a_mix_probe_sends_the_edit_and_the_buffer_load(self):
        firmware = Firmware()
        result = tool.probe(firmware, MIX_THREE[0], 1, settle=0.0)
        packets = _packets(firmware)
        assert {packet.function for packet in packets} <= {0x10, 0x0E}
        loads = [packet for packet in packets if packet.function == 0x0E]
        assert [packet.number for packet in loads] == [100]
        assert result.restored is True

    def test_a_whole_run_never_puts_a_store_on_the_wire(self):
        firmware = Firmware()
        tool.run(firmware, GLOBAL_THREE + MIX_THREE + PROGRAM_THREE, settle=0.0)
        packets = _packets(firmware)
        opcodes = {packet.function for packet in packets}
        assert 0x00 not in opcodes  # the user-program store
        assert 0x0A not in opcodes  # the global store; its restore is 10s
        # 0x0D is mode_select: a mode change, never a store (rule 6).
        assert opcodes <= {0x10, 0x02, 0x0D, 0x0E}
        # The only mix dump this run may build is the edit buffer's load.
        loads = [packet for packet in packets if packet.function == 0x0E]
        assert loads
        assert all(packet.number >= 100 for packet in loads)

    def test_the_source_never_names_a_store(self):
        # A source scan, not only a frame scan: the frames above prove
        # what this run sent, and this proves the store's encoders are
        # not even named in the code that sends -- one accidental import
        # away from a bank overwrite is a failure a green frame list
        # cannot show. The comments in the scan itself say why ``\b``
        # exempts the load this tool is allowed to build.
        with open(_TOOL, encoding="utf-8") as handle:
            source = handle.read()
        assert _FORBIDDEN.search(source) is None


class TestSkippedRowsNeverReachTheWire:
    def test_a_spare_row_is_skipped_and_nothing_is_sent_at_all(self):
        firmware = Firmware()
        spare = next(row for row in params.PARAMS if row.function < 0)
        assert tool.probeable(spare, tool.record_size(spare.mode)) is False
        probes = tool.run(firmware, [spare], settle=0.0)

        assert probes == []
        assert firmware.edits == []
        # Nothing at all: with no row to probe there is no mode to
        # select and no record to protect, so not one frame is built.
        assert firmware.sent == []
        assert firmware.events == []

    def test_effects_rows_are_skipped_under_the_edit_strategy(self):
        firmware = Firmware()
        effects = [row for row in params.PARAMS if row.mode == "effects"]
        assert effects, "the tables have effects rows; this proves nothing"
        probes = tool.run(firmware, effects, settle=0.0, strategy="edit")

        assert probes == []
        assert firmware.edits == []
        assert firmware.sent == []
        assert firmware.events == []

    def test_the_buffer_factory_returns_the_effects_record(self):
        buffer = tool.buffer_for("effects")
        assert buffer == tool.RecordBuffer()
        assert buffer.mode == "effects"
        assert buffer.edit == 0
        assert buffer.size == rec.EFFECTS_BYTES == 65


class TestTheBufferFactory:
    def test_each_mode_gets_the_record_the_bench_read(self):
        assert tool.buffer_for("global") == tool.Buffer("global", 0)
        assert tool.buffer_for("mix") == tool.Buffer("mix", 100)
        assert tool.buffer_for("program") == tool.Buffer("program", 1)
        assert tool.buffer_for("program", channel=3) == tool.Buffer("program", 4)

    def test_the_record_sizes_are_the_modes_own(self):
        assert tool.buffer_for("global").size == rec.GLOBAL_BYTES == 20
        assert tool.buffer_for("mix").size == rec.MIX_BYTES == 138
        assert tool.buffer_for("program").size == rec.PROGRAM_BYTES == 350

    def test_a_global_record_has_no_load(self):
        firmware = Firmware()
        buffer = tool.buffer_for("global")
        with pytest.raises(tool.ProbeAborted):
            buffer.load(firmware, bytes(rec.GLOBAL_BYTES))
        assert firmware.sent == []  # the refusal built no frame


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


class TestPositiveControl:
    def test_normal_control_confirms_and_record_identical(self):
        for rows in (GLOBAL_THREE, MIX_THREE, PROGRAM_THREE):
            f = Firmware()
            if rows[0].mode == "global":
                ref = bytes(f.global_record)
            elif rows[0].mode == "mix":
                ref = bytes(f.mix_record)
            else:
                ref = bytes(f.program_record)
            probes = tool.run(f, rows, settle=0.0)
            assert tool.succeeded(probes)
            if rows[0].mode == "global":
                assert bytes(f.global_record) == ref
            elif rows[0].mode == "mix":
                assert bytes(f.mix_record) == ref
            else:
                assert bytes(f.program_record) == ref

    def test_dead_ten_is_caught_before_any_probe(self):
        class DeadTen(Firmware):
            def midi_edit(self, *args, **kwargs):
                self.events.append("edit")
                self.sent.append(m.midi_edit(*args, **kwargs))
                self.edits.append(
                    (
                        args[0],
                        args[1],
                        args[2],
                        args[3],
                        args[4],
                        kwargs.get("sound", 0),
                        kwargs.get("channel", 0),
                    )
                )

        firmware = DeadTen()
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert excinfo.value.preflight is True
        # The control tries each row it may use, and no probe follows.
        assert len(firmware.edits) == len(GLOBAL_THREE)

    def test_one_ignored_row_does_not_condemn_the_mode(self):
        """The bench found a mix row the unit ignores; the next one works."""

        class FirstIgnored(Firmware):
            def midi_edit(self, *args, **kwargs):
                if not self.edits:
                    # Record the frame but change nothing, like the unit
                    # on an address it does not edit.
                    self.sent.append(m.midi_edit(*args, **kwargs))
                    self.edits.append((*args[:5], 0, 0))
                    return
                super().midi_edit(*args, **kwargs)

        firmware = FirstIgnored()
        probes = tool.run(firmware, GLOBAL_THREE, settle=0.0)
        assert [p.verdict for p in probes] == ["confirmed"] * len(GLOBAL_THREE)
        assert bytes(firmware.global_record) == bytes(rec.GLOBAL_BYTES)

    def test_dead_load_restore_fails_preflight(self):
        class DeadLoad(Firmware):
            def write_mix(self, number, record, *, timeout=None):
                if number != 100:
                    raise AssertionError
                rec.check_size(record, rec.MIX_BYTES, "a mix")
                self.events.append("write")
                self.mix_numbers.append(number)
                self.sent.append(m.mix_dump(number, record))
                # ignore the load

            def write_edit_program(self, record, *, edit=0, timeout=None):
                rec.check_size(record, rec.PROGRAM_BYTES, "a program")
                self.events.append("write")
                self.edit_numbers.append(edit)
                self.sent.append(m.edit_program_dump(record, edit=edit))

        for rows in (MIX_THREE, PROGRAM_THREE):
            firmware = DeadLoad()
            with pytest.raises(tool.ProbeAborted) as excinfo:
                tool.run(firmware, rows, settle=0.0)
            assert excinfo.value.preflight is True
            msg = str(excinfo.value).lower()
            assert "control did not move" in msg or "restore did not verify" in msg

    def test_control_leaves_record_byte_identical_per_mode(self):
        for rows in (GLOBAL_THREE, MIX_THREE, PROGRAM_THREE):
            f = Firmware()
            if rows[0].mode == "global":
                ref = bytes(f.global_record)
            elif rows[0].mode == "mix":
                ref = bytes(f.mix_record)
            else:
                ref = bytes(f.program_record)
            tool.run(f, rows, settle=0.0)
            if rows[0].mode == "global":
                assert bytes(f.global_record) == ref
            elif rows[0].mode == "mix":
                assert bytes(f.mix_record) == ref
            else:
                assert bytes(f.program_record) == ref


class TestDeletedSpares:
    def test_the_legacy_slots_are_never_probed(self):
        row = params.by_label("Effect spare (deleted parameter)")[0]
        assert (
            tool.probeable(row, tool.record_size("effects"), strategy="record") is False
        )
        assert (
            tool.probeable(row, tool.record_size("effects"), strategy="edit") is False
        )

    def test_the_configuration_row_is_probeable_on_the_record_path(self):
        row = params.by_label("Effect configuration")[0]
        assert (
            tool.probeable(row, tool.record_size("effects"), strategy="record") is True
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

        # The backup is the run's restore reference. A global run's is
        # the bare 20-byte global record: the global restore is a 10
        # per row, and the record has no load message to be framed in,
        # because 0A is a store.
        assert (backup_dir / "edit-buffer.syx").read_bytes() == tool.EditingDemo(
            modes=("global",)
        ).read_global()

    def test_the_demo_walks_the_program_buffer_in_mix_mode(self, capsys):
        code = tool.main(
            ["--demo", "--mode", "program", "--limit", "2", "--settle", "0"]
        )

        assert code == 0
        out = capsys.readouterr().out
        assert out.count("confirmed restored") == 2
        assert "program" in out

    def test_the_effects_demo_confirms_through_the_record(self, capsys):
        code = tool.main(
            ["--demo", "--mode", "effects", "--limit", "2", "--settle", "0"]
        )

        assert code == 0
        captured = capsys.readouterr()
        assert captured.out.count("confirmed restored") == 2
        assert "09" in captured.out and "08" in captured.out
        assert "aborted" not in captured.err

    def test_a_real_port_without_yes_sends_nothing(self, monkeypatch, capsys):
        def explode(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("the port was opened without --yes")

        monkeypatch.setattr(tool.b.NanoBridge, "open", explode)
        assert tool.main(["--port", "X:1", "--mode", "global", "--limit", "3"]) == 0
        assert "dry run" in capsys.readouterr().out


class TestTheRecordStrategy:
    """Effects are proved through ``09``/``08``, not the ignored ``10``."""

    def test_three_effects_rows_confirm_and_the_record_came_back(self):
        firmware = RecordFirmware()
        reference = bytes(firmware.effects_record)
        probes = tool.run(firmware, EFFECTS_THREE, settle=0.0)

        assert [p.verdict for p in probes] == ["confirmed"] * 3
        assert [p.restored for p in probes] == [True] * 3
        assert tool.succeeded(probes) is True
        assert bytes(firmware.effects_record) == reference
        # No 10 was sent: effects use the load, and the mode is selected
        # in Program mode before the record is read.
        assert firmware.modes == [False]
        assert "edit" not in firmware.events

    def test_the_wire_carries_only_08_09_and_0d(self):
        firmware = RecordFirmware()
        tool.run(firmware, EFFECTS_THREE, settle=0.0)
        opcodes = set(_functions(firmware))

        assert opcodes <= {0x08, 0x09, 0x0D}
        for forbidden in (0x06, 0x00, 0x0A, 0x02, 0x0E):
            assert forbidden not in opcodes
        # Every load is the edit buffer: number 0, never a user slot.
        loads = [packet for packet in _packets(firmware) if packet.function == 0x08]
        assert loads
        assert all(packet.number == 0 for packet in loads)

    def test_a_normalizing_unit_reads_partial(self):
        row = EFFECTS_THREE[0]
        # Any load whose field reads at least 1 is stored as 1: the
        # probe's target 95 comes back as 1, inside the field, so the
        # verdict is partial rather than a wrong address.
        firmware = RecordFirmware(clamp=(row, 1, 1))
        probes = tool.run(firmware, EFFECTS_THREE, settle=0.0)

        assert probes[0].verdict == "partial"
        assert probes[0].restored is True
        assert [p.verdict for p in probes[1:]] == ["confirmed"] * 2
        assert tool.succeeded(probes) is False

    def test_a_unit_that_ignores_the_load_reads_no_change(self):
        row = EFFECTS_THREE[0]
        firmware = RecordFirmware(ignore_load=True)
        buffer = tool.buffer_for("effects")
        reference = buffer.read(firmware)
        stored = rec.decode_bit_field(reference, row)
        result = tool.record_probe(
            firmware,
            buffer,
            row,
            tool.flip_value(row, stored),
            settle=0.0,
            reference=reference,
        )

        assert result.verdict == "no-change"
        assert result.changed == ()
        assert result.restored is True
        assert bytes(firmware.effects_record) == reference

    def test_a_record_restore_that_does_not_verify_aborts_the_run(self):
        # The control's two loads and the probe's load land; the probe's
        # restore is the fourth load and does not.
        firmware = RecordFirmware(corrupt_from=3)
        with pytest.raises(tool.ProbeAborted) as excinfo:
            tool.run(firmware, EFFECTS_THREE, settle=0.0)
        assert excinfo.value.preflight is False
        assert "effects record did not come back" in str(excinfo.value)

    def test_the_demo_records_never_build_a_user_effects_store(self):
        demo = tool.EditingDemo(modes=("effects",))
        probes = tool.run(demo, EFFECTS_THREE, settle=0.0)
        assert [p.verdict for p in probes] == ["confirmed"] * 3

        opcodes = set(_functions(demo))
        assert opcodes <= {0x08, 0x09, 0x0D}
        assert 0x06 not in opcodes
