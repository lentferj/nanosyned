# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""Importing: the source model. Fixtures are invented."""

from __future__ import annotations

import os

import pytest

from nano import importing
from nano import messages as m
from nano import records as rec


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + len(payload).to_bytes(4, "big") + payload


def _container(*bodies: bytes) -> bytes:
    forms = b"".join(_chunk(b"FORM", _chunk(b"BODY", body)) for body in bodies)
    return _chunk(b"LIST", b"    " + forms)


def _program(number: int, name: str) -> bytes:
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    return m.program_dump(number, record)


def _mix(number: int, name: str) -> bytes:
    record = bytearray(rec.MIX_BYTES)
    m.encode_name(record, name, rec.MIX_NAME_BIT_OFFSET)
    return m.mix_dump(number, record)


class TestSingleProgramSyx:
    def test_one_bank_one_program(self, tmp_path):
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        source = importing.read_import(str(path))
        assert source.kind == "syx"
        assert len(source.banks) == 1
        bank = source.banks[0]
        assert bank.label == "one.syx"
        assert len(bank.programs) == 1
        prog = bank.programs[7]
        assert prog.slot == 7
        assert prog.index == 0
        assert prog.name == "Invented7"
        assert len(prog.record) == rec.PROGRAM_BYTES
        assert source.summary().endswith(".")


class TestAllDumpSyx:
    def test_all_dump_reads(self, tmp_path):
        raw = bytearray()
        for n in range(128):
            record = bytearray(rec.PROGRAM_BYTES)
            m.encode_name(record, f"Invented{n % 10}")
            raw += m.program_dump(n, record)
        for n in range(100):
            record = bytearray(rec.MIX_BYTES)
            m.encode_name(record, f"Set {n:02d}", rec.MIX_NAME_BIT_OFFSET)
            raw += m.mix_dump(n, record)
        raw += m.global_dump(bytes(rec.GLOBAL_BYTES))
        path = tmp_path / "all.syx"
        path.write_bytes(bytes(raw))
        source = importing.read_import(str(path))
        assert len(source.banks) == 1
        bank = source.banks[0]
        assert len(bank.programs) == 128
        assert len(bank.mixes) == 100
        assert bank.globals_ is not None
        assert source.summary().count(".") == 1


class TestMultiBankSqs:
    def test_identical_slots_stay_distinct(self, tmp_path):
        first = _program(0, "BankZero")
        second = _program(0, "BankOne")
        path = tmp_path / "two.sqs"
        path.write_bytes(_container(first, second))
        source = importing.read_import(str(path))
        assert source.kind == "sqs"
        assert len(source.banks) == 2
        assert source.banks[0].programs[0].name == "BankZero"
        assert source.banks[1].programs[0].name == "BankOne"
        assert source.banks[0].label == "bank 0"
        assert source.banks[1].label == "bank 1"


class TestMixOnlyBank:
    def test_mix_only_is_usable(self, tmp_path):
        path = tmp_path / "mix.syx"
        path.write_bytes(_mix(3, "MyMix"))
        source = importing.read_import(str(path))
        bank = source.banks[0]
        assert bank.programs == {}
        assert len(bank.mixes) == 1
        assert bank.mixes[3] is not None


class TestForeignOnly:
    def test_foreign_only_refuses(self, tmp_path):
        foreign = bytes([0xF0, 0x41, 0x10, 0x42, 0xF7])
        path = tmp_path / "foreign.sqs"
        path.write_bytes(_container(foreign))
        with pytest.raises(m.ProtocolError):
            importing.read_import(str(path))


class TestTruncatedMessage:
    def test_truncated_tail_dropped(self, tmp_path):
        path = tmp_path / "trunc.syx"
        path.write_bytes(_program(0, "Kept") + bytes([0xF0, 0x00, 0x00]))
        source = importing.read_import(str(path))
        assert len(source.banks[0].programs) == 1

    def test_only_truncated_refuses(self, tmp_path):
        path = tmp_path / "onlytrunc.syx"
        path.write_bytes(bytes([0xF0, 0x00, 0x00]))
        with pytest.raises(m.ProtocolError):
            importing.read_import(str(path))


class TestUnreadableName:
    def test_question_mark_on_protocol_error(self, tmp_path, monkeypatch):
        path = tmp_path / "badname.syx"
        path.write_bytes(_program(0, "Invented0"))

        def boom(_record):
            raise m.ProtocolError("bad")

        monkeypatch.setattr(rec, "program_name", boom)
        source = importing.read_import(str(path))
        assert source.banks[0].programs[0].name == "?"


class TestSummaryPunctuation:
    def test_one_sentence_one_period(self, tmp_path):
        path = tmp_path / "one.syx"
        path.write_bytes(_program(0, "Invented0"))
        source = importing.read_import(str(path))
        s = source.summary()
        assert s.endswith(".")
        assert s.count(".") == 1


class TestDuplicates:
    def test_duplicate_slot_recorded(self, tmp_path):
        path = tmp_path / "dup.syx"
        path.write_bytes(_program(0, "First") + _program(0, "Second"))
        source = importing.read_import(str(path))
        bank = source.banks[0]
        assert bank.duplicates == [0]
        assert bank.programs[0].name == "Second"


def _owner_fixture(env: str, fallback: str) -> str:
    """A file from the maintainer's collection, or a skip on a clean runner."""
    path = os.environ.get(env, fallback)
    if not os.path.isfile(path):
        pytest.skip(f"{env} fixture not present at {path}")
    return path


class TestFactory:
    def test_factory_five_banks(self):
        path = _owner_fixture(
            "NANOSYNED_FACTORY_SQS",
            "/home/lentferj/Dokumente/SYNTHS/Nanosynth/Nanosynth_Factory_User.sqs",
        )
        source = importing.read_import(path)
        assert source.kind == "sqs"
        assert len(source.banks) == 5
        banks_with_programs = [b for b in source.banks if b.programs]
        assert len(banks_with_programs) == 1
        assert banks_with_programs[0].index == 2

    def test_qesence_one_bank_128(self):
        path = _owner_fixture(
            "NANOSYNED_QESENCE_SYX",
            "/home/lentferj/Dokumente/SYNTHS/Nanosynth/qesence1.syx",
        )
        source = importing.read_import(path)
        assert source.kind == "syx"
        assert len(source.banks) == 1
        assert len(source.banks[0].programs) == 128
