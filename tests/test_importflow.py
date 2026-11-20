# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""The import flow: pick, source bank, whole bank or single, plan.

Every fixture is invented; no MIDI port is opened and nothing is written.
The flow's write seams are the screens the follow-up task cards own, so a
test can watch the plan a whole bank becomes without a device behind it.
"""

from __future__ import annotations

from nano import catalog as cat
from nano import importing
from nano import messages as m
from nano import records as rec
from nanosyned import importflow
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.screens import ReportScreen
from vinsynlib.ui.modals import ChoiceScreen

_BANK_TITLE = "Source bank"
_IMPORT_TITLE = "Import"


def make(tmp_path) -> NanosynedApp:
    """An offline app whose config path is a temporary file."""
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
    )


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


def _run(app, path: str, whole: list, single: list) -> None:
    """Run the flow under test against ``app``; watch the write seams."""

    def on_whole(plan) -> None:
        whole.append(plan)

    def on_single(bank) -> None:
        single.append(bank)

    importflow.run_import_flow(
        app,
        path,
        open_whole_bank=on_whole,
        open_single=on_single,
    )


async def _until(pilot, ready, attempts: int = 100) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


def _choice_title(screen) -> str:
    return getattr(screen, "_title", "") or ""


def _waiting_on_picker(app) -> bool:
    return len(app.screen.query("#picker-table")) == 1


def _source_program(index: int, slot: int, name: str) -> importing.SourceProgram:
    return importing.SourceProgram(
        index=index, slot=slot, name=name, record=bytes(rec.PROGRAM_BYTES)
    )


def _source_bank(index: int, *slots: int) -> importing.SourceBank:
    bank = importing.SourceBank(index=index, label=f"bank {index}")
    for position, slot in enumerate(slots):
        bank.programs[slot] = _source_program(position, slot, f"Invented{slot}")
    return bank


def _source(*banks: importing.SourceBank) -> importing.ImportSource:
    return importing.ImportSource(path="fixture.sqs", kind="sqs", banks=list(banks))


class TestTheSourceQuestions:
    """The bank question and the plan it leads to, without a pilot."""

    def test_only_banks_with_programs_are_offered(self) -> None:
        bank = _source_bank(0, 0)
        empty = importing.SourceBank(index=1, label="bank 1")
        source = _source(bank, empty)
        assert importflow.source_banks(source) == [bank]
        assert importflow.source_bank_choices(source) == ["bank 0 — 1 program(s)"]

    def test_every_program_bank_gets_a_choice(self) -> None:
        source = _source(_source_bank(0, 0, 2), _source_bank(1, 5))
        assert importflow.source_bank_choices(source) == [
            "bank 0 — 2 program(s)",
            "bank 1 — 1 program(s)",
        ]

    def test_the_whole_bank_plan_skips_the_hardwired_source(self) -> None:
        bank = _source_bank(0, 3, 127, 4)
        plan = importflow.whole_bank_plan(bank)
        assert [step.target for step in plan.steps] == [3, 4]
        assert plan.skipped == ("source 127 is hardwired silent",)


class TestTheImportFlow:
    """The flow's screens, one question at a time."""

    async def test_a_single_bank_flows_to_the_whole_bank_plan(self, tmp_path):
        (tmp_path / "one.syx").write_bytes(_program(3, "Invented3"))
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            assert _choice_title(app.screen) == _IMPORT_TITLE
            await pilot.press("enter")
            await _until(pilot, lambda: len(whole) == 1)
        plan = whole[0]
        assert [step.target for step in plan.steps] == [3]
        assert plan.steps[0].source_label == "one.syx program 003"
        assert plan.skipped == ()

    async def test_two_program_banks_ask_the_source_bank(self, tmp_path):
        (tmp_path / "two.sqs").write_bytes(
            _container(_program(0, "BankZero"), _program(0, "BankOne"))
        )
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            screen = app.screen
            assert _choice_title(screen) == _BANK_TITLE
            assert screen._choices == [
                "bank 0 — 1 program(s)",
                "bank 1 — 1 program(s)",
            ]
            await pilot.press("down")
            await pilot.press("enter")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ChoiceScreen)
                    and _choice_title(app.screen) == _IMPORT_TITLE
                ),
            )
            await pilot.press("enter")
            await _until(pilot, lambda: len(whole) == 1)
        plan = whole[0]
        assert [step.source_label for step in plan.steps] == ["bank 1 program 000"]

    async def test_the_whole_bank_plan_skips_the_hardwired_source(self, tmp_path):
        (tmp_path / "skip.syx").write_bytes(
            _program(127, "Hardwired") + _program(3, "Invented3")
        )
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: len(whole) == 1)
        plan = whole[0]
        assert [step.target for step in plan.steps] == [3]
        assert plan.skipped == ("source 127 is hardwired silent",)

    async def test_the_single_mode_screen_gets_the_bank(self, tmp_path):
        (tmp_path / "one.sqs").write_bytes(_program(0, "Invented0"))
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await _until(pilot, lambda: len(single) == 1)
        assert len(single) == 1
        assert isinstance(single[0].programs[0], importing.SourceProgram)

    async def test_a_file_that_reads_nothing_is_a_report(self, tmp_path):
        (tmp_path / "junk.syx").write_bytes(b"not a dump at all")
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: not isinstance(app.screen, ReportScreen))
        assert whole == []
        assert single == []

    async def test_cancel_at_the_source_bank_question_writes_nothing(self, tmp_path):
        (tmp_path / "two.sqs").write_bytes(
            _container(_program(0, "BankZero"), _program(0, "BankOne"))
        )
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, ChoiceScreen))
        assert whole == []
        assert single == []

    async def test_cancel_at_the_import_question_writes_nothing(self, tmp_path):
        (tmp_path / "one.syx").write_bytes(_program(0, "Invented0"))
        app = make(tmp_path)
        whole: list = []
        single: list = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            _run(app, str(tmp_path), whole, single)
            await _until(pilot, lambda: _waiting_on_picker(app))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, ChoiceScreen))
        assert whole == []
        assert single == []
