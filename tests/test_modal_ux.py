# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
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

"""Every modal opens, closes with the keys it documents, and leaves a browser.

A binding whose action method does not exist is not an error in Textual:
it is logged and the key presses on, invisibly. So each screen here is
driven with the keys its own ``BINDINGS`` promises, and every dismissal
ends with the same check -- the browser underneath still answers a key.

The screens come from three places, and all three are covered because
all three are opened over the browser:

* :mod:`nanosyned.screens` -- the report, prompt, confirmation and editor;
* :mod:`nanosyned.scan` -- the offer and the progress screen;
* the library's search form (:class:`vinsynlib.ui.modals.SearchScreen`),
  which the browser opens with ``/`` and which the task list names.

The mix screen is guarded the way the optional screens are: the last
class tests it when it is present and skips with a sentence when it is
not, rather than silently missing it.

Every device is the demo; no port is opened, and every name is invented.
"""

from __future__ import annotations

import threading

import pytest
from textual.widgets import DataTable, Input, Static

from nano import catalog as cat
from nanosyned import mix as mixview
from nanosyned import scan as scan_module
from nanosyned import screens
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditGate, ProgramEditor
from nanosyned.programpicker import ProgramPickerScreen
from nanosyned.scan import ScanOfferScreen, ScanScreen
from nanosyned.screens import (
    ConfirmScreen,
    EditorScreen,
    PromptScreen,
    ReportScreen,
)
from vinsynlib.ui.modals import ChoiceScreen, SearchScreen


def make(*, allow_write: bool = False) -> NanosynedApp:
    """An offline app whose non-empty catalog suppresses the scan offer."""
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        allow_write=allow_write,
    )


async def _until(pilot, ready, attempts: int = 100) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _still_usable(app: NanosynedApp, pilot) -> None:
    """The browser underneath answers a key after a modal has gone.

    One cursor move, which is the smallest gesture that proves the screen
    stack is back where it was; and no selection, because a dialog that
    closed must not have selected a program as a side effect.
    """
    table = app.query_one("#bank-table", DataTable)
    table.focus()
    table.move_cursor(row=0)
    await pilot.pause()
    await pilot.press("down")
    await pilot.pause()
    assert table.cursor_row == 1
    assert app.device.selected_log == []
    assert app._running is True


class TestReportScreen:
    """The help frame: escape, q, and this tool's extra enter."""

    @pytest.mark.parametrize("key", ["escape", "q", "enter"])
    async def test_every_documented_key_closes_it(self, key):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await _until(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.press(key)
            await _until(pilot, lambda: not isinstance(app.screen, ReportScreen))
            await _still_usable(app, pilot)

    async def test_the_help_body_is_the_tools_own_words(self):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await _until(pilot, lambda: isinstance(app.screen, ReportScreen))
            body = str(app.screen.query_one(".body", Static).visual)
            assert "Program Change" in body
            assert "nanosyned" in body


class TestPromptScreen:
    """``c`` opens the channel prompt; escape cancels, enter answers."""

    async def test_escape_closes_without_changing_the_channel(self):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            before = app.device.channel
            await pilot.press("c")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, PromptScreen))
            assert app.device.channel == before
            await _still_usable(app, pilot)

    async def test_enter_answers_the_prompt(self):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("c")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "9"
            await pilot.press("enter")
            await _until(pilot, lambda: not isinstance(app.screen, PromptScreen))
            assert app.device.channel == 8
            await _still_usable(app, pilot)


class TestConfirmScreen:
    """``y`` confirms; ``n`` and escape cancel. There is no ``q``."""

    @staticmethod
    async def _open(app, pilot, sink) -> None:
        app.push_screen(ConfirmScreen("Store it?"), sink.append)
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("y", True), ("n", False), ("escape", False)],
    )
    async def test_each_documented_key_keeps_its_meaning(self, key, expected):
        app = make()
        seen: list[bool] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await self._open(app, pilot, seen)
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [expected]
            await _still_usable(app, pilot)


class TestSearchScreen:
    """``/`` opens the library's form; escape cancels, enter searches."""

    async def test_escape_closes_and_leaves_the_browser_usable(self):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await _until(pilot, lambda: isinstance(app.screen, SearchScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, SearchScreen))
            await _still_usable(app, pilot)

    async def test_enter_searches_and_opens_the_report(self):
        app = make()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await _until(pilot, lambda: isinstance(app.screen, SearchScreen))
            app.screen.query_one("#search-needle", Input).value = "Invented"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: not isinstance(app.screen, ReportScreen))
            await _still_usable(app, pilot)


class TestScanOfferScreen:
    """Three answers plus escape, and the browser is still there after."""

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("y", "scan"), ("n", "later"), ("d", "never"), ("escape", "later")],
    )
    async def test_each_documented_key_dismisses_with_its_answer(self, key, expected):
        app = make()
        seen: list[str] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(ScanOfferScreen(), seen.append)
            await _until(pilot, lambda: isinstance(app.screen, ScanOfferScreen))
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [expected]
            await _still_usable(app, pilot)


class TestScanScreen:
    """Cancel is escape or q, and the screen hands the app ``None``."""

    @staticmethod
    def _blocking_read():
        started = threading.Event()

        def read(on_progress, cancel):
            on_progress(1, 2)
            started.set()
            while not cancel.wait(0.01):
                pass
            return {0: "never adopted"}

        return read, started

    @pytest.mark.parametrize("key", ["escape", "q"])
    async def test_each_documented_key_cancels(self, key):
        app = make()
        seen: list[dict[int, str] | None] = []
        read, started = self._blocking_read()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(ScanScreen(read, total=2), seen.append)
            await pilot.pause()
            assert started.wait(1)
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _until(pilot, lambda: not isinstance(app.screen, ScanScreen))
            await _still_usable(app, pilot)

    async def test_the_cancel_button_cancels_too(self):
        app = make()
        seen: list[dict[int, str] | None] = []
        read, started = self._blocking_read()
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(ScanScreen(read, total=2), seen.append)
            await pilot.pause()
            assert started.wait(1)
            await pilot.click("#cancel")
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _still_usable(app, pilot)


class TestEditorScreen:
    """The editor returns ``None`` unless armed and fired with ``w``."""

    @staticmethod
    def _screen() -> EditorScreen:
        editor = ProgramEditor(0, DemoDevice().read_program(0))
        return EditorScreen(editor, slot="User 000", replaced="Invented One")

    @pytest.mark.parametrize("key", ["escape", "q"])
    async def test_each_documented_close_key_stores_nothing(self, key):
        app = make(allow_write=True)
        seen: list[bytes | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(self._screen(), seen.append)
            await _until(pilot, lambda: isinstance(app.screen, EditorScreen))
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            assert app.device.program_writes == []
            await _still_usable(app, pilot)

    async def test_n_opens_the_name_prompt_and_escape_returns(self):
        app = make(allow_write=True)
        seen: list[bytes | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(self._screen(), seen.append)
            await _until(pilot, lambda: isinstance(app.screen, EditorScreen))
            await pilot.press("n")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: isinstance(app.screen, EditorScreen))
            await pilot.press("escape")
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _still_usable(app, pilot)


class TestTheMixScreen:
    """The mix editor: escape, q, and the gate-then-arm-then-store path.

    Guarded rather than omitted: a screen that appears in
    ``nanosyned.screens`` or ``nanosyned.scan`` without a dismissal test
    is exactly the silent gap this file exists to close, and the skip
    below says plainly that the screen is what is missing.

    ``MixScreen`` takes the record it edits, so this class reads mix 0
    from the demo before pushing it, exactly as the app's picker does.
    A screen pushed without the app's gate still has one of its own, so
    ``w`` arms it here just as it does in the app.
    """

    @staticmethod
    def _screen():
        mix_screen = getattr(screens, "MixScreen", None) or getattr(
            scan_module, "MixScreen", None
        )
        if mix_screen is None:
            pytest.skip(
                "nanosyned has no mix screen yet: nothing named MixScreen in "
                "nanosyned.screens or nanosyned.scan"
            )
        return mix_screen

    @pytest.mark.parametrize("key", ["escape", "q"])
    async def test_every_dismissal_key_closes_it(self, key):
        mix_screen = self._screen()
        app = make()
        seen: list[bytes | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(
                mix_screen(DemoDevice().read_mix(0), number=0, replaced="Invented"),
                seen.append,
            )
            await _until(pilot, lambda: isinstance(app.screen, mix_screen))
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _still_usable(app, pilot)

    async def test_unarmed_store_refuses_and_leaves_the_screen_open(self):
        mix_screen = self._screen()
        app = make()
        seen: list[bytes | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(
                mix_screen(DemoDevice().read_mix(0), number=0, replaced="Invented"),
                seen.append,
            )
            await _until(pilot, lambda: isinstance(app.screen, mix_screen))
            await pilot.press("s")
            await pilot.pause()
            assert seen == []
            assert isinstance(app.screen, mix_screen)
            await pilot.press("escape")
            await _until(pilot, lambda: bool(seen))
            await _still_usable(app, pilot)

    async def test_edit_then_arm_then_fire_returns_the_new_record(self):
        mix_screen = self._screen()
        record = DemoDevice().read_mix(0)
        wanted = (mixview.get_channel_field(record, 0, "program") + 1) % 128
        app = make()
        seen: list[bytes | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(
                mix_screen(
                    record,
                    number=0,
                    replaced="Invented",
                    gate=EditGate(armed=True),
                ),
                seen.append,
            )
            await _until(pilot, lambda: isinstance(app.screen, mix_screen))
            await pilot.press("e")
            await _until(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
            app.screen.query_one("#program-table", DataTable).move_cursor(row=wanted)
            await pilot.press("enter")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, mix_screen)
                    and mixview.get_channel_field(app.screen.record, 0, "program")
                    == wanted
                ),
            )
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("s")
            await _until(pilot, lambda: bool(seen))
            assert seen[0] is not None
            assert mixview.get_channel_field(seen[0], 0, "program") == wanted
            assert seen[0] != record
            await _still_usable(app, pilot)
