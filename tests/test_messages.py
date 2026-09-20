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

"""The wire format. Every fixture is invented."""

import pytest

from nano import banks
from nano import messages as m
from nano import records as rec


class TestPacking:
    """Seven 8-bit bytes travel as eight 7-bit ones, low bits first."""

    def test_it_round_trips(self):
        data = bytes(range(256)) * 2
        assert m.unpack7(m.pack7(data))[:len(data)] == data

    def test_a_program_packs_to_the_size_the_wire_carries(self):
        """350 bytes become 400. Measured against the instrument."""
        packed = m.pack7(bytes(rec.PROGRAM_BYTES))
        assert len(packed) == rec.PROGRAM_PACKED

    def test_nothing_packed_has_bit_7_set(self):
        for byte in m.pack7(bytes(range(256))):
            assert byte <= 0x7F

    def test_a_packed_byte_with_bit_7_set_is_refused(self):
        """Impossible on the wire; reachable from a corrupt file."""
        with pytest.raises(m.ProtocolError, match="bit 7"):
            m.unpack7(bytes([0x00, 0x80, 0x00]))

    def test_the_direction_matters(self):
        """A high-bits-first reading of real data is not an error.

        It yields a record of exactly the right length full of plausible
        nonsense, which is why the bit order is stated in the docstring
        and pinned here rather than left to the reader.
        """
        data = bytes(range(7))
        forward = m.unpack7(m.pack7(data))[:7]
        backward = bytes(reversed(m.unpack7(bytes(
            reversed(m.pack7(data))))[:7]))
        assert forward == data
        assert backward != data


class TestNames:
    """Ten characters of seven bits, and not on a byte boundary."""

    def test_a_name_round_trips(self):
        record = bytearray(rec.PROGRAM_BYTES)
        m.encode_name(record, "Invented")
        assert m.decode_name(record) == "Invented  "

    def test_it_fills_ten_characters(self):
        record = bytearray(rec.PROGRAM_BYTES)
        m.encode_name(record, "A name that is far too long")
        assert len(m.decode_name(record)) == m.NAME_CHARS

    def test_the_character_set_has_an_edge(self):
        record = bytearray(rec.PROGRAM_BYTES)
        with pytest.raises(m.ProtocolError, match="character set"):
            m.encode_name(record, "\t")

    def test_a_mix_name_is_at_a_different_offset(self):
        """Five bits in, not eight, and reading it wrong does not fail.

        It produces ten plausible characters of nonsense, which is how the
        difference was noticed in the first place.
        """
        record = bytearray(rec.MIX_BYTES)
        m.encode_name(record, "Invented", rec.MIX_NAME_BIT_OFFSET)
        assert rec.mix_name(record) == "Invented  "
        assert m.decode_name(record) != "Invented  ", (
            "if these agreed, the offset would not matter and this test "
            "would be proving nothing")


class TestFraming:
    def test_a_message_carries_the_alesis_extended_id(self):
        framed = m.frame(m.Function.GLOBAL_REQUEST, [0])
        assert framed[0] == m.SYSEX_START
        assert tuple(framed[1:4]) == m.ALESIS_ID
        assert framed[4] == m.QS_FAMILY
        assert framed[-1] == m.SYSEX_END

    def test_a_byte_with_bit_7_set_is_refused(self):
        with pytest.raises(m.ProtocolError, match="7-bit"):
            m.frame(m.Function.GLOBAL_REQUEST, [0x80])

    def test_a_foreign_message_parses_as_none(self):
        assert m.parse(bytes([0xF0, 0x43, 0x00, 0xF7])) is None
        assert m.parse(bytes([0xF0, 0x00, 0x00, 0x0E, 0x0F, 0x00,
                              0xF7])) is None

    def test_a_dump_carries_its_number_apart_from_its_payload(self):
        packed = m.pack7(bytes(rec.PROGRAM_BYTES))
        message = m.frame(m.Function.USER_PROGRAM_DUMP, [42, *packed])
        packet = m.parse(message)
        assert packet.number == 42
        assert len(packet.data()) >= rec.PROGRAM_BYTES

    def test_our_own_request_parses_as_a_valid_message(self):
        """Which is exactly why a reply is matched by opcode.

        The chain this was written against echoes everything sent. The
        echo is not malformed and cannot be rejected as such.
        """
        echo = m.parse(m.program_dump_request(5))
        assert echo is not None
        assert echo.function == m.Function.USER_PROGRAM_REQUEST
        assert echo.function != m.Function.USER_PROGRAM_DUMP


class TestIdentity:
    #: What this unit actually answered, byte for byte.
    REPLY = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02,
                   0x00, 0x00, 0x0E,        # Alesis, extended
                   0x0E, 0x00,              # QS family
                   0x07, 0x00,              # member: this box
                   0x30, 0x31, 0x30, 0x30,  # "0100"
                   0xF7])

    def test_it_is_recognised(self):
        fields = m.identity_reply_fields(self.REPLY)
        assert fields["is_alesis"]
        assert fields["is_qs_family"]
        assert fields["is_nanosynth"]
        assert fields["version"] == "0100"

    def test_a_request_is_never_taken_for_a_reply(self):
        """A thru loop returns the request, and this chain has one."""
        assert m.identity_reply_fields(m.identity_request()) is None

    def test_another_manufacturer_is_not_this_one(self):
        roland = bytes([0xF0, 0x7E, 0x10, 0x06, 0x02, 0x41, 0x10, 0x01,
                        0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0xF7])
        fields = m.identity_reply_fields(roland)
        assert fields is not None
        assert not fields["is_alesis"]
        assert not fields["is_nanosynth"]


class TestSelection:
    def test_bank_select_is_controller_zero(self):
        """The unit ignores Controller 32; the manual is explicit."""
        messages = m.bank_select(2, channel=0)
        assert len(messages) == 1
        assert list(messages[0]) == [0xB0, 0x00, 0x02]

    def test_the_channel_lands_in_the_status_byte(self):
        assert list(m.bank_select(1, channel=9)[0])[0] == 0xB9
        assert list(m.program_change(5, channel=9))[0] == 0xC9

    def test_out_of_range_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.program_change(128)
        with pytest.raises(m.ProtocolError):
            m.bank_select(0, channel=16)


class TestRequests:
    def test_only_the_user_bank_has_a_program_request(self):
        """128 programs, and the ROM banks are not among them."""
        assert m.parse(m.program_dump_request(0)).number == 0
        with pytest.raises(m.ProtocolError, match="0-127"):
            m.program_dump_request(128)

    def test_a_mix_request_knows_there_are_a_hundred(self):
        assert m.parse(m.mix_dump_request(99)).number == 99
        with pytest.raises(m.ProtocolError, match="0-99"):
            m.mix_dump_request(100)

    def test_every_request_has_a_named_reply(self):
        for request, reply in m.Function.REPLY_TO.items():
            assert m.Function.name(request).endswith("Request")
            assert not m.Function.name(reply).endswith("Request")

    def test_every_opcode_used_here_has_a_name(self):
        """A timeout that says "no 0x00 came back" helps nobody."""
        for opcode in list(m.Function.REPLY_TO) + list(
                m.Function.REPLY_TO.values()):
            assert not m.Function.name(opcode).startswith("function ")


class TestTheEditBufferCarriesANumberToo:
    """An edit buffer is one thing, so its dump looks like it would carry
    no number. It carries one, always zero, and leaving it in the payload
    does not raise -- every field shifts eight bits and the name comes out
    one character over, which a reader would accept at a glance. It was
    found on the bench exactly that way.
    """

    def _dump(self, function, header):
        record = bytearray(rec.PROGRAM_BYTES)
        m.encode_name(record, "Invented")
        return m.frame(function, [*header, *m.pack7(bytes(record))])

    def test_an_edit_dump_number_is_stripped_from_the_payload(self):
        packet = m.parse(self._dump(m.Function.EDIT_PROGRAM_DUMP, [0]))
        assert packet.number == 0
        assert rec.program_name(packet.data()) == "Invented  "

    def test_edit_effects_are_numbered_the_same_way(self):
        packed = m.pack7(bytes(rec.EFFECTS_BYTES))
        packet = m.parse(m.frame(m.Function.EDIT_EFFECTS_DUMP, [0, *packed]))
        assert packet.number == 0

    def test_the_shift_it_guards_against_is_silent(self):
        """Proof the guard is needed: the wrong reading is not an error."""
        message = self._dump(m.Function.EDIT_PROGRAM_DUMP, [0])
        wrong = m.unpack7(bytes(message)[6:-1])      # number left in
        assert len(wrong) >= rec.PROGRAM_BYTES, "it is still the right size"
        assert m.decode_name(wrong) != "Invented  "
        assert m.decode_name(wrong).strip(), "and still looks like a name"
