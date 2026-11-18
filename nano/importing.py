# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""The source model for importing programs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from nano import dumps, sqs
from nano import messages as m
from nano import records as rec


@dataclass(frozen=True)
class SourceProgram:
    index: int
    slot: int
    name: str
    record: bytes


@dataclass
class SourceBank:
    index: int
    label: str
    programs: dict[int, SourceProgram] = field(default_factory=dict)
    effects: dict[int, bytes] = field(default_factory=dict)
    mixes: dict[int, bytes] = field(default_factory=dict)
    globals_: bytes | None = None
    duplicates: list[int] = field(default_factory=list)


@dataclass
class ImportSource:
    path: str
    kind: str
    banks: list[SourceBank]

    def summary(self) -> str:
        programs = sum(len(bank.programs) for bank in self.banks)
        effects = sum(len(bank.effects) for bank in self.banks)
        mixes = sum(len(bank.mixes) for bank in self.banks)
        globals_ = sum(1 for bank in self.banks if bank.globals_ is not None)
        duplicates = sum(len(bank.duplicates) for bank in self.banks)
        return (
            f"{len(self.banks)} bank(s), {programs} program(s), {effects} effects, "
            f"{mixes} mix(es), {globals_} global, {duplicates} duplicates."
        )


def _handle_message(bank: SourceBank, packet: m.Packet, program_index: int) -> int:
    """Apply one parsed message to ``bank``.

    Returns ``1`` when a program was added (so the caller can advance its
    flat index), otherwise ``0``.
    """
    try:
        data = packet.data()
    except m.ProtocolError:
        return 0
    number = packet.number
    function = packet.function
    if number is None:
        return 0
    if function == m.Function.USER_PROGRAM_DUMP:
        if len(data) != rec.PROGRAM_BYTES:
            return 0
        try:
            name = rec.program_name(data).strip()
        except m.ProtocolError:
            name = "?"
        if number in bank.programs:
            bank.duplicates.append(number)
        bank.programs[number] = SourceProgram(
            index=program_index,
            slot=number,
            name=name,
            record=bytes(data),
        )
        return 1
    if function == m.Function.USER_EFFECTS_DUMP:
        bank.effects[number] = bytes(data)
    elif function == m.Function.MIX_DUMP:
        bank.mixes[number] = bytes(data)
    elif function == m.Function.GLOBAL_DUMP:
        bank.globals_ = bytes(data)
    return 0


def _read_bank(payload: bytes, index: int, label: str) -> SourceBank:
    bank = SourceBank(index=index, label=label)
    program_index = 0
    for message in dumps.split_messages(payload):
        packet = m.parse(message)
        if packet is None:
            continue
        delta = _handle_message(bank, packet, program_index)
        program_index += delta
    return bank


def read_import(path: str) -> ImportSource:
    with open(path, "rb") as handle:
        raw = handle.read()
    if sqs.is_sqs(raw):
        kind = "sqs"
        payloads = sqs.read_banks(raw)
        banks: list[SourceBank] = []
        for index, payload in enumerate(payloads):
            banks.append(_read_bank(payload, index, f"bank {index}"))
    else:
        kind = "syx"
        banks = [_read_bank(raw, 0, os.path.basename(path))]
    source = ImportSource(path=path, kind=kind, banks=banks)
    usable = any(
        bank.programs or bank.effects or bank.mixes or bank.globals_ is not None
        for bank in source.banks
    )
    if not usable:
        raise m.ProtocolError(f"{path}: no usable records")
    return source
