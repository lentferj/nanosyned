# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The write rules, with no MIDI and no terminal.

Every fixture here is invented; nothing opens a port. ``editor.py`` is pure
for exactly this reason -- the gate and the rename rules are the part that
must be provable, so they are asked directly rather than by pressing a key.
"""

from nano import messages as m
from nano import params as p
from nano import records as rec
from nanosyned.editor import (
    DELETED_PARAMETER_REFUSAL,
    GATE_REFUSAL,
    EditGate,
    EditRecord,
    EffectsEditor,
    ProgramEditor,
    choice_text,
)


def _record(name: str = "Old Name") -> bytes:
    """A 350-byte program with ``name`` and a non-ASCII byte past it.

    The high bit on the last byte is there because a record of nothing but
    seven-bit name data would let a broken encode pass: the name bits are
    the only ones this editor may touch.
    """
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    record[-1] = 0x80 | 7
    return bytes(record)


class TestEditGate:
    def test_it_starts_locked(self):
        gate = EditGate()
        assert gate.armed is False
        assert gate.describe() == "write gate locked"

    def test_a_locked_gate_refuses_in_a_sentence_that_names_it(self):
        refusal = EditGate().check()
        assert refusal is not None
        assert "write gate" in refusal
        assert refusal == GATE_REFUSAL

    def test_toggling_arms_and_locks_again(self):
        gate = EditGate()
        assert gate.toggle() is True
        assert gate.armed is True
        assert gate.check() is None
        assert gate.describe() == "write gate armed"
        assert gate.toggle() is False
        assert gate.check() == GATE_REFUSAL

    def test_it_can_start_armed_for_allow_write(self):
        gate = EditGate(armed=True)
        assert gate.check() is None
        assert gate.describe() == "write gate armed"


class TestProgramEditor:
    def test_it_keeps_the_record_it_was_given(self):
        record = _record()
        editor = ProgramEditor(5, record)
        assert editor.number == 5
        assert editor.original == record
        assert editor.record() == record
        assert editor.dirty is False
        assert editor.name == "Old Name  "

    def test_a_valid_name_is_accepted_and_padded(self):
        editor = ProgramEditor(0, _record())
        assert editor.set_name("New") is None
        assert editor.name == "New       "
        assert editor.dirty is True

    def test_a_long_name_is_cut_to_the_instrument_width(self):
        editor = ProgramEditor(0, _record())
        assert editor.set_name("123456789012") is None
        assert editor.name == "1234567890"
        assert len(editor.name) == m.NAME_CHARS

    def test_a_character_outside_the_charset_is_refused(self):
        record = _record()
        editor = ProgramEditor(0, record)
        problem = editor.set_name("Noé")
        assert problem is not None
        assert "character set" in problem
        # Nothing was written, not even the two good characters before the
        # bad one: encode_name raises part-way, so the work is done on a
        # copy and only adopted when it succeeds.
        assert editor.record() == record
        assert editor.dirty is False
        assert editor.name == "Old Name  "

    def test_the_record_differs_from_the_original_only_in_the_name(self):
        record = _record()
        editor = ProgramEditor(3, record)
        assert editor.set_name("Fresh Name") is None
        changed = editor.record()
        assert changed != record
        # The name is bits 8..77: bytes 1 through 9 touched, byte 0 and
        # everything from byte 10 on exactly as read.
        assert changed[:1] == record[:1]
        assert changed[10:] == record[10:]
        assert changed[1:10] != record[1:10]
        assert rec.program_name(changed) == "Fresh Name"

    def test_reset_puts_the_original_back(self):
        record = _record()
        editor = ProgramEditor(0, record)
        editor.set_name("Changed")
        assert editor.dirty is True
        editor.reset()
        assert editor.dirty is False
        assert editor.record() == record
        assert editor.name == "Old Name  "

    def test_it_refuses_a_short_record(self):
        import pytest

        with pytest.raises(m.ProtocolError):
            ProgramEditor(0, bytes(rec.PROGRAM_BYTES - 1))


class TestEffectsEditor:
    def test_the_deleted_rows_are_not_offered(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        rows = editor.rows()
        # The specification keeps ten effects spares as deleted parameters;
        # the editor offers the rest, the whole record still carrying them.
        assert len(rows) == len(p.EFFECT_PARAMS) - 10
        assert all("deleted parameter" not in row.param.label for row in rows)
        assert "Effect configuration" in [row.param.label for row in rows]

    def test_the_real_configuration_rows_are_still_offered(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        labels = [row.param.label for row in editor.rows()]
        assert "Send 1 pitch type" in labels
        assert "Send 1 pitch speed" in labels

    def test_the_configuration_row_shows_the_name_at_the_record_value(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        assert editor.set_value("Effect configuration", 3) is None
        row = next(
            row for row in editor.rows() if row.param.label == "Effect configuration"
        )
        assert row.value == 3
        assert row.choice == "2 sends, with EQ"

    def test_a_named_switch_shows_off_and_on(self):
        enable = p.at("mix", 0, 0, 3)
        assert enable is not None
        assert choice_text(enable, 0) == "off"
        assert choice_text(enable, 1) == "on"

    def test_the_reverb_type_shows_the_name(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        row = next(row for row in editor.rows() if row.param.label == "Reverb type")
        assert row.value == 0
        assert row.choice == "Plate 1"
        assert editor.set_value("Reverb type", 6) is None
        row = next(row for row in editor.rows() if row.param.label == "Reverb type")
        assert row.choice == "Reverse"

    def test_set_value_refuses_a_deleted_parameter_and_keeps_the_record(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        before = editor.record()
        problem = editor.set_value("Effect spare (deleted parameter)", 5)
        assert problem is not None
        assert problem == DELETED_PARAMETER_REFUSAL
        assert editor.record() == before
        assert editor.dirty is False

    def test_editing_a_real_row_keeps_the_deleted_bytes(self):
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        original = editor.record()
        assert editor.set_value("MIDImod source 1", 3) is None
        changed = editor.record()
        assert changed != original
        # The hidden bytes are the ten deleted spares; a real edit must not
        # have moved them.
        assert changed[:10] == original[:10]


class TestEditRecord:
    def test_it_carries_the_slot_the_previous_bytes_and_the_old_name(self):
        record = _record()
        edit = EditRecord(number=12, previous=record, name="Old Name")
        assert edit.number == 12
        assert edit.previous == record
        assert edit.name == "Old Name"
        assert edit.label == "user program 012"
