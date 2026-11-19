# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The escaping of unit-supplied text is ported from the sibling emorphed
# and rxved projects, which fix the same bug, and which carry the same
# licence:
#   Copyright (C) 2026  emorphed / rxved contributors
#                                     - GPL-2.0-or-later
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The import screens: the picker, and the whole-bank preview.

No hardware, no parse, no device: the picker only lists folders and the
whole-bank screen only shows a plan somebody else built, so every fixture
here is invented and lives in a temporary directory. The app is the demo,
and its config path is injected, so the remembered folder is a temporary
file rather than somebody's.
"""

from __future__ import annotations

import os

import pytest
from textual.widgets import DataTable, Static

from nano import catalog as cat
from nano import config, importing, importplan
from nano import messages as m
from nano import records as rec
from nanosyned import importflow
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditGate
from nanosyned.importbank import WholeBankScreen
from nanosyned.importsingle import SingleMappingScreen
from nanosyned.picker import FilePickerScreen
from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.modals import ChoiceScreen


def make(tmp_path) -> NanosynedApp:
    """An offline app whose config path is a temporary file."""
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
    )


async def _until(pilot, ready, attempts: int = 100) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open(pilot, screen, seen) -> None:
    """Push a picker over the running app and wait for it to mount."""
    app = pilot.app
    app.push_screen(screen, seen.append)
    await _until(pilot, lambda: isinstance(app.screen, FilePickerScreen))
    await _until(pilot, lambda: len(app.screen.query("#picker-table")) == 1)


class TestTheFilePicker:
    """The picker's own keys, with no import behind them yet."""

    async def test_lists_the_folder_and_its_import_files(self, tmp_path):
        (tmp_path / "programs").mkdir()
        (tmp_path / "qesence1.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2
            assert str(table.get_row_at(0)[0]) == "programs/"
            assert str(table.get_row_at(1)[0]) == "qesence1.syx"

    async def test_the_filter_narrows_the_listing(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        (tmp_path / "qesence2.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2
            await pilot.press("slash")
            await pilot.press("q", "e", "s", "e", "n", "c", "e", "1")
            await pilot.pause()
            assert table.row_count == 1
            assert str(table.get_row_at(0)[0]) == "qesence1.syx"

    async def test_enter_enters_a_directory(self, tmp_path):
        (tmp_path / "programs").mkdir()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            await pilot.press("enter")
            await pilot.pause()
            assert screen.folder == str(tmp_path / "programs")
            assert screen._rows == []

    async def test_enter_on_a_file_returns_its_path(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        seen: list[str | None] = []
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            await pilot.press("enter")
            await _until(pilot, lambda: bool(seen))
            assert seen == [str(tmp_path / "qesence1.syx")]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))

    async def test_the_folder_is_remembered_across_two_mounts(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        config.save_ui_state(
            "import.folder", str(tmp_path), str(tmp_path / "config.toml")
        )
        seen: list[str | None] = []
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            first = app.screen
            assert first.folder == str(tmp_path)
            await pilot.press("enter")
            await _until(pilot, lambda: bool(seen))
            assert seen == [str(tmp_path / "qesence1.syx")]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))
        assert config.load_ui_str(
            "import.folder", str(tmp_path / "config.toml")
        ) == str(tmp_path)

        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            assert app.screen.folder == str(tmp_path)

    async def test_a_remembered_folder_that_is_gone_falls_back_to_home(self, tmp_path):
        config.save_ui_state(
            "import.folder", str(tmp_path / "absent"), str(tmp_path / "config.toml")
        )
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            screen = app.screen
            assert screen.folder == os.path.expanduser("~")
            status = screen.query_one("#picker-status", Static)
            assert "gone or unreadable" in str(status.content)

    async def test_a_long_or_bracketed_name_does_not_crash_the_markup(
        self, tmp_path
    ) -> None:
        long_name = "q" * 200 + "[bracketed].syx"
        (tmp_path / long_name).touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            assert str(screen.query_one("#picker-status", Static).content)

    @pytest.mark.parametrize("key", ["escape", "q"])
    async def test_escape_and_q_return_none(self, tmp_path, key):
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))


class TestLetterNavigation:
    """Letter keys jump to the first matching entry when not filtering."""

    async def test_letter_jumps_to_first_matching_entry(self, tmp_path):
        (tmp_path / "alpha.syx").touch()
        (tmp_path / "beta.syx").touch()
        (tmp_path / "gamma.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 3

            # Press 'g' - should jump to gamma.syx
            await pilot.press("g")
            await pilot.pause()
            assert table.cursor_row == 2  # gamma is 3rd (index 2)

            # Press 'a' - should jump to alpha.syx
            await pilot.press("a")
            await pilot.pause()
            assert table.cursor_row == 0  # alpha is 1st

    async def test_letter_case_insensitive(self, tmp_path):
        (tmp_path / "Alpha.syx").touch()
        (tmp_path / "beta.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            table = app.screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2

            # Uppercase 'A' should still find alpha (case insensitive)
            await pilot.press("A")
            await pilot.pause()
            assert table.cursor_row == 0  # Alpha is 1st

    async def test_letter_does_nothing_when_filtering(self, tmp_path):
        (tmp_path / "alpha.syx").touch()
        (tmp_path / "bongo.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            table = app.screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2

            # Start filtering with '/'
            await pilot.press("slash")
            await pilot.pause()
            # Now 'a' should be part of filter, not jump
            await pilot.press("a")
            await pilot.pause()
            # Filter narrows to entries containing 'a': alpha only
            assert table.row_count == 1
            assert str(table.get_row_at(0)[0]) == "alpha.syx"

    async def test_q_cancels_not_jumps(self, tmp_path):
        (tmp_path / "qtest.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            table = app.screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1

            # Press 'q' - should cancel, not jump to qtest.syx
            await pilot.press("q")
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]


# --- the whole-bank screen -------------------------------------------------


def _record(name: str) -> bytes:
    """A 350-byte program whose name field says ``name``."""
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    return bytes(record)


def _program(number: int, name: str) -> bytes:
    """One program dump, as a file carries it."""
    return m.program_dump(number, _record(name))


def _bank(*items: tuple[int, str]) -> importing.SourceBank:
    """A source bank holding ``(slot, name)`` in the order given."""
    bank = importing.SourceBank(index=0, label="bank 0")
    for index, (slot, name) in enumerate(items):
        bank.programs[slot] = importing.SourceProgram(
            index=index, slot=slot, name=name, record=_record(name)
        )
    return bank


def _catalog(*items: tuple[int, str]) -> cat.Catalog:
    """A catalog with names for the named User slots."""
    return cat.Catalog([cat.Entry("USER", number, name) for number, name in items])


async def _open_bank(pilot, screen, seen) -> None:
    """Push a whole-bank screen over the running app and wait for its table."""
    app = pilot.app
    app.push_screen(screen, seen.append)
    await _until(pilot, lambda: isinstance(app.screen, WholeBankScreen))
    await _until(pilot, lambda: len(app.screen.query("#bank-table")) == 1)


def _waiting_on_confirm(app) -> bool:
    return isinstance(app.screen, ConfirmScreen)


def _waiting_on_picker(app) -> bool:
    return len(app.screen.query("#picker-table")) == 1


class TestTheWholeBankScreen:
    """The whole-bank table, its gate, and the two questions."""

    async def test_the_label_and_the_gate_are_shown_at_the_top(self, tmp_path):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        gate = EditGate()
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=gate)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            assert screen.bank_label == "bank 0"
            assert "bank 0" in str(screen.query_one("#bank-source").content)
            gate_line = screen.query_one("#bank-gate", Static)
            assert "Write gate: locked" in str(gate_line.content)

    async def test_the_hardwired_source_is_a_skipped_row(self, tmp_path):
        bank = _bank((127, "Hardwired"), (3, "Invented3"))
        plan = importplan.plan_bank(bank)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=EditGate())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            table = screen.query_one("#bank-table", DataTable)
            assert table.row_count == 2
            skipped = [str(cell) for cell in table.get_row_at(0)]
            assert skipped[1] == "Hardwired"
            assert skipped[2] == "---"
            assert skipped[3] == "skipped: hardwired silent"
            kept = [str(cell) for cell in table.get_row_at(1)]
            assert kept[2] == "[b]003[/b]"

    async def test_a_used_destination_is_named_in_the_state_column(self, tmp_path):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(
            plan, bank=bank, gate=EditGate(), catalog=_catalog((3, "Old Name"))
        )
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            table = screen.query_one("#bank-table", DataTable)
            assert str(table.get_row_at(0)[3]) == "used: Old Name"

    async def test_a_locked_gate_refuses_and_keeps_the_screen(self, tmp_path):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=EditGate())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, WholeBankScreen)
            assert not _waiting_on_confirm(app)
            status = screen.query_one("#bank-status", Static)
            assert "write gate is locked" in str(status.content)
            assert seen == []

    async def test_two_confirmations_answer_the_plan(self, tmp_path):
        bank = _bank((3, "Invented3"), (4, "Invented4"))
        plan = importplan.plan_bank(bank)
        gate = EditGate(armed=True)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(
            plan, bank=bank, gate=gate, catalog=_catalog((3, "Old Name"))
        )
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            assert "import 2 programs into the User bank?" in app.screen.prompt_text
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    _waiting_on_confirm(app) and "Old Name" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(pilot, lambda: bool(seen))
            assert seen == [plan]
            assert len(seen[0].steps) == 2
            await _until(pilot, lambda: not isinstance(app.screen, WholeBankScreen))

    @pytest.mark.parametrize("answer", ["n", "escape"])
    async def test_cancel_at_the_first_confirm_writes_nothing(self, tmp_path, answer):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            await pilot.press(answer)
            await _until(pilot, lambda: isinstance(app.screen, WholeBankScreen))
            assert seen == []
            assert "nothing imported" in str(
                screen.query_one("#bank-status", Static).content
            )

    @pytest.mark.parametrize("answer", ["n", "escape"])
    async def test_cancel_at_the_second_confirm_writes_nothing(self, tmp_path, answer):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    _waiting_on_confirm(app)
                    and "these User slots will be overwritten" in app.screen.prompt_text
                ),
            )
            await pilot.press(answer)
            await _until(pilot, lambda: isinstance(app.screen, WholeBankScreen))
            assert seen == []
            assert "nothing imported" in str(
                screen.query_one("#bank-status", Static).content
            )

    async def test_a_gate_locked_between_the_confirms_refuses(self, tmp_path):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        gate = EditGate(armed=True)
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=gate)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    _waiting_on_confirm(app)
                    and "these User slots will be overwritten" in app.screen.prompt_text
                ),
            )
            # The app's `w` can be pressed while a modal is up; this is the
            # same object the screen holds, not a copy of its state.
            gate.toggle()
            await pilot.press("y")
            await _until(pilot, lambda: isinstance(app.screen, WholeBankScreen))
            assert seen == []
            assert "write gate is locked" in str(
                screen.query_one("#bank-status", Static).content
            )

    async def test_w_arms_the_gate_in_place(self, tmp_path):
        bank = _bank((3, "Invented3"))
        plan = importplan.plan_bank(bank)
        gate = EditGate()
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=gate)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            await pilot.press("w")
            await pilot.pause()
            assert gate.armed
            assert "Write gate: ARMED" in str(
                screen.query_one("#bank-gate", Static).content
            )

    async def test_the_part_rows_are_part_of_the_preview(self, tmp_path):
        bank = _bank((3, "Invented3"))
        bank.effects[0] = bytes(rec.EFFECTS_BYTES)
        programs = importplan.plan_bank(bank)
        effects = importplan.plan_all_effects(bank)
        plan = importplan.ImportPlan(
            steps=programs.steps + effects.steps,
            skipped=programs.skipped,
            overwrites=programs.overwrites + effects.overwrites,
        )
        app = make(tmp_path)
        seen: list = []
        screen = WholeBankScreen(plan, bank=bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_bank(pilot, screen, seen)
            table = screen.query_one("#bank-table", DataTable)
            assert table.row_count == 2
            assert "1 other record(s)" in str(
                screen.query_one("#bank-plan", Static).content
            )
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            assert "and 1 other record(s)" in app.screen.prompt_text


class TestTheWholeBankInTheFlow:
    """Pick, choose whole bank, confirm twice: the plan comes back."""

    async def test_the_flow_reaches_the_plan_through_the_screen(self, tmp_path):
        (tmp_path / "one.syx").write_bytes(
            _program(127, "Hardwired") + _program(3, "Invented3")
        )
        app = make(tmp_path)
        gate = EditGate(armed=True)
        opened: list = []
        answers: list = []

        def open_whole(plan) -> None:
            opened.append(plan)
            app.push_screen(WholeBankScreen(plan, gate=gate), answers.append)

        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            importflow.run_import_flow(app, str(tmp_path), open_whole_bank=open_whole)
            await _until(pilot, lambda: _waiting_on_picker(app))
            picker = app.screen.query_one("#picker-table", DataTable)
            assert picker.row_count == 1
            assert str(picker.get_row_at(0)[0]) == "one.syx"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: len(opened) == 1)
            await _until(pilot, lambda: isinstance(app.screen, WholeBankScreen))
            table = app.screen.query_one("#bank-table", DataTable)
            assert table.row_count == 2
            rows = [
                [str(cell) for cell in table.get_row_at(index)]
                for index in range(table.row_count)
            ]
            skipped = [row for row in rows if row[3] == "skipped: hardwired silent"]
            assert len(skipped) == 1
            assert skipped[0][1] == "source 127"
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: _waiting_on_confirm(app))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    _waiting_on_confirm(app)
                    and "these User slots will be overwritten" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(pilot, lambda: bool(answers))
            await _until(pilot, lambda: not isinstance(app.screen, WholeBankScreen))

        assert opened == answers
        plan = answers[0]
        assert [step.target for step in plan.steps] == [3]
        assert plan.skipped == ("source 127 is hardwired silent",)


# --- the single / multiple mapping screen ---------------------------------


async def _open_single(pilot, screen, seen) -> None:
    """Push a single-mapping screen over the running app and wait for it."""
    app = pilot.app
    app.push_screen(screen, seen.append)
    await _until(pilot, lambda: isinstance(app.screen, SingleMappingScreen))
    await _until(pilot, lambda: len(app.screen.query("#single-table")) == 1)


class TestTheSingleMappingScreen:
    """The slot map, its validation, and the two questions."""

    async def test_assign_one_slot(self, tmp_path):
        bank = _bank((0, "Src0"), (1, "Src1"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.pause()
            assert screen.assignments == [(0, 0)]
            table = screen.query_one("#single-table", DataTable)
            assert str(table.get_row_at(0)[2]) == "[b]000[/b]"

    async def test_a_duplicate_target_is_refused(self, tmp_path):
        bank = _bank((0, "Src0"), (1, "Src1"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("0", "0", "5")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("0", "0", "5")
            await pilot.pause()
            status = screen.query_one("#single-status", Static)
            assert "assigned twice" in str(status.content)

    async def test_target_127_is_refused(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("1", "2", "7")
            await pilot.pause()
            status = screen.query_one("#single-status", Static)
            assert "hardwired silent" in str(status.content)

    async def test_an_out_of_range_target_is_refused(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("1", "2", "8")
            await pilot.pause()
            status = screen.query_one("#single-status", Static)
            assert "outside 0-126" in str(status.content)

    async def test_auto_assign_skips_used_slots(self, tmp_path):
        bank = _bank((0, "Src0"), (1, "Src1"))
        catalog = _catalog((0, "Old0"), (1, "Old1"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True), catalog=catalog)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("A")
            await pilot.pause()
            targets = [target for _, target in screen.assignments]
            assert 0 not in targets
            assert 1 not in targets

    async def test_unassign(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.pause()
            assert screen.assignments == [(0, 0)]
            await pilot.press("u")
            await pilot.pause()
            assert screen.assignments == []

    async def test_clear(self, tmp_path):
        bank = _bank((0, "Src0"), (1, "Src1"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("space")
            await pilot.pause()
            assert len(screen.assignments) == 2
            await pilot.press("U")
            await pilot.pause()
            assert screen.assignments == []

    async def test_gate_kept(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=False))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, SingleMappingScreen)
            assert seen == []
            status = screen.query_one("#single-status", Static)
            assert "write gate is locked" in str(status.content)

    async def test_cancel_typed_target_then_screen(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("1")
            await pilot.pause()
            assert screen._slot_entry == "1"
            await pilot.press("escape")
            await pilot.pause()
            assert screen._slot_entry == ""
            assert isinstance(app.screen, SingleMappingScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert seen == [None]

    async def test_two_confirmations_answer_the_assignments(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            assert "import 1 programs into the User bank?" in app.screen.prompt_text
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "these User slots will be overwritten" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(pilot, lambda: bool(seen))
            assert seen == [[(0, 0)]]
            await _until(pilot, lambda: not isinstance(app.screen, SingleMappingScreen))

    async def test_a_gate_locked_between_the_confirms_refuses(self, tmp_path):
        bank = _bank((0, "Src0"))
        gate = EditGate(armed=True)
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=gate)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "these User slots will be overwritten" in app.screen.prompt_text
                ),
            )
            gate.toggle()
            await pilot.press("y")
            await _until(pilot, lambda: isinstance(app.screen, SingleMappingScreen))
            assert seen == []
            status = screen.query_one("#single-status", Static)
            assert "write gate is locked" in str(status.content)

    async def test_non_printing_digits_do_not_crash(self, tmp_path):
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        seen: list = []
        screen = SingleMappingScreen(bank, gate=EditGate(armed=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open_single(pilot, screen, seen)
            # Press a non-digit printable and an arrow while not typing.
            await pilot.press("a")
            await pilot.press("down")
            await pilot.pause()
            assert screen._slot_entry == ""
            await pilot.press("escape")
            await pilot.pause()
            assert seen == [None]

    async def test_l_loads_into_the_edit_buffer_without_storing(self, tmp_path):
        """`l` previews: it loads (opcode 02) into the edit buffer, stores nothing."""
        bank = _bank((0, "Src0"))
        app = make(tmp_path)
        previews: list = []
        screen = SingleMappingScreen(
            bank, gate=EditGate(armed=True), on_preview=previews.append
        )
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            seen: list = []
            app.push_screen(screen, seen.append)
            await _until(pilot, lambda: isinstance(app.screen, SingleMappingScreen))
            await _until(pilot, lambda: len(app.screen.query("#single-table")) == 1)
            await pilot.press("down")  # ensure a row is focused
            await pilot.press("l")
            await pilot.pause()
            assert len(previews) == 1
            assert previews[0] == bank.programs[0].record
            # The app's own preview loads and never stores.
            app._preview_import(previews[0])
            await pilot.pause()
            assert len(app.device.edit_program_writes) == 1
            assert (
                app.device.edit_program_writes[0]
                == bytes(bank.programs[0].record)[: rec.PROGRAM_BYTES]
            )
            assert app.device.program_writes == []
