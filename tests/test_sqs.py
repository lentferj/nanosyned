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

"""The MidiQuest ``.sqs`` container. Every fixture is invented."""

from nano import messages as m
from nano import records as rec
from nano import sqs


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + len(payload).to_bytes(4, "big") + payload


def _container(*bodies: bytes) -> bytes:
    """A LIST of FORMs, each with one BODY carrying ``bodies``' bytes."""
    forms = b"".join(_chunk(b"FORM", _chunk(b"BODY", body)) for body in bodies)
    return _chunk(b"LIST", b"    " + forms)


def _program(number: int, name: str) -> bytes:
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    return m.program_dump(number, record)


class TestRecognisingTheContainer:
    def test_a_list_file_is_a_container(self):
        assert sqs.is_sqs(_container(b""))

    def test_a_syx_file_is_not(self):
        assert not sqs.is_sqs(_program(0, "Invented0"))


class TestExtractingTheMessages:
    def _messages(self):
        return [
            _program(0, "Invented0"),
            m.global_dump(bytes(rec.GLOBAL_BYTES)),
            _program(1, "Invented1"),
        ]

    def test_every_alesis_message_comes_out_in_order(self):
        first, global_, second = self._messages()
        raw = _container(
            first + b"junk\x00\x01\x02" + global_,
            b"BANK\x00" + m.identity_request() + second,
        )
        assert sqs.extract_sysex(raw) == first + global_ + second

    def test_another_manufacturer_s_message_is_left_out(self):
        program = _program(0, "Invented0")
        foreign = bytes([0xF0, 0x41, 0x10, 0x42, 0xF7])
        raw = _container(foreign + program + foreign)
        assert sqs.extract_sysex(raw) == program

    def test_a_header_with_no_end_is_dropped(self):
        program = _program(0, "Invented0")
        raw = _container(program + sqs.HEADER + b"\x00\x01")
        assert sqs.extract_sysex(raw) == program

    def test_a_stray_f0_before_the_header_is_skipped(self):
        program = _program(0, "Invented0")
        raw = _container(b"\xf0\x7e\x7f" + program)
        assert sqs.extract_sysex(raw) == program

    def test_an_empty_container_extracts_nothing(self):
        assert sqs.extract_sysex(_container(b"")) == b""

    def test_a_container_of_foreign_messages_extracts_nothing(self):
        raw = _container(m.identity_request())
        assert sqs.extract_sysex(raw) == b""


class TestReadingBanks:
    def test_two_banks_same_slot_stay_distinct(self):
        first = _program(0, "BankZero")
        second = _program(0, "BankOne")
        raw = _container(first, second)
        banks = sqs.read_banks(raw)
        assert len(banks) == 2
        assert banks[0] == first
        assert banks[1] == second

    def test_form_bytes_inside_a_packed_message_do_not_split(self):
        # A "FORM" signature that falls inside an Alesis message span must
        # not become a bank boundary.
        embedded = sqs.HEADER + b"FORM" + b"\xf7"
        other = _program(1, "Other")
        raw = _container(embedded, other)
        banks = sqs.read_banks(raw)
        assert len(banks) == 2
        assert banks[0] == embedded
        assert banks[1] == other

    def test_junk_and_foreign_sysex_are_ignored(self):
        program = _program(0, "Kept")
        foreign = bytes([0xF0, 0x41, 0x10, 0x42, 0xF7])
        raw = _container(foreign + b"junk\x00\x01" + program + foreign)
        banks = sqs.read_banks(raw)
        assert len(banks) == 1
        assert banks[0] == program

    def test_a_missing_f7_drops_that_message_only(self):
        first = _program(0, "First")
        second = _program(1, "Second")
        # A header with no terminator between two valid messages.
        raw = _container(first + sqs.HEADER + b"\x00\x01" + second)
        banks = sqs.read_banks(raw)
        assert len(banks) == 1
        assert banks[0] == first + second

    def test_a_bank_with_no_alesis_message_is_empty(self):
        program = _program(0, "Only")
        raw = _container(b"", program)
        banks = sqs.read_banks(raw)
        assert len(banks) == 2
        assert banks[0] == b""
        assert banks[1] == program

    def test_a_list_with_one_form_is_one_bank(self):
        program = _program(0, "Solo")
        raw = _container(program)
        banks = sqs.read_banks(raw)
        assert len(banks) == 1
        assert banks[0] == program

    def test_extract_sysex_matches_concatenation(self):
        first = _program(0, "A")
        second = _program(1, "B")
        raw = _container(first, b"", second)
        assert sqs.extract_sysex(raw) == first + second
        assert sqs.extract_sysex(raw) == b"".join(sqs.read_banks(raw))
