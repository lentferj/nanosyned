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

"""Init bank core: the template, whole-record equality, the append scan.

Every record here is synthetic; nothing opens a port or a file.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from nano import initbank, messages
from nano import records as rec

#: A byte in the sound blocks, never in the ten-character name: flipping
#: it leaves the name readable and the record different.
_NON_NAME_BYTE = 200


def _off_record() -> bytes:
    """A synthetic 127 ``Off`` record: a patterned fill, then its name."""
    record = bytearray(rec.PROGRAM_BYTES)
    for index in range(rec.PROGRAM_BYTES):
        record[index] = (index * 11 + 5) & 0x7F
    messages.encode_name(record, "Off")
    return bytes(record)


def _flipped(template: bytes) -> bytes:
    """``template`` with one sound-block byte changed; the name stays."""
    record = bytearray(template)
    record[_NON_NAME_BYTE] ^= 0x01
    return bytes(record)


def _read_with_non_init(template: bytes, non_init: set[int]) -> Callable[[int], bytes]:
    """A read over slots 0-126: ``non_init`` slots return non-Init records."""

    def read(number: int) -> bytes:
        if number in non_init:
            return _flipped(template)
        return template

    return read


class TestInitRecord:
    def test_changes_only_the_name(self):
        off = _off_record()
        record = initbank.init_record(off)
        expected = bytearray(off)
        messages.encode_name(expected, initbank.INIT_NAME, messages.NAME_BIT_OFFSET)
        assert record == bytes(expected)
        assert len(record) == rec.PROGRAM_BYTES

    def test_name_decodes_as_init_and_source_was_not(self):
        assert rec.program_name(initbank.init_record(_off_record())).rstrip() == "Init"
        assert rec.program_name(_off_record()).rstrip() == "Off"

    def test_a_padded_record_is_cut_to_the_documented_size(self):
        off = _off_record()
        padded = off + bytes(11)
        assert initbank.init_record(padded) == initbank.init_record(off)
        assert len(initbank.init_record(padded)) == rec.PROGRAM_BYTES

    def test_a_short_record_is_refused(self):
        with pytest.raises(ValueError):
            initbank.init_record(_off_record()[: rec.PROGRAM_BYTES - 1])


class TestIsInit:
    def test_the_exact_template_is_init(self):
        template = initbank.init_record(_off_record())
        assert initbank.is_init(template, template)

    def test_a_longer_record_is_truncated(self):
        template = initbank.init_record(_off_record())
        assert initbank.is_init(template + bytes(5), template)

    def test_a_changed_parameter_byte_is_not_init(self):
        template = initbank.init_record(_off_record())
        assert not initbank.is_init(_flipped(template), template)

    def test_a_same_name_different_bytes_record_is_not_init(self):
        template = initbank.init_record(_off_record())
        same_name = _flipped(template)
        # The name still reads Init; the bytes behind it do not match.
        assert rec.program_name(same_name).rstrip() == "Init"
        assert not initbank.is_init(same_name, template)

    def test_a_short_record_is_not_init(self):
        template = initbank.init_record(_off_record())
        assert not initbank.is_init(template[: rec.PROGRAM_BYTES - 1], template)
        assert not initbank.is_init(b"", template)


class TestAppendStart:
    def test_all_init_returns_zero(self):
        template = initbank.init_record(_off_record())
        assert initbank.append_start(lambda number: template, template) == 0

    def test_top_slot_non_init_returns_127(self):
        template = initbank.init_record(_off_record())
        read = _read_with_non_init(template, {126})
        assert initbank.append_start(read, template) == 127

    def test_a_gap_below_returns_after_the_highest_non_init(self):
        template = initbank.init_record(_off_record())
        read = _read_with_non_init(template, {50})
        assert initbank.append_start(read, template) == 51

    def test_mixed_bank_returns_after_the_highest_non_init(self):
        template = initbank.init_record(_off_record())
        read = _read_with_non_init(template, {99, 50})
        assert initbank.append_start(read, template) == 100

    def test_a_failed_read_propagates(self):
        template = initbank.init_record(_off_record())

        def read(number: int) -> bytes:
            if number == 42:
                raise ValueError("read failed at 42")
            return template

        with pytest.raises(ValueError, match="read failed at 42"):
            initbank.append_start(read, template)
