# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""Selection and plan: what an import will write, decided before a port opens.

**The plan is pure.** :func:`plan_bank` and :func:`plan_single` take a source
bank that somebody else read from disk, validate the selection, and return
steps. They open no file, open no port, read no catalog and print nothing.
That is what makes the dangerous part reviewable: the CLI and the TUI agree
on the plan first, and :mod:`nano.writing` is the only code that stores it.

The planner refuses the selections a store may not make:

* a destination named twice, because the second store would silently win;
* destination 127, which is hardwired silent on this unit;
* a destination outside ``000``-``126``, the only User slots that exist;
* a source slot the bank does not hold;
* a record that is shorter than the kind it claims to be;
* an empty selection.

Whole-bank import is the one place a hardwired slot is not an error: source
127 is skipped with a sentence, because a factory bank or a complete dump
legitimately carries it. Whole-mix import does the same for mix 100, the edit
buffer. Naming either as a *destination* is still refused.

``ImportPlan.overwrites`` is a tuple of human sentences, not a name lookup.
The planner cannot know what a destination holds; the caller reads the
destination first, then names the old and new program in the confirmation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from nano import records as rec
from nano.importing import SourceBank, SourceProgram

__all__ = [
    "EDIT_MIX",
    "SILENT_PROGRAM",
    "USER_PROGRAM_SLOTS",
    "Assignment",
    "ImportPlan",
    "Step",
    "plan_all_effects",
    "plan_all_global",
    "plan_all_mixes",
    "plan_bank",
    "plan_single",
]

#: User programs 000-126 may be written. 127 is hardwired silent and is
#: shown in a bank import only to be skipped.
USER_PROGRAM_SLOTS = (0, 126)

#: The hardwired silent program. A source dump of it is skipped; it is never
#: a legal destination.
SILENT_PROGRAM = 127

#: The mix edit buffer: loadable, never storable. A bank that carries it
#: skips it rather than refusing the whole file.
EDIT_MIX = 100

#: The unpacked size of each record kind, from the one place that defines
#: them. A planner step carries exactly this many bytes.
_RECORD_BYTES = {
    "program": rec.PROGRAM_BYTES,
    "effects": rec.EFFECTS_BYTES,
    "mix": rec.MIX_BYTES,
    "global": rec.GLOBAL_BYTES,
}

#: What a person calls each kind, for a refusal that has to name one.
_RECORD_WORDS = {
    "program": "user program",
    "effects": "effects patch",
    "mix": "mix",
    "global": "global settings",
}

#: The destination range each numbered kind has. Global has no number.
_NUMBER_RANGES = {
    "program": USER_PROGRAM_SLOTS,
    "effects": (0, 127),
    "mix": (0, 99),
}


@dataclass(frozen=True)
class Assignment:
    """One source program and the User slot it will be written to."""

    source: SourceProgram
    target: int


@dataclass(frozen=True)
class Step:
    """One record to store.

    ``old_name`` is deliberately :data:`None` here and filled by the reader
    that knows the destination, not by the planner. ``source_label`` names
    where the record came from, for progress and for the plan display.
    """

    kind: str
    target: int | None
    record: bytes
    old_name: str | None
    source_label: str


@dataclass(frozen=True)
class ImportPlan:
    """What an import will write, and what it refuses to touch.

    ``skipped`` names records the source carries but the plan leaves alone,
    such as source 127 or mix 100. ``overwrites`` is one sentence per step
    for the confirmation; the old names are filled in after the destination
    read, because only the unit knows them.
    """

    steps: tuple[Step, ...]
    skipped: tuple[str, ...]
    overwrites: tuple[str, ...]


def _check_target(kind: str, target: int) -> None:
    """Refuse a destination the unit cannot store, before any port opens."""
    if kind == "program" and target == SILENT_PROGRAM:
        raise ValueError(
            "user program 127 is hardwired silent and cannot be changed; nothing sent"
        )
    low, high = _NUMBER_RANGES[kind]
    if not low <= target <= high:
        raise ValueError(
            f"{_RECORD_WORDS[kind]} {target} is outside {low}-{high}; nothing sent"
        )


def _sized(kind: str, record: bytes, what: str) -> bytes:
    """A record at its documented size, or :class:`ValueError`.

    A dump is padded to a whole packing group, so the tail is dropped. A
    *short* record is refused: a step that carries fewer bytes than the kind
    occupies would put whatever follows it into the slot.
    """
    size = _RECORD_BYTES[kind]
    try:
        rec.check_size(record, size, what)
    except ValueError as exc:
        raise ValueError(f"{exc}; nothing sent") from None
    return bytes(record[:size])


def _step(
    kind: str,
    target: int | None,
    record: bytes,
    source_label: str,
    what: str,
) -> Step:
    """One validated step; ``old_name`` is the destination reader's to fill."""
    return Step(
        kind=kind,
        target=target,
        record=_sized(kind, record, what),
        old_name=None,
        source_label=source_label,
    )


def _overwrite(kind: str, target: int | None) -> str:
    """One sentence for the confirmation, without guessing the old name."""
    if kind == "global":
        return "the global settings will be overwritten"
    return f"{_RECORD_WORDS[kind]} {target:03d} will be overwritten"


def _assemble(steps: list[Step], skipped: list[str]) -> ImportPlan:
    """Freeze steps and their confirmation sentences into a plan."""
    return ImportPlan(
        steps=tuple(steps),
        skipped=tuple(skipped),
        overwrites=tuple(_overwrite(step.kind, step.target) for step in steps),
    )


def _program_label(bank: SourceBank, program: SourceProgram) -> str:
    """Where a program came from, in words a progress line can show."""
    return f"{bank.label} program {program.slot:03d}"


def plan_bank(bank: SourceBank) -> ImportPlan:
    """Every program in ``bank`` to its own User slot, skipping source 127.

    The order is source order: the flat ``index`` the reader assigned, not
    the slot number and not the dictionary's insertion order. A bank that
    holds only the hardwired program yields a plan with no steps and one
    sentence; refusing an empty plan is the caller's job, because the
    sentence is exactly what the screen has to show.
    """
    steps: list[Step] = []
    skipped: list[str] = []
    for program in sorted(bank.programs.values(), key=lambda item: item.index):
        if program.slot == SILENT_PROGRAM:
            skipped.append(f"source {SILENT_PROGRAM} is hardwired silent")
            continue
        _check_target("program", program.slot)
        steps.append(
            _step(
                "program",
                program.slot,
                program.record,
                _program_label(bank, program),
                f"source program {program.slot}",
            )
        )
    return _assemble(steps, skipped)


def plan_single(bank: SourceBank, pairs: Iterable[tuple[int, int]]) -> ImportPlan:
    """Plan selected source programs, each to a chosen User slot.

    ``pairs`` is ``(source_slot, target_slot)``, repeatable and in the order
    the caller collected them. The steps come back in source order, so the
    progress line and the bank preview walk the file the same way. Slot
    numbers are validated here, not when the store is sent.
    """
    selections = tuple(pairs)
    if not selections:
        raise ValueError("nothing selected; nothing sent")
    assignments: list[Assignment] = []
    seen: set[int] = set()
    for source_slot, target in selections:
        source = bank.programs.get(source_slot)
        if source is None:
            raise ValueError(
                f"source slot {source_slot} is not in {bank.label}; nothing sent"
            )
        _check_target("program", target)
        if target in seen:
            raise ValueError(
                f"user program {target:03d} is assigned twice; nothing sent"
            )
        seen.add(target)
        assignments.append(Assignment(source=source, target=target))
    steps = [
        _step(
            "program",
            assignment.target,
            assignment.source.record,
            _program_label(bank, assignment.source),
            f"source program {assignment.source.slot}",
        )
        for assignment in sorted(assignments, key=lambda item: item.source.index)
    ]
    return _assemble(steps, [])


def plan_all_effects(bank: SourceBank) -> ImportPlan:
    """Every effects patch in ``bank``, each to its own numbered slot."""
    steps: list[Step] = []
    for number in sorted(bank.effects):
        _check_target("effects", number)
        steps.append(
            _step(
                "effects",
                number,
                bank.effects[number],
                f"{bank.label} effects {number:03d}",
                f"source effects patch {number}",
            )
        )
    return _assemble(steps, [])


def plan_all_mixes(bank: SourceBank) -> ImportPlan:
    """Every stored mix in ``bank``, skipping the edit buffer at 100."""
    steps: list[Step] = []
    skipped: list[str] = []
    for number in sorted(bank.mixes):
        if number == EDIT_MIX:
            skipped.append(f"source mix {EDIT_MIX} is the edit buffer; skipped")
            continue
        _check_target("mix", number)
        steps.append(
            _step(
                "mix",
                number,
                bank.mixes[number],
                f"{bank.label} mix {number:03d}",
                f"source mix {number}",
            )
        )
    return _assemble(steps, skipped)


def plan_all_global(bank: SourceBank) -> ImportPlan:
    """The bank's global settings, when it carries them.

    A bank without a global dump yields an empty plan rather than an error:
    the caller asked for a part the file does not have, and a note is the
    honest answer.
    """
    if bank.globals_ is None:
        return _assemble([], [])
    step = _step(
        "global",
        None,
        bank.globals_,
        f"{bank.label} global",
        "source global settings",
    )
    return _assemble([step], [])
