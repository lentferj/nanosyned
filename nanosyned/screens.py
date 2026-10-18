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

"""The widgets the application opens.

Split out of :mod:`nanosyned.app` so the browser itself stays readable, on
the same shape as :mod:`rxved.screens` and :mod:`emorphed.screens`. This
module holds every widget the application opens. It imports nothing from
:mod:`nanosyned.app`, so the dependency runs one way only and any part of
the program can import it without a cycle.

``ReportScreen`` and ``PromptScreen`` used to be defined in the browser
itself, eight copies of the same class across the family. They are the
library's now -- :mod:`vinsynlib.ui.report` and
:mod:`vinsynlib.ui.prompt`, imported below and re-exported so every call
site reads exactly as it did, with the one difference each sibling keeps:
``enter`` closes the report, so the frame's words are the library's and the
key is this tool's.

``EditorScreen`` is the one screen here that can destroy something. It
follows the sibling projects' rule for a destructive operation -- arm, then
fire with a *different* key, and anything that moves disarms -- because the
thing it replaces is a program somebody made.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nanosyned import mix as mixview
from nanosyned.editor import GlobalEditor, GlobalRow, ProgramEditor
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.hints import KeyHints as _LibraryKeyHints
from vinsynlib.ui.modals import ChoiceScreen
from vinsynlib.ui.prompt import PromptScreen
from vinsynlib.ui.report import ReportScreen as _Frame

__all__ = [
    "ConfirmScreen",
    "EditorScreen",
    "GlobalScreen",
    "KeyHints",
    "MixScreen",
    "PromptScreen",
    "ReportScreen",
]


#: rxved's shape: ``enter`` closes as well. Three lines, no rewrite --
#: so the frame's words are the library's and the only difference is the
#: key that closes it.
class ReportScreen(_Frame):
    """nanosyned's shape: ``enter`` closes as well. Three lines, no rewrite."""

    BINDINGS: ClassVar[list[Any]] = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("enter", "close", "Close"),
    ]


class KeyHints(_LibraryKeyHints):
    """The library legend, relaid out after every re-wrap.

    The library widget re-wraps its text on mount and on resize but never
    asks for a layout, so ``height: auto`` keeps whatever height the first
    render gave it. That first render happens before the widget has a width:
    the wrap falls back to its minimum, the whole legend stacks into about a
    dozen lines, and the footer stays that tall -- a band of empty panel
    under the keys -- until the terminal is resized. Requesting the layout
    after each re-wrap keeps the footer only as tall as the wrapped text,
    which is the point of wrapping it here at all.
    """

    def on_mount(self) -> None:
        super().on_mount()
        self.call_after_refresh(self.refresh, layout=True)

    def on_resize(self) -> None:
        super().on_resize()
        self.call_after_refresh(self.refresh, layout=True)


class EditorScreen(ModalScreen[bytes | None]):
    """One User program's name, and an arm-then-fire store.

    Returns the new 350-byte record when the user fires, ``None`` when they
    close without storing. **It sends nothing itself** -- there is no device
    and no clock in this screen -- so the app can claim its exchange on the
    main thread, back the slot up, write it and read it back in the one
    worker every other MIDI action uses.

    Three deliberate steps, none of them a single keystroke:

    1. Pick the new name with `n` (the library's prompt) and press `a` to
       arm. Arming names the destination **and what is about to be
       replaced** -- "User 005" means nothing; the name it holds means
       everything.
    2. Press `w`, a different key, while armed. Only then does the screen
       return the record.
    3. Anything that changes where the user is looking -- the arrow keys,
       typing a name, reverting -- disarms.

    Escape closes without storing, armed or not.
    """

    DEFAULT_CSS = """
    EditorScreen { align: center middle; }
    EditorScreen > Vertical {
        width: 74; height: auto; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    EditorScreen .armed {
        color: $error;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "close", "Cancel"),
        Binding("q", "close", "Cancel"),
        Binding("n", "edit_name", "Name"),
        Binding("a", "arm", "Arm"),
        # Deliberately not Enter, and deliberately not next to "a": the fire
        # key should not be the one a finger is resting on after arming.
        Binding("w", "fire", "Store"),
        Binding("r", "revert", "Revert"),
        # There is no table to move a cursor over here, but reaching for one
        # is still a change of mind: any movement disarms, as it does in the
        # family's store screens.
        Binding("up", "disarm", "Disarm", show=False),
        Binding("down", "disarm", "Disarm", show=False),
        Binding("left", "disarm", "Disarm", show=False),
        Binding("right", "disarm", "Disarm", show=False),
    ]

    def __init__(
        self,
        editor: ProgramEditor,
        *,
        slot: str,
        replaced: str,
    ) -> None:
        super().__init__()
        self._editor = editor
        #: The destination, as the browser names it ("User 005").
        self._slot = slot
        #: The name the destination holds now -- what firing destroys.
        self._replaced = replaced
        self._armed = False
        self._notice = ""

    @property
    def armed(self) -> bool:
        """Whether `w` would store right now."""
        return self._armed

    def compose(self) -> ComposeResult:
        with Vertical(id="editor-dialog"):
            yield Label(f"[b]Edit {literal(self._slot)}[/b]", id="editor-title")
            yield Static("", id="editor-name")
            yield Static("", id="editor-status")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        name = literal(self._editor.name.rstrip()) or "[dim](blank)[/dim]"
        state = "unsaved changes" if self._editor.dirty else "unchanged"
        self.query_one("#editor-name", Static).update(
            f"[b]{name}[/b]   [dim]{state}[/dim]"
        )
        status = self.query_one("#editor-status", Static)
        status.update(self._status())
        status.set_class(self._armed, "armed")

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if self._armed:
            return (
                f"[b]ARMED[/b] — about to overwrite {literal(self._slot)} — "
                f"{literal(self._replaced) or '(blank)'}.\n"
                f"[b]w[/b] stores it and reads it back; its current contents "
                f"are saved to a backup file first. Any other key disarms."
            )
        return "[dim]n name · a arm the store · r revert · esc cancel[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        """Put one sentence in the screen's own status row.

        ``sentence`` is escaped here rather than at every call site: the
        rename refusal quotes the character the user typed, and a bracket
        in that character would otherwise be read as markup.
        """
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh()

    def _disarm(self) -> None:
        self._armed = False

    def action_edit_name(self) -> None:
        """Open the text prompt. Typing is a change of mind: disarm first."""
        self._disarm()
        self._notice = ""
        self._refresh()
        self.app.push_screen(
            PromptScreen("Program name:", self._editor.name.rstrip()), self._named
        )

    def _named(self, text: str | None) -> None:
        if text is None:
            self._refresh()
            return
        problem = self._editor.set_name(text)
        if problem is not None:
            self._say(problem, refused=True)
            return
        self._notice = ""
        self._refresh()

    def action_arm(self) -> None:
        if not self._editor.dirty:
            self._say("nothing to store — the name is unchanged", refused=True)
            return
        self._armed = True
        self._notice = ""
        self._refresh()

    def action_disarm(self) -> None:
        if self._armed:
            self._disarm()
            self._refresh()

    def action_revert(self) -> None:
        """Undo the edits in this dialog. Sends nothing; disarms."""
        self._disarm()
        self._editor.reset()
        self._notice = ""
        self._refresh()

    def action_fire(self) -> None:
        """Return the record, but only while armed. A second look first."""
        if not self._armed:
            self._say("not armed — press a first", refused=True)
            return
        if not self._editor.dirty:
            self._disarm()
            self._say("nothing to store — the name is unchanged", refused=True)
            return
        record = self._editor.record()
        self._disarm()
        self.dismiss(record)

    def action_close(self) -> None:
        self.dismiss(None)


class MixScreen(ModalScreen[bytes | None]):
    """One mix's sixteen channels, and an arm-then-fire store.

    Returns the new 138-byte mix record when the user fires, ``None`` when
    they close without storing. **It sends nothing itself** -- there is no
    device and no clock in this screen -- so the app can claim its exchange
    on the main thread, back the mix up, write it and read it back in the
    one worker every other MIDI action uses.

    The browser's banks are programs, not mixes, so this screen is reached
    through the app's mix picker (`m`): the mix number is chosen there, and
    this screen only ever edits the record it was handed.

    Editing is staged: ``e`` asks which of the three fields to edit and then
    for its value, and the change lands in a working copy. Nothing reaches
    the unit until ``a`` arms and ``w`` -- a different key -- fires. Anything
    that moves the cursor or opens a dialog disarms, because the thing being
    replaced is a mix somebody made.
    """

    DEFAULT_CSS = """
    MixScreen { align: center middle; }
    MixScreen > Vertical {
        width: 84; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    MixScreen DataTable { height: 1fr; }
    MixScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    MixScreen #mix-status { height: auto; color: $text; padding-top: 1; }
    MixScreen .armed {
        color: $error;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "close", "Cancel"),
        Binding("q", "close", "Cancel"),
        Binding("e", "edit_field", "Edit field"),
        Binding("a", "arm", "Arm"),
        # Deliberately not Enter, and deliberately not next to "a": the fire
        # key should not be the one a finger is resting on after arming.
        Binding("w", "fire", "Store"),
        Binding("r", "revert", "Revert"),
    ]

    def __init__(self, record: bytes, *, number: int, replaced: str) -> None:
        super().__init__()
        self._original = bytes(record)
        self._working = bytes(record)
        #: Which of the 100 user mixes this is.
        self._number = number
        #: The name the mix held when it was read -- what firing destroys.
        self._replaced = replaced
        self._armed = False
        self._notice = ""

    @property
    def armed(self) -> bool:
        """Whether `w` would store right now."""
        return self._armed

    @property
    def record(self) -> bytes:
        """The working copy, as firing would return it."""
        return self._working

    def compose(self) -> ComposeResult:
        with Vertical(id="mix-dialog"):
            yield Label("", id="mix-title")
            yield DataTable(id="mix-table", cursor_type="row")
            yield Static("", id="mix-status")
            yield Static(
                "[dim]↑↓ pick a channel · e edit program/volume/pan · "
                "a arm · w store · r revert · esc cancel[/dim]",
                id="mix-note",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#mix-table", DataTable)
        for label, key in (
            ("ch", "ch"),
            ("program", "program"),
            ("volume", "volume"),
            ("pan", "pan"),
            ("enable", "enable"),
        ):
            table.add_column(label, key=key)
        self._fill()

    def _fill(self) -> None:
        """Redraw the table from the working copy, keeping the cursor row."""
        table = self.query_one("#mix-table", DataTable)
        row = table.cursor_row or 0
        table.clear()
        for channel in mixview.channels(self._working):
            table.add_row(
                str(channel.channel + 1),
                _shown(channel.program),
                _shown(channel.volume),
                _shown(channel.pan),
                _shown(None if channel.enable is None else int(channel.enable)),
                key=str(channel.channel),
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._refresh()

    def _refresh(self) -> None:
        name = literal(mixview.mix_name(self._working).rstrip()) or "[dim](blank)[/dim]"
        state = "unsaved changes" if self._working != self._original else "unchanged"
        self.query_one("#mix-title", Label).update(
            f"[b]Mix {self._number:03d}[/b]  {name}   [dim]{state}[/dim]"
        )
        status = self.query_one("#mix-status", Static)
        status.update(self._status())
        status.set_class(self._armed, "armed")

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if self._armed:
            return (
                f"[b]ARMED[/b] — about to store mix {self._number:03d}, "
                f"replacing {literal(self._replaced) or '(blank)'}.\n"
                f"[b]w[/b] stores it and reads it back; its current contents "
                f"are saved to a backup file first. Any other key disarms."
            )
        return "[dim]nothing is sent until a then w[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        """Put one sentence in the screen's own status row."""
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh()

    def _disarm(self) -> None:
        self._armed = False

    def _cursor_row(self) -> int:
        table = self.query_one("#mix-table", DataTable)
        last = len(mixview.channels(self._working)) - 1
        return min(max(table.cursor_row or 0, 0), last)

    def action_edit_field(self) -> None:
        """Choose a field, then type its value. Typing is a change of mind."""
        self._disarm()
        self._notice = ""
        row = self._cursor_row()
        self.app.push_screen(
            ChoiceScreen(
                f"Channel {row + 1}: which field?",
                list(mixview.FIELDS),
                0,
                status_message="the change is staged; nothing is sent yet",
            ),
            lambda choice: self._field_chosen(row, choice),
        )

    def _field_chosen(self, row: int, choice: int | None) -> None:
        if choice is None:
            self._refresh()
            return
        label = mixview.FIELDS[choice]
        param = mixview.param_for(row, label)
        if param is None:
            self._say(
                f"the parameter table has no {label} row for channel {row + 1}",
                refused=True,
            )
            return
        current = mixview.get_channel_field(self._working, row, label)
        self.app.push_screen(
            PromptScreen(
                f"Channel {row + 1} {label} ({param.low}-{param.high}):",
                "" if current is None else str(current),
            ),
            lambda text: self._typed(row, label, text),
        )

    def _typed(self, row: int, label: str, text: str | None) -> None:
        if text is None:
            self._refresh()
            return
        try:
            value = int(text.strip())
        except ValueError:
            self._say(f"{text!r} is not a number", refused=True)
            return
        param = mixview.param_for(row, label)
        if param is None:  # pragma: no cover -- _field_chosen refused it
            self._say(
                f"the parameter table has no {label} row for channel {row + 1}",
                refused=True,
            )
            return
        clamped = param.clamp(value)
        self._working = mixview.set_channel_field(self._working, row, label, value)
        self._fill()
        note = " (clamped)" if clamped != value else ""
        self._say(f"channel {row + 1} {label}: {clamped}{note} — not stored yet")

    def on_key(self, event) -> None:
        """Any key but the fire key is a change of mind while armed.

        The status row promises this, and it is the point of a second key:
        a hand that comes down on the keyboard after arming cancels the
        store instead of firing it.
        """
        if self._armed and event.key != "w":
            self._disarm()
            self._refresh()

    def on_data_table_row_highlighted(self, event) -> None:
        """Moving the cursor is a change of mind, as it is in the family."""
        if event.data_table.id == "mix-table" and self._armed:
            self._disarm()
            self._refresh()

    def action_arm(self) -> None:
        if self._working == self._original:
            self._say("nothing to store — no channel has been changed", refused=True)
            return
        self._armed = True
        self._notice = ""
        self._refresh()

    def action_revert(self) -> None:
        """Undo the staged edits. Sends nothing; disarms."""
        self._disarm()
        self._working = self._original
        self._notice = ""
        self._fill()

    def action_fire(self) -> None:
        """Return the record, but only while armed. A second look first."""
        if not self._armed:
            self._say("not armed — press a first", refused=True)
            return
        if self._working == self._original:
            self._disarm()
            self._say("nothing to store — no channel has been changed", refused=True)
            return
        record = self._working
        self._disarm()
        self.dismiss(record)

    def action_close(self) -> None:
        self.dismiss(None)


class GlobalScreen(ModalScreen[bytes | None]):
    """The unit's one global record, table-driven, with an armed store.

    Every documented row of :data:`nano.params.GLOBAL_PARAMS` is shown, in
    the spec's order, with its value, its range and -- where it must not be
    written -- the reason. The rows the specification documents for another
    model (``(QS6,7,8 only)`` and the like), the deleted parameters and the
    rows a older dump does not carry are **shown but not editable**: a
    store here writes the whole record, and writing a value the unit is
    documented to ignore while reporting success would be a lie about what
    happened.

    As in :class:`MixScreen`, nothing is sent until `a` then `w`, and
    anything that moves the cursor or opens a dialog disarms.
    """

    DEFAULT_CSS = """
    GlobalScreen { align: center middle; }
    GlobalScreen > Vertical {
        width: 104; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    GlobalScreen DataTable { height: 1fr; }
    GlobalScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    GlobalScreen #global-status { height: auto; color: $text; padding-top: 1; }
    GlobalScreen .armed {
        color: $error;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "close", "Cancel"),
        Binding("q", "close", "Cancel"),
        Binding("e", "edit_value", "Edit"),
        Binding("a", "arm", "Arm"),
        Binding("w", "fire", "Store"),
        Binding("r", "revert", "Revert"),
    ]

    def __init__(self, editor: GlobalEditor) -> None:
        super().__init__()
        self._editor = editor
        self._armed = False
        self._notice = ""

    @property
    def armed(self) -> bool:
        """Whether `w` would store right now."""
        return self._armed

    @property
    def editor(self) -> GlobalEditor:
        """The rules object, so a test can ask it what it holds."""
        return self._editor

    def compose(self) -> ComposeResult:
        with Vertical(id="global-dialog"):
            yield Label("", id="global-title")
            yield DataTable(id="global-table", cursor_type="row")
            yield Static("", id="global-status")
            yield Static(
                "[dim]↑↓ pick a setting · e edit · a arm · w store · "
                "r revert · esc cancel. Rows with a note are shown but not "
                "written -- the spec marks them for another model, or as "
                "deleted parameters.[/dim]",
                id="global-note",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#global-table", DataTable)
        for label, key in (
            ("parameter", "param"),
            ("value", "value"),
            ("range", "range"),
            ("note", "note"),
        ):
            table.add_column(label, key=key)
        self._fill()

    def _rows(self) -> list[GlobalRow]:
        return self._editor.rows()

    def _fill(self) -> None:
        """Redraw the table from the editor, keeping the cursor row."""
        table = self.query_one("#global-table", DataTable)
        row = table.cursor_row or 0
        table.clear()
        for index, entry in enumerate(self._rows()):
            table.add_row(
                literal(entry.param.label),
                _shown(entry.value),
                f"{entry.param.low}..{entry.param.high}",
                "" if entry.writable else literal(entry.refusal or ""),
                key=str(index),
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._refresh()

    def _refresh(self) -> None:
        state = "unsaved changes" if self._editor.dirty else "unchanged"
        self.query_one("#global-title", Label).update(
            f"[b]Global settings[/b]  [dim]{self._editor.size} bytes · {state}[/dim]"
        )
        status = self.query_one("#global-status", Static)
        status.update(self._status())
        status.set_class(self._armed, "armed")

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if self._armed:
            return (
                "[b]ARMED[/b] — about to store the global settings. There is "
                "one set: this replaces what the whole instrument is "
                "configured with.\n[b]w[/b] stores it and reads it back; "
                "its current contents are saved to a backup file first. Any "
                "other key disarms."
            )
        return "[dim]nothing is sent until a then w[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh()

    def _disarm(self) -> None:
        self._armed = False

    def _cursor_row(self) -> int:
        table = self.query_one("#global-table", DataTable)
        rows = self._rows()
        if not rows:
            return 0
        return min(max(table.cursor_row or 0, 0), len(rows) - 1)

    def action_edit_value(self) -> None:
        """Prompt for one row's value. Typing is a change of mind."""
        self._disarm()
        self._notice = ""
        row = self._rows()[self._cursor_row()]
        if not row.writable:
            self._say(f"{row.param.label} is not written: {row.refusal}", refused=True)
            return
        self.app.push_screen(
            PromptScreen(
                f"{row.param.label} ({row.param.low}..{row.param.high}):",
                "" if row.value is None else str(row.value),
            ),
            self._typed,
        )

    def _typed(self, text: str | None) -> None:
        if text is None:
            self._refresh()
            return
        row = self._rows()[self._cursor_row()]
        try:
            value = int(text.strip())
        except ValueError:
            self._say(f"{text!r} is not a number", refused=True)
            return
        problem = self._editor.set_value(row.param.label, value)
        if problem is not None:
            self._say(problem, refused=True)
            return
        clamped = row.param.clamp(value)
        self._fill()
        note = " (clamped)" if clamped != value else ""
        self._say(f"{row.param.label}: {clamped}{note} — not stored yet")

    def on_key(self, event) -> None:
        """Any key but the fire key is a change of mind while armed."""
        if self._armed and event.key != "w":
            self._disarm()
            self._refresh()

    def on_data_table_row_highlighted(self, event) -> None:
        """Moving the cursor is a change of mind, as it is in the family."""
        if event.data_table.id == "global-table" and self._armed:
            self._disarm()
            self._refresh()

    def action_arm(self) -> None:
        if not self._editor.dirty:
            self._say("nothing to store — no setting has been changed", refused=True)
            return
        self._armed = True
        self._notice = ""
        self._refresh()

    def action_revert(self) -> None:
        """Undo the staged edits. Sends nothing; disarms."""
        self._disarm()
        self._editor.reset()
        self._notice = ""
        self._fill()

    def action_fire(self) -> None:
        """Return the record, but only while armed. A second look first."""
        if not self._armed:
            self._say("not armed — press a first", refused=True)
            return
        if not self._editor.dirty:
            self._disarm()
            self._say("nothing to store — no setting has been changed", refused=True)
            return
        record = self._editor.record()
        self._disarm()
        self.dismiss(record)

    def action_close(self) -> None:
        self.dismiss(None)


def _shown(value: int | None) -> str:
    """A table cell for a value, with an honest dash for an absent row."""
    return "-" if value is None else str(value)
