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

"""Banks, records and .syx files. Every fixture is invented."""

import pytest

from nano import banks, dumps
from nano import messages as m
from nano import records as rec


class TestTheFiveBanks:
    def test_there_are_640_programs(self):
        assert banks.TOTAL_PROGRAMS == 640
        assert len(banks.BANKS) * banks.PROGRAMS_PER_BANK == 640

    def test_bank_select_values_are_zero_to_four(self):
        assert [b.select for b in banks.BANKS] == [0, 1, 2, 3, 4]

    def test_only_one_bank_can_be_read_back(self):
        """The protocol has a program request for the user bank and for
        nothing else. Everything the browser shows for the other four
        comes from a catalog."""
        readable = banks.readable_banks()
        assert [b.id for b in readable] == ["USER"]

    def test_three_banks_are_out_of_the_front_panel_s_reach(self):
        """384 programs, which is most of the reason for this program."""
        hidden = [b for b in banks.BANKS if not b.front_panel]
        assert len(hidden) == 3
        assert sum(b.count for b in hidden) == 384

    def test_the_number_and_the_program_change_are_separate(self):
        """They agree on this instrument. They are still separate, because
        a helper that quietly converted was a real bug in a sibling."""
        slot = banks.slot("USER", 64)
        assert slot.number == 64
        assert slot.program_change == 64
        assert slot.number is not None and slot.program_change is not None

    def test_a_bank_select_and_program_change_resolve_to_a_slot(self):
        slot = banks.lookup(2, 33)
        assert slot.bank_id == "P1"
        assert slot.program_change == 33

    def test_an_unknown_bank_select_resolves_to_nothing(self):
        assert banks.lookup(5, 0) is None

    def test_the_silent_program_is_where_the_manual_says(self):
        bank_id, number = banks.SILENT_PROGRAM
        assert (bank_id, number) == ("USER", 127)

    def test_categories_are_sixteen_of_eight(self):
        assert len(banks.CATEGORIES) == 16
        assert banks.CATEGORY_SIZE == 8
        assert banks.slot("GM", 0).category == "Piano"
        assert banks.slot("GM", 127).category == "Effects"


class TestRecordSizes:
    def test_a_program_is_ten_common_bytes_and_four_sounds(self):
        assert rec.PROGRAM_BYTES == 350
        assert (rec.PROGRAM_COMMON + rec.SOUNDS_PER_PROGRAM * rec.SOUND_BYTES) == 350

    def test_a_mix_is_ten_common_bytes_and_sixteen_channels(self):
        assert rec.MIX_BYTES == 138
        assert (rec.MIX_COMMON + rec.MIX_CHANNELS * rec.MIX_CHANNEL_BYTES) == 138

    def test_a_short_record_is_refused(self):
        with pytest.raises(m.ProtocolError, match="fewer than"):
            rec.program_name(bytes(rec.PROGRAM_BYTES - 1))

    def test_a_long_record_is_not(self):
        """The instrument pads to a whole packing group."""
        record = bytearray(rec.PROGRAM_BYTES + 4)
        m.encode_name(record, "Invented")
        assert rec.program_name(record) == "Invented  "

    def test_a_sound_block_is_returned_whole(self):
        record = bytes(rec.PROGRAM_BYTES)
        assert len(rec.sound_block(record, 3)) == rec.SOUND_BYTES
        with pytest.raises(ValueError):
            rec.sound_block(record, 4)


def _dump(function, number, record, size):
    padded = bytes(record) + bytes(size - len(record))
    return m.frame(function, [number, *m.pack7(padded)])


class TestReadingSyxFiles:
    def _all_dump(self):
        raw = bytearray()
        for n in range(banks.PROGRAMS_PER_BANK):
            record = bytearray(rec.PROGRAM_BYTES)
            m.encode_name(record, f"Invented{n % 10}")
            raw += _dump(m.Function.USER_PROGRAM_DUMP, n, record, rec.PROGRAM_BYTES)
        for n in range(banks.MIXES):
            record = bytearray(rec.MIX_BYTES)
            m.encode_name(record, f"Set {n:02d}", rec.MIX_NAME_BIT_OFFSET)
            raw += _dump(m.Function.MIX_DUMP, n, record, rec.MIX_BYTES)
        raw += _dump(
            m.Function.GLOBAL_DUMP, 0, bytes(rec.GLOBAL_BYTES), rec.GLOBAL_BYTES
        )
        return bytes(raw)

    def test_an_all_dump_is_recognised(self):
        library = dumps.read_bytes(self._all_dump())
        assert len(library.programs) == 128
        assert len(library.mixes) == 100
        assert library.globals_ is not None
        assert library.is_all_dump

    def test_names_come_out(self):
        library = dumps.read_bytes(self._all_dump())
        assert library.program_names()[0] == "Invented0 "
        assert library.mix_names()[7].startswith("Set 07")

    def test_a_foreign_message_is_counted_not_fatal(self):
        raw = bytes([0xF0, 0x43, 0x00, 0xF7]) + self._all_dump()
        library = dumps.read_bytes(raw)
        assert library.foreign == 1
        assert library.is_all_dump

    def test_a_truncated_tail_is_dropped(self):
        raw = self._all_dump() + bytes([0xF0, 0x00, 0x00])
        library = dumps.read_bytes(raw)
        assert library.is_all_dump

    def test_splitting_finds_every_message(self):
        raw = self._all_dump()
        assert len(dumps.split_messages(raw)) == 128 + 100 + 1
