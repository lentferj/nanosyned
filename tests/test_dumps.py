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

"""Reading files, whatever container they arrive in. Fixtures are invented."""

from nano import dumps
from nano import messages as m
from nano import records as rec


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + len(payload).to_bytes(4, "big") + payload


def _container(body: bytes) -> bytes:
    return _chunk(b"LIST", b"    " + _chunk(b"FORM", _chunk(b"BODY", body)))


def _messages() -> list[bytes]:
    first = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(first, "Invented0")
    second = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(second, "Invented1")
    effects = bytearray(rec.EFFECTS_BYTES)
    mix = bytearray(rec.MIX_BYTES)
    m.encode_name(mix, "Set 00", rec.MIX_NAME_BIT_OFFSET)
    return [
        m.program_dump(0, first),
        m.program_dump(1, second),
        m.effects_dump(0, effects),
        m.mix_dump(0, mix),
        m.global_dump(bytes(rec.GLOBAL_BYTES)),
    ]


class TestReadingSqsFiles:
    def test_a_bank_reads_as_the_syx_it_contains(self, tmp_path):
        path = tmp_path / "bank.sqs"
        path.write_bytes(_container(b"".join(_messages())))
        library = dumps.read_syx_file(str(path))
        assert library.summary() == ("2 program(s), 1 effects, 1 mix(es), global")
        assert library.program_names()[0].rstrip() == "Invented0"

    def test_a_plain_syx_is_unchanged(self, tmp_path):
        raw = b"".join(_messages())
        path = tmp_path / "all.syx"
        path.write_bytes(raw)
        library = dumps.read_syx_file(str(path))
        assert library.programs == dumps.read_bytes(raw).programs
        assert library.summary() == dumps.read_bytes(raw).summary()

    def test_a_container_with_no_alesis_messages_reads_empty(self, tmp_path):
        path = tmp_path / "empty.sqs"
        path.write_bytes(_container(b"\x00\x01\x02"))
        library = dumps.read_syx_file(str(path))
        assert library.summary() == "0 program(s)"
