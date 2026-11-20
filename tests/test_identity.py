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
# nanosyned is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.

"""The content identity of one User program."""

from __future__ import annotations

import pytest

from nano import identity
from nano import messages as m
from nano import records as rec


def _record(name: str = "Init") -> bytes:
    """One synthetic, full-length program with a real encoded name."""
    record = bytearray((index * 7 + 3) & 0x7F for index in range(rec.PROGRAM_BYTES))
    m.encode_name(record, name, m.NAME_BIT_OFFSET)
    return bytes(record)


#: Pinned SHA-256 of `_record("Init")`; a byte change or a name change must
#: move it, and a serializer edit must not move it silently.
PINNED = (
    "58d8a3c9aa86f23305befd075794ba8d"  # pragma: allowlist secret
    "92d2af02e24081e303e3b8f75527e1e8"  # pragma: allowlist secret
)


class TestTheDigest:
    def test_the_synthetic_record_has_a_pinned_digest(self):
        assert identity.digest(_record()) == PINNED

    def test_same_bytes_have_the_same_digest(self):
        assert identity.digest(_record()) == identity.digest(_record())

    def test_one_parameter_byte_changes_the_digest(self):
        record = bytearray(_record())
        record[200] ^= 0x01

        assert identity.digest(bytes(record)) != PINNED

    def test_changing_only_the_name_changes_the_digest(self):
        assert identity.digest(_record("Init")) != identity.digest(_record("Other"))

    def test_padding_past_the_record_is_ignored(self):
        assert identity.digest(_record() + b"\x00\x01\x02") == PINNED

    def test_a_short_record_is_refused(self):
        with pytest.raises(m.ProtocolError):
            identity.digest(b"\x00" * (rec.PROGRAM_BYTES - 1))

    def test_the_digest_is_lower_case_hex(self):
        value = identity.digest(_record())

        assert len(value) == 64
        assert value == value.lower()
        assert all(character in "0123456789abcdef" for character in value)


class TestTheName:
    def test_the_name_is_stripped_of_padding(self):
        assert identity.program_name(_record("Init")) == "Init"

    def test_a_short_record_is_refused(self):
        with pytest.raises(m.ProtocolError):
            identity.program_name(b"\x00" * (rec.PROGRAM_BYTES - 1))
