# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""The browser's import flow: pick, source bank, whole bank or single.

The flow is the part of the plan drawn as a straight line in
``docs/IMPORT_PLAN.md``: the picker's answer becomes a source, the source's
banks become the questions, and the user's answer becomes a plan. Nothing
here sends, stores or opens a port -- the flow is a state machine over
dismissals, and the write fence lives behind the seams the follow-up task
cards own.

While the write gate is locked the flow still runs to its questions: the
picker and the choices are reads, so nothing refuses them, and the screens
the follow-ups push show the gate state and ask it again before they take
a plan apart. A locked gate therefore costs a cancelled import its
questions no more than an armed one does.

The questions, in order:

1. the picker chose a file; :func:`run_import_flow` reads it;
2. more than one bank with programs -- the source bank is asked;
3. whole bank or single / multiple programs;
4. the screen that turns the answer into a plan (T10 / T11).

Cancel at any question ends the flow before a later one is asked, so no
plan is built and the bank is left untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nano import importing, importplan
from nano import messages as m
from nanosyned.picker import FilePickerScreen
from nanosyned.screens import ReportScreen
from vinsynlib.ui.modals import ChoiceScreen

__all__ = [
    "APPEND",
    "IMPORT_MODES",
    "SINGLE",
    "WHOLE_BANK",
    "run_import_flow",
    "source_bank_choices",
    "source_banks",
    "whole_bank_plan",
]

#: The import screen's choices, as ``(answer, label)`` pairs in screen
#: order: whole bank first, then the mapping.
WHOLE_BANK = "whole"
APPEND = "append"
SINGLE = "single"
IMPORT_MODES: tuple[tuple[str, str], ...] = (
    (WHOLE_BANK, "Whole bank"),
    (APPEND, "Append to free slots"),
    (SINGLE, "Single / multiple programs"),
)

_BANK_TITLE = "Source bank"
_IMPORT_TITLE = "Import"


def source_banks(source: importing.ImportSource) -> list[importing.SourceBank]:
    """The banks that hold at least one program, in file order."""
    return [bank for bank in source.banks if bank.programs]


def source_bank_choices(source: importing.ImportSource) -> list[str]:
    """One source-bank choice per bank that holds programs."""
    return [
        f"bank {bank.index} — {len(bank.programs)} program(s)"
        for bank in source_banks(source)
    ]


def whole_bank_plan(bank: importing.SourceBank) -> importplan.ImportPlan:
    """The whole-bank plan for ``bank``: each program to its own User slot.

    Source slot 127 is skipped -- hardwired silent -- and the skip is
    named in the plan, so the screen shows it before anything is sent.
    """
    return importplan.plan_bank(bank)


def run_import_flow(
    app: Any,
    path: str,
    *,
    open_whole_bank: Callable[[importplan.ImportPlan], None] | None = None,
    open_append: Callable[[importing.SourceBank], None] | None = None,
    open_single: Callable[[importing.SourceBank], None] | None = None,
) -> None:
    """Run the flow off one chosen file path.

    The picker is the first screen; its answer is the file to read, its
    cancel is the end of the flow. The two seams are the screens the
    follow-up task cards own: the whole-bank screen receives the plan
    built for it, the mapping screen the source bank to map. Until those
    land the app passes stubs, and the flow still owns the questions that
    precede them.
    """

    def on_picked(chosen: str | None) -> None:
        if chosen is None:
            return
        _ask_after_read(app, chosen, open_whole_bank, open_append, open_single)

    app.push_screen(FilePickerScreen(path=path), on_picked)


def _ask_after_read(
    app: Any,
    path: str,
    open_whole_bank: Callable[[importplan.ImportPlan], None] | None,
    open_append: Callable[[importing.SourceBank], None] | None,
    open_single: Callable[[importing.SourceBank], None] | None,
) -> None:
    """Read the chosen file, then ask the next question it needs."""
    try:
        source = importing.read_import(path)
    except (OSError, m.ProtocolError) as exc:
        _report(app, f"could not read {path}: {exc}")
        return
    banks = source_banks(source)
    if len(banks) > 1:
        choices = source_bank_choices(source)

        def answered(index: int | None) -> None:
            if index is None:
                return
            _ask_mode(app, banks[index], open_whole_bank, open_append, open_single)

        app.push_screen(ChoiceScreen(_BANK_TITLE, choices), answered)
        return
    if not banks:
        _report(app, f"{path} holds no programs to import")
        return
    _ask_mode(app, banks[0], open_whole_bank, open_append, open_single)


def _ask_mode(
    app: Any,
    bank: importing.SourceBank,
    open_whole_bank: Callable[[importplan.ImportPlan], None] | None,
    open_append: Callable[[importing.SourceBank], None] | None,
    open_single: Callable[[importing.SourceBank], None] | None,
) -> None:
    """Ask which kind of import this is, then hand the answer onward."""

    def answered(choice: int | None) -> None:
        if choice is None:
            return
        kind = IMPORT_MODES[choice][0]
        if kind == WHOLE_BANK:
            if open_whole_bank is None:
                return
            open_whole_bank(whole_bank_plan(bank))
            return
        if kind == APPEND:
            if open_append is not None:
                open_append(bank)
            return
        if open_single is not None:
            open_single(bank)

    app.push_screen(
        ChoiceScreen(_IMPORT_TITLE, [label for _, label in IMPORT_MODES], current=0),
        answered,
    )


def _report(app: Any, sentence: str) -> None:
    """Show a read-only report screen; the flow ends here until a write."""
    app.push_screen(ReportScreen(_IMPORT_TITLE, sentence), lambda answer: None)
