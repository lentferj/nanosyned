# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The key-hint legend is ported from the sibling rxved and p2ked projects,
# which port it from s3ked, eosed and k2kremote:
#   Copyright (C) 2026  rxved / p2ked / s3ked / eosed / k2kremote
#   contributors                                     - GPL-2.0-or-later
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

"""``nanosyned`` -- a terminal browser for the Alesis NanoSynth.

Two panes: banks on the left, that bank's programs on the right.

Four rules, each about not lying to the user:

**Moving the cursor is silent by default.** Selecting a program changes
what the instrument plays. Enter always selects; `a` explicitly enables
cursor-follow auto-load, and the choice is remembered. A test enforces the
default silence.

**Reading names makes no sound**, and reaches exactly one bank. The
protocol has a request for the 128 user programs and for nothing else: the
General MIDI bank and the three preset banks are ROM. So four fifths of
what this browser shows comes from a catalog and one fifth comes from the
instrument, and the two are marked differently on purpose.

**Bank Select is Controller 0.** The unit ignores Controller 32, which many
sequencers send instead; the manual says so plainly. Enter sends Bank
Select and then Program Change, always both, because a Program Change
alone lands in whatever bank the unit was last put into -- possibly by
somebody turning a knob.

**Silence is not an answer, and this unit is quiet by design.** It never
replies to an Identity Request when it receives one: it holds the reply
and sends it the next time it answers some other System Exclusive message.
Everything here that asks the unit anything allows for that.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from typing import Any, ClassVar, cast

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Header, Static

from nano import (
    banks,
    exporting,
    fullbackup,
    identity,
    importing,
    importplan,
    initbank,
    livenames,
    preset_memory,
    verify,
    writing,
)
from nano import (
    catalog as cat,
)
from nano import config as cfg
from nano import records as rec
from nano.config import UNSET
from nano.favorites import rating_cell
from nanosyned.appendbank import MANUAL, AppendBankScreen
from nanosyned.editor import (
    EditGate,
    EditRecord,
    EffectsEditor,
    EffectsEditRecord,
    GlobalEditor,
    GlobalEditRecord,
    ImportRecord,
    MixEditRecord,
    ProgramEditor,
    RestoreRecord,
)
from nanosyned.importbank import WholeBankScreen
from nanosyned.importflow import run_import_flow
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.importsingle import SingleMappingScreen
from nanosyned.initbank import InitBankScreen
from nanosyned.paramsui import ParameterScreen
from nanosyned.picker import FilePickerScreen
from nanosyned.restorebank import FullRestoreScreen
from nanosyned.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen
from nanosyned.screens import (
    ConfirmScreen,
    EditorScreen,
    EffectsScreen,
    GlobalScreen,
    KeyHints,
    MixScreen,
    PromptScreen,
    ReportScreen,
)
from nanosyned.text import literal
from vinsynlib import keys
from vinsynlib.build import build_of
from vinsynlib.cli import add_common_arguments, make_parser, validate_common
from vinsynlib.keys import wrap_blocks as _wrap_blocks
from vinsynlib.ui.modals import (
    ChoiceScreen,
    RatingFilter,
    RatingFilterScreen,
    SearchScreen,
)
from vinsynlib.ui.work import QUIET_BRIDGE_ERRORS, BusyGate, close_when_idle
from vinsynlib.undo import Record, UndoLog

__all__ = ["KEY_HINTS", "NanosynedApp", "build_parser", "main", "wrap_blocks"]

_SEP = " · "

#: The family's quiet error set, plus the errors this unit's bridge and
#: the protocol itself raise on a conversation gone wrong (compare
#: emorphed's set of the same name). A programming error -- a TypeError,
#: a KeyError -- is in none of these, so it raises out of the worker
#: instead of being dressed up as a device fault in the status bar.
_BRIDGE_ERRORS: tuple[type[BaseException], ...] = (
    *tuple(QUIET_BRIDGE_ERRORS),
    ValueError,
    LookupError,
    RuntimeError,
    SystemError,
)


class _ScanCancelled(Exception):
    """Stop a User-bank read between two requests.

    ``read_program_names`` reports progress after each program has come
    back, so raising from its callback is the one place a cancel can land
    without interrupting a message already on the wire. The alternative --
    checking a flag only after all 128 requests -- is a Cancel button that
    does nothing for as long as the read takes.
    """


#: What `F` steps through. The same three the sibling rxved and p2ked use,
#: so the key means the same thing across these projects.
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"

#: The left pane's pseudo-bank for the unit's 100 mixes. It is not a
#: program bank: no Bank Select, no favourites, no catalog.
MIXES_BANK = "MIXES"
MIX_BANK = banks.Bank(
    MIXES_BANK, "Mixes", 0, readable=False, front_panel=False, note="100 mixes"
)
MIX_SLOTS: tuple[banks.Slot, ...] = tuple(
    banks.Slot(MIX_BANK, number, number) for number in range(banks.MIXES)
)
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all slots",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}


#: The legend. Every binding the app has, in the order somebody meets them.
#: Built from the family's shared legend rather than hand-written: it used
#: to be a tuple of its own, in its own order. ``keys.legend`` puts this
#: tool's own hints in the one place the family leaves for them -- after
#: `n note`, before `i device` -- and this tool's are the scan key, the two
#: rating keys, auto-load and pane focus, and its editors, import/export,
#: full backup/restore, init, gate and undo keys. ``w``/``z``/``Z`` are the family's
#: canonical editor keys, spelled the family's way; this browser legend has
#: no editor tier, so they are carried here as this tool's hints.
WRITE_HINTS: tuple[str, ...] = (
    "e edit",
    "x effects",
    "p parameters",
    "M program/mix mode",
    "g global",
    "w write gate",
    "I import",
    "E export favourites",
    "B backup",
    "R restore",
    "N init bank",
    "z undo",
    "Z undo all",
)
KEY_HINTS = keys.legend(
    extras=(
        "S scan device",
        "* rating",
        "V rating filter",
        "a auto-load",
        "←/→ pane",
        *WRITE_HINTS,
    )
)


def wrap_blocks(blocks, width: int, sep: str = _SEP) -> str:
    """Pack hints into lines no wider than ``width``.

    Re-exported from :func:`vinsynlib.keys.wrap_blocks`, which every tool
    in this family now uses. Kept as a name because it is part of this
    module's published surface.
    """
    return _wrap_blocks(blocks, width, sep)


class PaneTable(DataTable):
    """A pane table whose left/right arrows move focus between panes."""

    BINDINGS: ClassVar[list[BindingType]] = cast(
        list[BindingType],
        [
            binding
            for binding in DataTable.BINDINGS
            if isinstance(binding, Binding) and binding.key not in ("left", "right")
        ]
        + [
            Binding("left", "focus_left_pane", "Left pane", show=False),
            Binding("right", "focus_right_pane", "Right pane", show=False),
        ],
    )

    def action_focus_left_pane(self) -> None:
        app: Any = self.app
        app.action_focus_left_pane()

    def action_focus_right_pane(self) -> None:
        app: Any = self.app
        app.action_focus_right_pane()


class NanosynedApp(App):
    """The browser."""

    CSS = """
    Screen { layers: base; }
    #panes { height: 1fr; }
    /* Sized to its content. A fixed width does not truncate the end
       of a label -- the table scrolls sideways and clips the
       *start*, so a bank reads as nonsense rather than as narrow. */
    #bank-table {
        width: auto; min-width: 20; max-width: 52;
        border-right: solid $panel;
    }
    #slot-table { width: 1fr; }
    DataTable { height: 1fr; }
    #detail { height: 3; padding: 0 1; border-top: solid $panel; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    /* The ID is repeated or the rule never paints: an ID selector outranks
       a class, so a bare ``.refused`` was dead CSS and every refusal drew in
       the same grey as a success. Red and bold, the sibling rxved's shape,
       so a refused action is legible at a glance. */
    #status.refused {
        background: $error;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # Enter is NOT bound here: a focused DataTable consumes it for its
        # own row selection, so it arrives as RowSelected instead.
        Binding("r", "read_names", "Read names"),
        # There is no `R` rebuild key, deliberately: on this instrument
        # only the User bank can be dumped, and "rebuild" would have to
        # mean re-reading the printed catalog for the other four. That
        # catalog is a transcription of the manual (tools/extract_catalog.py),
        # not a question the unit can answer, so a key for it would send
        # nothing and change nothing.
        Binding("S", "scan_device", "Scan device"),
        Binding("left_square_bracket", "channel_down", "Channel -"),
        Binding("right_square_bracket", "channel_up", "Channel +"),
        Binding("c", "pick_channel", "Set channel"),
        Binding("f", "toggle_favorite", "Favourite"),
        Binding("F", "cycle_favorites", "Favourites view"),
        Binding("t", "edit_tags", "Tags"),
        Binding("n", "edit_note", "Note"),
        Binding("asterisk", "edit_rating", "Rating"),
        Binding("V", "rating_filter", "Rating filter"),
        Binding("slash", "search", "Search"),
        Binding("a", "toggle_auto_load", "Auto-load"),
        # The write path. `e` opens the editor only while the gate is armed;
        # `e` opens the focused mix editor in Mixes and `g` the global editor
        # under the same rule; `M` sends Mode Select, which changes what plays and
        # stores nothing. `w` is the family's canonical gate key, and `z`/`Z`
        # re-send what a store replaced. Every one of them is inert until `w`.
        Binding("e", "edit_program", "Edit"),
        Binding("x", "edit_effects", "Effects"),
        Binding("p", "edit_parameter", "Parameters"),
        Binding("M", "mode_select", "Program/Mix mode"),
        Binding("g", "edit_global", "Global"),
        Binding("w", "toggle_write_gate", "Write gate"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        Binding("i", "device_info", "Device"),
        Binding("I", "import", "Import"),
        Binding("E", "export_favourites", "Export favourites"),
        Binding("B", "backup", "Backup"),
        Binding("R", "restore", "Restore backup"),
        Binding("N", "init_bank", "Init bank"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(  # noqa: PLR0913, PLR0915 -- one keyword per injection point
        self,
        device,
        *,
        catalog=None,
        favorites=None,
        config_path: str | None = None,
        catalog_path: str | None = None,
        memory_path: str | None = None,
        allow_write: bool = False,
    ) -> None:
        super().__init__()
        self.device = device
        self.catalog = catalog if catalog is not None else cat.empty()
        #: Injected, never opened here, so a test cannot write into the
        #: user's real database.
        self.favorites = favorites
        #: The content-addressed memory is optional in tests and embedders:
        #: a path opens it, ``None`` keeps the app strictly slot-based.
        self.memory = (
            preset_memory.PresetMemory(memory_path) if memory_path is not None else None
        )
        #: Where the send channel is remembered. Injected and None
        #: in tests, so a test cannot drop a config into the
        #: working directory.
        self._config_path = config_path
        #: Where the screen remembers where it was: ``ui-state.toml``
        #: beside the settings file, not inside it. The settings writer
        #: refuses a file holding tables or lists, so mixing screen state
        #: into it is what wedged the cache when an older build wrote a
        #: dotted key unquoted. ``None`` when no settings path was given,
        #: which keeps the no-path, no-file rule for tests.
        self._ui_state_path = (
            cfg.ui_state_path(config_path) if config_path is not None else None
        )
        #: Which catalog file this browser is pointed at. The live-names
        #: sidecar travels beside it -- see :func:`nano.livenames.path_for`
        #: -- so a run against another catalog reads that catalog's names.
        self._catalog_path = catalog_path or cat.DEFAULT_PATH
        self.view_mode = VIEW_ALL
        self._lock = threading.RLock()
        self._bank_ids: list[str] = [*banks.bank_ids(), MIXES_BANK]
        self._current_bank = self._bank_ids[0]
        #: Mix names are read from the unit on first use, then cached for
        #: this session. Until they arrive the table shows ``Mix NNN``.
        self._mix_names: dict[int, str] = {}
        self._mix_names_loaded = False
        self._mix_names_reading = False
        #: Best-effort record of the last mode this app sent. The protocol
        #: cannot read the unit's current mode, so this is not a reading.
        self._unit_mode: str | None = None
        self._current: list[banks.Slot] = []
        self._filling = False
        #: The family's busy gate, over the old boolean. It tracks whether
        #: an exchange is in flight (for an idle close) and refuses a
        #: second one before a worker is spawned.
        self._busy_gate = BusyGate()
        #: Whether this launch has already put the scan offer on screen.
        #: The offer has two callers -- the 0.6s timer and an explicit
        #: ``_maybe_offer_scan`` -- and without this the two could stack
        #: two dialogs, so answering the top one left another behind.
        #: "Later" is a deferral to the next launch, not a request to be
        #: asked again in the same launch.
        self._scan_offer_shown = False
        #: One exchange at a time, claimed on the main thread before the
        #: worker is spawned and released by the worker in a ``finally``.
        #: The gate alone cannot carry this: entering it *clears* a
        #: refusal, so between claiming and entering a second action would
        #: find neither signal set and start a second worker. ``_busy``
        #: reads this claim as the third signal.
        self._exchange = threading.Lock()
        #: The write fence, over everything that changes the unit's memory.
        #: Locked at startup unless ``--allow-write`` said otherwise; every
        #: write action asks :meth:`EditGate.check` on the main thread
        #: before a worker exists, so a locked gate sends nothing at all.
        self._write_gate = EditGate(armed=allow_write)
        #: The family's undo log. ``plan``/``settle`` are the doors used
        #: here: the re-send runs on a worker, so the entries leave the log
        #: as the plan is taken, on the main thread, and ``settle`` reports
        #: what actually landed.
        self._undo_log = UndoLog(
            apply_hook=self._undo_apply,
            gate_hook=self._undo_gate,
            status_hook=self._undo_status,
        )
        #: Slots whose pre-first-write contents have a backup file this
        #: session. A set, not a boolean: the rule is once per slot. The
        #: destination is still read in full before *every* store -- the
        #: read is what makes the write undoable and what fails the write if
        #: the slot cannot be read -- but the file is written once. The
        #: workers add to it inside the same ``_busy_gate``/``_lock`` block
        #: as the backup, so the shared set is serialised even though it is
        #: reached from a worker thread.
        self._backed_up: set[str] = set()
        #: The last mix focused in the Mixes pane. Restored below when a
        #: config path was injected; it is used by the editor's own state,
        #: not as an input prompt.
        self._mix_number = 0
        #: The mode the last Mode Select asked for, or ``None`` before one
        #: has been sent. **Not a reading of the unit**: this protocol has
        #: no request that reports the current mode, so this only
        #: pre-selects an entry in the mode dialog and is never displayed as
        #: the unit's state.
        self._last_mode_sent: bool | None = None
        #: Restore the remembered browser state: which bank the left pane
        #: was on, which row the right pane's cursor was on, and where the
        #: cycling ``F`` view stood. Loaded here, not in ``on_mount``,
        #: because the first ``_fill`` down there builds its rows out of
        #: ``view_mode`` and ``_current_bank``; restoring anything later
        #: would mean filling twice. An injected path only -- ``None``
        #: means a test that asked for silence and gets it. The cursor is
        #: clamped to whatever the first fill produced, in ``on_mount``.
        self._saved_slot_cursor: int | None = None
        #: Whether moving the slot cursor sends the focused preset to the
        #: unit. Off by default; toggled with `a` and remembered.
        self._auto_load = False
        self._auto_load_timer: Any = None
        #: The remembered rating filter, or None for "show everything".
        #: Restored here rather than in ``on_mount`` for the same reason
        #: as the view: the first ``_fill`` builds rows through
        #: ``_visible``, which applies it.
        self.rating_filter: RatingFilter | None = None
        #: True while the startup restore is still settling: the queued
        #: first highlight must not be allowed to refill a different bank or
        #: file itself as the place the user was. Set and cleared in
        #: ``on_mount`` / :meth:`_finish_restore`.
        self._restoring = False
        self._remembered_bank = self._current_bank
        self._remembered_slot: int | None = None
        ui_path = self._ui_state_path
        if self._config_path is not None and ui_path is not None:
            from nano import config as _cfg

            try:
                # An older build wrote ``import.folder`` unquoted into
                # the settings file, which TOML reads as a table and the
                # settings writer then refuses. Move it out first, so the
                # channel and port can be saved again.
                _cfg.migrate_legacy_ui_state(self._config_path, ui_path)
                saved_view = _cfg.load_ui_state("view_mode", ui_path, default=UNSET)
                # Never trust a stored value: a view this build renamed
                # or a stale bank index is ignored, and the app opens on
                # its defaults.
                if saved_view is not UNSET and saved_view in VIEW_CYCLE:
                    self.view_mode = saved_view
                saved_bank = _cfg.load_ui_int("bank_index", ui_path)
                if saved_bank is not None and 0 <= saved_bank < len(self._bank_ids):
                    self._current_bank = self._bank_ids[saved_bank]
                self._saved_slot_cursor = _cfg.load_ui_int("slot_cursor", ui_path)
                saved_mix = _cfg.load_ui_int("mix_number", ui_path)
                if saved_mix is not None and 0 <= saved_mix < banks.MIXES:
                    self._mix_number = saved_mix
                # The rating filter, likewise clamped rather than trusted:
                # a hand-edited 9 stars is not a filter, it is a typo.
                saved_stars = _cfg.load_ui_int("rating_stars", ui_path)
                if saved_stars is not None and 0 <= saved_stars <= 5:
                    saved_at_least = _cfg.load_ui_bool("rating_at_least", ui_path)
                    self.rating_filter = RatingFilter(
                        stars=saved_stars, at_least=bool(saved_at_least)
                    )
                saved_auto = _cfg.load_ui_bool("auto_load", ui_path)
                if saved_auto is not None:
                    self._auto_load = bool(saved_auto)
                # Restore the remembered MIDI channel for the device.
                saved_channel = _cfg.load_channel(self._config_path)
                if saved_channel is not None and 0 <= saved_channel <= 15:
                    try:
                        self.device.channel = saved_channel
                    except Exception:
                        pass
            except Exception:
                # The cache is best-effort; a bad read is a default
                # startup.
                self._saved_slot_cursor = None

    @property
    def _busy(self) -> bool:
        """Whether a MIDI exchange is pending or in flight.

        A property over the gate and the exchange, not a flag set beside
        the check: a ``@work(thread=True)`` method returns at once, so a
        boolean it set could only be set on its own thread, too late --
        which is the race two quick selections used to win.
        """
        return (
            self._busy_gate.check() is not None
            or self._busy_gate.is_busy()
            or self._exchange.locked()
        )

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            yield PaneTable(id="bank-table", cursor_type="row")
            yield PaneTable(id="slot-table", cursor_type="row")
        yield Static("", id="detail")
        yield Static("", id="status")
        # KEY_HINTS passed explicitly: the shared widget defaults to the
        # canonical family legend, and this tool's own hints are its
        # business, not the library's.
        yield KeyHints(KEY_HINTS)

    def on_mount(self) -> None:
        self.title = "nanosyned"
        # Live names before anything draws: the panes below are built out
        # of the catalog, so the sidecar's names must be laid over it
        # first or a bank that has been read before opens on printed
        # names for one frame. Best-effort by construction -- a missing
        # or corrupt sidecar reads as an empty one -- so ``applied`` is
        # simply the count of names that came off it.
        applied = livenames.apply_to(
            self.catalog, livenames.path_for(self._catalog_path)
        )
        table = self.query_one("#bank-table", DataTable)
        for label, key in (("bank", "bank"), ("n", "n"), ("", "src"), ("♥", "fav")):
            table.add_column(label, key=key)
        for bank_id in self._bank_ids:
            if bank_id == MIXES_BANK:
                table.add_row("Mixes", str(banks.MIXES), "unit", "", key=MIXES_BANK)
                continue
            entry = banks.bank(bank_id)
            marked = len(self._favorite_keys(bank_id))
            table.add_row(
                entry.label,
                str(entry.count),
                "" if entry.readable else "rom",
                # blank rather than "0": a column of zeroes is
                # noise, and the eye wants the few that differ
                str(marked) if marked else "",
                key=bank_id,
            )

        slots = self.query_one("#slot-table", DataTable)
        # The favourite marker leads the row rather than trailing it: it is
        # a gutter mark the eye runs down, and gluing it to the name would
        # carry it into anything that sorts or searches.
        #
        # The rating column is pinned to five rather than fitted to its
        # content (rxved's reasoning): fitted, it is five wide in a bank
        # somebody has rated and one wide in a bank they have not, so the
        # column changes shape over data that has nothing to do with it and
        # a row jumps sideways the moment it is rated. Five is
        # ``rating_cell``'s full width -- ``★★★★★``.
        for label, key, width in (
            ("♥", "fav", None),
            ("#", "num", None),
            ("name", "name", None),
            ("★", "rating", 5),
            ("PC", "pc", None),
            ("LSB", "lsb", None),
            ("MSB", "msb", None),
        ):
            slots.add_column(label, key=key, width=width)
        # Open on the bank that was on screen last time: the left pane's
        # cursor has to sit on it before anything else moves. The guard is
        # set first, so the *queued* first highlight -- Textual posts one
        # for the table's starting row and delivers it only after this
        # returns -- cannot refill General MIDI over the restored bank and
        # file row 0 as the place the user was.
        self._restoring = True
        self._remembered_bank = self._current_bank
        self._remembered_slot = self._saved_slot_cursor
        table.move_cursor(row=self._bank_ids.index(self._current_bank))
        self._fill(self._current_bank)
        # The saved slot row, clamped to whatever this fill produced --
        # one use only.
        saved_slot_cursor = self._saved_slot_cursor
        self._saved_slot_cursor = None
        if saved_slot_cursor is not None and self._current:
            slots.move_cursor(row=min(saved_slot_cursor, len(self._current) - 1))
            slots.focus()
        else:
            table.focus()
        # A focus change can reset the slot table's visual cursor, and a
        # queued highlight may have moved the bank, so the remembered bank,
        # cursor and guard are all put right once the dust settles -- the
        # shape rxved applies its cursor after, extended to the bank.
        self.set_timer(0.1, self._finish_restore)
        printed = len(self.catalog)
        if printed and applied:
            self.notify_status(
                f"{printed} names from the catalog · {applied} read from the unit"
            )
        elif printed:
            self.notify_status(f"{printed} names from the catalog")
        elif applied:
            # Not "no catalog": the unit supplied them, they are kept in
            # the sidecar, and saying otherwise read as "the read never
            # made it" on every startup (compare emorphed).
            self.notify_status(
                f"{applied} names read from the unit (no printed catalog)"
            )
        else:
            self.notify_status("no names yet -- press r to read the User bank")
        # Offering to scan is deferred: the panes should paint first, and a
        # dialog over a half-drawn screen reads as a fault. The check
        # itself also runs when the sidecar was full, which is why it is a
        # timer rather than a branch here.
        self.set_timer(0.6, self._maybe_offer_scan)

    def _finish_restore(self) -> None:
        """Put the remembered bank and row back once the dust settles.

        The first highlight a `DataTable` posts arrives after ``on_mount``
        returns, and if nothing guards it it refills General MIDI over the
        bank the restore just chose and records row 0 as the user's place.
        So the guard is lifted here, and the bank and cursor are re-asserted
        in the same callback: whatever the queued events did, this is the
        last word, and it runs on the main thread with nothing racing it.

        Best-effort by construction: the row may not exist any more (a
        filter was remembered with it), and a timer callback must not raise.
        """
        try:
            bank_table = self.query_one("#bank-table", DataTable)
            slot_table = self.query_one("#slot-table", DataTable)
        except LookupError:  # pragma: no cover - the app is shutting down
            self._restoring = False
            return
        if self._current_bank != self._remembered_bank:
            self._fill(self._remembered_bank)
            bank_table.move_cursor(row=self._bank_ids.index(self._remembered_bank))
        if self._remembered_slot is not None and self._current:
            slot_table.move_cursor(
                row=min(self._remembered_slot, len(self._current) - 1)
            )
        self._restoring = False
        self._schedule_auto_load()

    # --- filling ------------------------------------------------------------

    def _favorite_keys(self, bank_id: str) -> set:
        if self.favorites is None:
            return set()
        return self.favorites.keys_for_bank(bank_id)

    def _all_favourites(self) -> list[banks.Slot]:
        """Every favourite in every bank, in bank order then number.

        Built from the slots rather than from the favourites rows, so a row
        naming a bank this build does not know is skipped rather than
        breaking the list.
        """
        if self.favorites is None:
            return []
        wanted: dict[str, set[int]] = {}
        for favourite in self.favorites.all(order="bank"):
            wanted.setdefault(favourite.bank_id, set()).add(favourite.number)
        out: list[banks.Slot] = []
        for bank_id in banks.bank_ids():
            numbers = wanted.get(bank_id)
            if not numbers:
                continue
            out.extend(e for e in banks.slots(bank_id) if e.program_change in numbers)
        return out

    def _visible(self, bank_id: str) -> list[banks.Slot]:
        if self.view_mode == VIEW_ALL_FAVOURITES:
            entries = self._all_favourites()
        else:
            entries = banks.slots(bank_id)
            if self.view_mode == VIEW_BANK_FAVOURITES:
                marked = self._favorite_keys(bank_id)
                entries = [e for e in entries if e.program_change in marked]
        return self._by_rating(entries)

    def _by_rating(self, entries: list[banks.Slot]) -> list[banks.Slot]:
        """Keep the slots whose stored rating matches the filter.

        A slot nobody has favourited has rating 0, which is why the
        ``at_least`` form needs no special case: "at least 1" already
        excludes the unrated ones. ``stars == 0`` is the family's
        spelling of "any", though, so it disables the filter whatever
        ``at_least`` says -- and that is also the value the
        rating-filter dialog produces when it is cleared.
        """
        flt = self.rating_filter
        if flt is None or flt.stars == 0 or self.favorites is None:
            return entries
        out: list[banks.Slot] = []
        for entry in entries:
            favourite = self.favorites.get(entry.bank_id, entry.program_change)
            rating = favourite.rating if favourite is not None else 0
            if (rating >= flt.stars) if flt.at_least else (rating == flt.stars):
                out.append(entry)
        return out

    def _cursor_entry(self):
        """The row under the cursor, or None."""
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return None
        return self._current[row]

    # --- the send channel ---------------------------------------------------

    def _channel(self) -> int:
        return getattr(self.device, "channel", 0)

    def _set_channel(self, channel: int) -> None:
        """Change the channel selections are sent on, and remember it."""
        channel = max(0, min(15, channel))
        try:
            self.device.channel = channel
        except Exception:
            self.notify_status("this device has no settable channel", refused=True)
            return
        self._remember_channel(channel)
        self._update_subtitle()
        self.notify_status(f"sending on MIDI channel {channel + 1}")

    def _remember_channel(self, channel: int) -> None:
        """Save it for next time. Only OSError is swallowed."""
        path = self._config_path
        if path is None:
            return
        from nano import config

        try:
            config.save_channel(channel, path)
        except OSError:
            pass

    def _save_ui_state(  # noqa: PLR0913 -- keyword-only switches, one per key
        self,
        *,
        bank_index: Any = UNSET,
        slot_cursor: Any = UNSET,
        view_mode: Any = UNSET,
        mix_number: Any = UNSET,
        rating_stars: Any = UNSET,
        rating_at_least: Any = UNSET,
        scan_offer_dismissed: Any = UNSET,
        auto_load: Any = UNSET,
    ) -> None:
        """Persist where the user was and what the browser remembers.

        :data:`UNSET` forwards nothing, so saving the cursor leaves the
        bank position alone: the keys are saved individually and only the
        ones named matter this time. ``None`` is the family's "remove the
        key", and the rating filter spells a cleared filter that way --
        a stored ``0`` would be indistinguishable from "exactly zero
        stars" to the next reader.

        Only :class:`OSError` is swallowed -- a read-only directory or a
        full disk, where forgetting the position beats refusing to run. A
        programming error (a list where an int belongs) raises and is
        heard.
        """
        path = self._ui_state_path
        if path is None:
            return
        from nano import config as _cfg

        try:
            for key, value in (
                ("bank_index", bank_index),
                ("slot_cursor", slot_cursor),
                ("view_mode", view_mode),
                ("mix_number", mix_number),
                ("rating_stars", rating_stars),
                ("rating_at_least", rating_at_least),
                ("scan_offer_dismissed", scan_offer_dismissed),
                ("auto_load", auto_load),
            ):
                if value is UNSET:
                    continue
                _cfg.save_ui_state(key, value, path)
        except OSError:
            pass

    def action_channel_up(self) -> None:
        self._set_channel(self._channel() + 1)

    def action_channel_down(self) -> None:
        self._set_channel(self._channel() - 1)

    def action_pick_channel(self) -> None:
        def apply(text):
            if not text:
                return
            try:
                value = int(text)
            except ValueError:
                self.notify_status(f"{literal(text)!r} is not a number", refused=True)
                return
            if not 1 <= value <= 16:
                self.notify_status("MIDI channels are 1-16", refused=True)
                return
            self._set_channel(value - 1)

        self.push_screen(
            PromptScreen("MIDI channel (1-16):", str(self._channel() + 1)), apply
        )

    def action_toggle_favorite(self) -> None:  # noqa: C901, PLR0912
        """Mark or unmark the slot under the cursor. Sends no MIDI."""
        if self._current_bank == MIXES_BANK:
            self.notify_status("Mixes are not a program bank", refused=True)
            return
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return
        entry = self._current[row]
        # entry.bank_id, not self._current_bank. In the all-favourites view
        # the rows come from every bank while the bank pane sits on one of
        # them, so using the pane's bank favourited a slot the user was not
        # looking at and left the one they were. _fill has always read the
        # row's own bank; these did not.
        bank_id = entry.bank_id
        name = self.catalog.display_name(bank_id, entry.program_change)
        # Favorites.toggle, not remove-then-add: un-favouriting keeps
        # the row so a rating, tags, a note and the original date
        # survive being toggled off and on. As a delete followed by a
        # fresh add this destroyed all four, and this is one keystroke.
        now = self.favorites.toggle(bank_id, entry.program_change, name=name)
        needs_refill = False
        if self.memory is not None and bank_id == "USER":
            digest = self.memory.slot_digest("USER", entry.program_change)
            if digest is not None:
                if now:
                    marked = self.favorites.get("USER", entry.program_change)
                    remembered = self.memory.get(digest)
                    if marked is not None and (
                        marked.rating or marked.tags or marked.note
                    ):
                        self.memory.set_favourite(
                            digest,
                            True,
                            rating=marked.rating,
                            tags=marked.tags,
                            note=marked.note,
                        )
                    elif remembered is not None and (
                        remembered.rating or remembered.tags or remembered.note
                    ):
                        self.memory.set_favourite(digest, True)
                        self.favorites.add(
                            "USER",
                            entry.program_change,
                            name=name,
                            rating=remembered.rating,
                            tags=remembered.tags,
                            note=remembered.note,
                        )
                    else:
                        self.memory.set_favourite(digest, True)
                else:
                    self.memory.set_favourite(digest, False)
                    occurrences = self.memory.slots_for(digest)
                    for slot_bank, slot_number in occurrences:
                        self.favorites.remove(slot_bank, slot_number)
                    needs_refill = len(occurrences) > 1
        self.notify_status(f"{'favourited' if now else 'unfavourited'} {literal(name)}")

        # In VIEW_ALL mode (not favourites views), only update the favourite
        # cell to avoid refilling the entire table and losing scroll position.
        if self.view_mode == VIEW_ALL and not needs_refill:
            table = self.query_one("#slot-table", DataTable)
            new_marker = "[b]♥[/b]" if now else ""
            table.update_cell(entry.key, "fav", new_marker)
            self._refresh_bank_fav_count(bank_id)
        else:
            # In favourites views (VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES),
            # we need to refresh the whole table because the visible rows may
            # change (add/remove rows), so do the existing behaviour.
            self._refill_keeping_place()
            self._refresh_bank_fav_count(bank_id)

    def _favourite_under_cursor(self):
        """The favourite row for the slot under the cursor, if there is one.

        Tags and notes hang off a favourite, so there is nothing to attach
        them to until `f` has been pressed. Saying so is better than
        silently creating one: the user asked to annotate, not to favourite.
        """
        entry = self._cursor_entry()
        if entry is None or self.favorites is None or self._current_bank == MIXES_BANK:
            return None, None
        # The row's bank, for the reason action_toggle_favorite gives: in
        # the all-favourites view a tag or a note written against the bank
        # pane's bank lands on a different slot than the one on screen.
        bank_id = entry.bank_id
        number = entry.program_change
        return (bank_id, number), self.favorites.get(bank_id, number)

    def action_edit_tags(self) -> None:
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status("not a favourite yet -- press f first", refused=True)
            return

        def apply(value):
            if value is None:
                return
            self.favorites.set_tags(where[0], where[1], value)
            self._refill_keeping_place()
            self.notify_status("tags set")

        self.push_screen(PromptScreen("Tags (comma separated):", existing.tags), apply)

    def action_edit_note(self) -> None:
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status("not a favourite yet -- press f first", refused=True)
            return

        def apply(value):
            if value is None:
                return
            self.favorites.set_note(where[0], where[1], value)
            self._refill_keeping_place()
            self.notify_status("note set")

        self.push_screen(PromptScreen("Note:", existing.note), apply)

    def action_edit_rating(self) -> None:
        """Rate the slot under the cursor, 0 to 5.

        ``Favorites.set_rating`` routes through ``add``, so it *creates*
        the favourite when the slot is not one -- the library documents
        that and pins it with a test. This is therefore the one
        annotation key that does not ask for `f` first: the user asked to
        rate, and the row becomes a favourite as the documented
        consequence of rating it.

        The rating is looked up even when no row is favourited yet, so
        the dialog opens on 0 rather than refusing.
        """
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        entry = self._cursor_entry()
        if entry is None:
            return
        existing = self.favorites.get(entry.bank_id, entry.program_change)
        current = existing.rating if existing is not None else 0
        # The family's choice UI rather than a typed number: 0-5 is a
        # short closed list, and `*` is never used for stars here -- it
        # already means "the name disagrees with the catalog".
        choices = ["no rating" if stars == 0 else "★" * stars for stars in range(6)]

        def apply(value: int | None) -> None:
            if value is None:
                return
            self.favorites.set_rating(entry.bank_id, entry.program_change, value)
            self._refill_keeping_place()
            self._refresh_bank_fav_count(entry.bank_id)
            self.notify_status(
                f"{entry.display} rated {value}"
                if value
                else f"{entry.display} rating cleared"
            )

        self.push_screen(
            ChoiceScreen(f"Rating for {entry.display}", choices, current), apply
        )

    def action_rating_filter(self) -> None:
        """Choose which star ratings the slot pane shows. Sends no MIDI."""
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        current = self.rating_filter or RatingFilter(stars=0, at_least=False)

        def apply(value: RatingFilter | None) -> None:
            if value is None:
                return
            # ``(0, at_least=True)`` is the dialog's own "cleared": the
            # family spells that as a filter of any stars, and so does
            # ``_by_rating``. Storing None keeps a cleared filter out of
            # the ui-state file instead of writing a 0 that a reader
            # would have to interpret.
            if value.stars == 0 and value.at_least:
                self.rating_filter = None
            else:
                self.rating_filter = value
            self._save_rating_filter()
            self._refill_keeping_place()
            flt = self.rating_filter
            if flt is None:
                self.notify_status("rating filter cleared")
            else:
                how = "at least" if flt.at_least else "exactly"
                self.notify_status(f"rating filter: {how} {flt.stars} star(s)")

        self.push_screen(RatingFilterScreen(current), apply)

    def _save_rating_filter(self) -> None:
        """Remember the filter, or remove both keys when it is cleared."""
        flt = self.rating_filter
        self._save_ui_state(
            rating_stars=None if flt is None else flt.stars,
            rating_at_least=None if flt is None else bool(flt.at_least),
        )

    def action_cycle_favorites(self) -> None:
        """Step: all slots -> this bank's favourites -> every favourite.

        Always exactly three steps, even when a view is empty: skipping one
        to be helpful makes a keypress land somewhere different depending on
        what happens to be favourited.
        """
        if self._current_bank == MIXES_BANK:
            self.notify_status("Mixes are not a program bank", refused=True)
            return
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        index = VIEW_CYCLE.index(self.view_mode)
        self.view_mode = VIEW_CYCLE[(index + 1) % len(VIEW_CYCLE)]
        self._save_ui_state(view_mode=self.view_mode)
        self._refill_keeping_place()
        shown = len(self._current)
        if self.view_mode == VIEW_ALL:
            self.notify_status(VIEW_LABELS[self.view_mode])
        elif not shown:
            where = (
                "this bank" if self.view_mode == VIEW_BANK_FAVOURITES else "any bank"
            )
            self.notify_status(
                f"{VIEW_LABELS[self.view_mode]} - nothing favourited in {where} yet"
            )
        else:
            self.notify_status(f"{VIEW_LABELS[self.view_mode]} - {shown}")

    def _refill_keeping_place(self) -> None:
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row or 0
        self._fill(self._current_bank)
        if self._current:
            table.move_cursor(row=min(row, len(self._current) - 1))

    def _refresh_bank_fav_count(self, bank_id: str) -> None:
        """Update the favourite counter in the bank-table column for *bank_id*."""
        table = self.query_one("#bank-table", DataTable)
        marked = len(self._favorite_keys(bank_id))
        table.update_cell(bank_id, "fav", str(marked) if marked else "")

    def _fill(self, bank_id: str) -> None:
        if bank_id == MIXES_BANK:
            self._fill_mixes()
            return
        table = self.query_one("#slot-table", DataTable)
        self._current_bank = bank_id
        self._current = self._visible(bank_id)
        # One query for the heart set and the ratings together, rather
        # than a `keys_for_bank()` and a `get()` per row: a bank is over a
        # hundred rows, and the store is behind a lock. Membership in the
        # whole set is also the right question in the all-favourites view,
        # where the rows come from every bank while the pane sits on one.
        everything = self.favorites.all() if self.favorites is not None else []
        favorited = {favourite.key for favourite in everything}
        ratings = {favourite.key: favourite.rating for favourite in everything}
        self._filling = True
        try:
            table.clear()
            for entry in self._current:
                # Escaped before the project's own [b]/[dim] goes around
                # it: a name is unit-supplied and user-editable, and an
                # unclosed markup tag in one kills the pane for all of
                # them. The markup is this project's, so it is the one
                # side of this f-string that is not escaped.
                name = literal(
                    self.catalog.display_name(entry.bank_id, entry.program_change)
                )
                if self.catalog.differs(entry.bank_id, entry.program_change):
                    shown = f"[b]{name}[/b] [dim]*[/dim]"
                elif self.catalog.is_live(entry.bank_id, entry.program_change):
                    shown = f"[b]{name}[/b]"
                else:
                    shown = name
                table.add_row(
                    "[b]♥[/b]" if entry.key in favorited else "",
                    entry.display,
                    shown,
                    rating_cell(ratings.get(entry.key, 0)),
                    str(entry.program_change),
                    str(entry.lsb),
                    str(entry.msb),
                    key=entry.key,
                )
        finally:
            self._filling = False
        self._detail(0)
        self._update_subtitle()

    def _fill_mixes(self) -> None:
        """Fill the right pane with Mixes 000-099, names once read."""
        table = self.query_one("#slot-table", DataTable)
        self._current_bank = MIXES_BANK
        self._current = list(MIX_SLOTS)
        self._filling = True
        try:
            table.clear()
            for entry in self._current:
                name = literal(
                    self._mix_names.get(entry.number, f"Mix {entry.number:03d}")
                )
                table.add_row(
                    "",
                    f"{entry.number:03d}",
                    name,
                    "",
                    str(entry.number),
                    "",
                    "",
                    key=entry.key,
                )
        finally:
            self._filling = False
        self._detail(0)
        self._update_subtitle()
        self._ensure_mix_names()

    def _ensure_mix_names(self) -> None:
        """Read the 100 mix names once, in a worker, when Mixes is shown."""
        if self._mix_names_loaded or self._mix_names_reading:
            return
        if self._busy:
            return
        if not self._exchange.acquire(blocking=False):
            return
        self._mix_names_reading = True
        self.notify_status("reading mix names...")
        self._mix_names_worker()

    @work(thread=True)
    def _mix_names_worker(self) -> None:
        """**MIDI only.** Read every mix name; the main thread refills."""
        failure: BaseException | None = None
        names: dict[int, str] = {}
        try:
            with self._busy_gate, self._lock:
                names = self.device.read_mix_names(
                    on_progress=lambda done, total: self.call_from_thread(
                        self._mix_names_progress, done, total
                    )
                )
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self._mix_names_failed, failure)
            return
        self.call_from_thread(self._mix_names_ready, names)

    def _mix_names_progress(self, done: int, total: int) -> None:
        self.notify_status(f"reading mix names {done}/{total}")

    def _mix_names_ready(self, names: dict[int, str]) -> None:
        self._mix_names = names
        self._mix_names_loaded = True
        self._mix_names_reading = False
        if self._current_bank == MIXES_BANK:
            self._refill_keeping_place()
        self.notify_status(f"read {len(names)} mix names")

    def _mix_names_failed(self, failure: BaseException) -> None:
        self._mix_names_reading = False
        self.notify_status(f"mixes: {failure}", refused=True)

    def _detail(self, row: int) -> None:
        if not self._current or row >= len(self._current):
            self.query_one("#detail", Static).update("")
            return
        entry = self._current[row]
        if entry.bank_id == MIXES_BANK:
            name = literal(self._mix_names.get(entry.number, f"Mix {entry.number:03d}"))
            self.query_one("#detail", Static).update(
                f"[b]{entry.display}[/b]  {name}   "
                f"[dim]Mix mode · Program Change {entry.program_change}[/dim]"
            )
            return
        name = literal(self.catalog.display_name(entry.bank_id, entry.program_change))
        where = "front panel and MIDI" if entry.bank.front_panel else "MIDI only"
        source = (
            "read from the unit"
            if self.catalog.is_live(entry.bank_id, entry.program_change)
            else (
                "ROM, from the catalog" if not entry.bank.readable else "not read yet"
            )
        )
        silent = ""
        if (entry.bank_id, entry.number) == banks.SILENT_PROGRAM:
            silent = (
                "   [dim]this one is the hardwired silent program; "
                "selecting it mutes the channel[/dim]"
            )
        self.query_one("#detail", Static).update(
            f"[b]{entry.display}[/b]  {name}   [dim]{entry.category}[/dim]\n"
            f"Bank Select (CC0) [b]{entry.msb}[/b] · LSB (CC32) "
            f"[b]{entry.lsb}[/b] · PC [b]{entry.program_change}[/b] · "
            f"{where} · {source}{silent}"
        )

    def notify_status(self, message: str, *, refused: bool = False) -> None:
        """Say the last thing; a refusal goes red and bold.

        The family's shape (rxved): the widget carries a ``refused`` class
        rather than a text prefix, so a refusal is a red bar the eye cannot
        miss instead of another grey status line.
        """
        status = self.query_one("#status", Static)
        status.update(message)
        status.set_class(refused, "refused")

    def _update_subtitle(self) -> None:
        """Say in the header which pane this is and which channel sends on.

        The family puts the same line in the Header's subtitle, and for the
        same reason: the send channel is the one piece of state that is
        always in play and never asked about. ``[`` and ``]`` move it
        silently, and a Bank Select plus Program Change sent on the wrong
        channel is silent too -- the unit just never hears it, or hears it
        on a channel nobody is listening to. Showing it makes both visible
        at a glance.

        The count carries its denominator -- "12" alone reads as a small
        bank, "12 of 128" reads as part of one -- which is what answers
        "why is this list shorter than I remember" after a restart that
        brought a rating filter back.
        """
        if self._current_bank == MIXES_BANK:
            self.sub_title = (
                f"Mixes — {len(self._current)}   ·   ch {self._channel() + 1}"
            )
            return
        entry = banks.bank(self._current_bank)
        shown = len(self._current)
        # The denominator is the same view with the rating filter lifted:
        # the filter is the only thing that can quietly take rows away, so
        # the two numbers say exactly how many it took.
        saved = self.rating_filter
        self.rating_filter = None
        try:
            total = len(self._visible(self._current_bank))
        finally:
            self.rating_filter = saved
        counted = f"{shown} of {total}" if shown != total else f"{shown}"

        if self.view_mode == VIEW_ALL_FAVOURITES:
            what = f"every favourite — {counted}"
        elif self.view_mode == VIEW_BANK_FAVOURITES:
            plural = "" if shown == 1 else "s"
            what = f"{entry.label} — {counted} favourite{plural}"
        else:
            plural = "" if shown == 1 else "s"
            what = f"{entry.label} — {counted} program{plural}"

        filters = ""
        if self.rating_filter is not None:
            stars = "★" * self.rating_filter.stars or "any"
            sign = "≥" if self.rating_filter.at_least else "="
            filters = f"{stars} {sign}   "
        self.sub_title = f"{filters}{what}   ·   ch {self._channel() + 1}"

    # --- navigation ---------------------------------------------------------

    def on_data_table_row_highlighted(self, event) -> None:
        if self._filling:
            return
        if event.data_table.id == "bank-table":
            row = event.cursor_row
            if 0 <= row < len(self._bank_ids):
                bank_id = self._bank_ids[row]
                # Idempotent on purpose. ``_filling`` cannot guard this --
                # the event is delivered after the flag is cleared -- so
                # the handler has to be safe to receive for the bank it
                # is already showing. Moving the cursor never triggers it
                # for a row already shown, and a stale queued event for a
                # bank that was showing a moment ago must not refill the
                # pane over a newer fill. While the startup restore is
                # still settling, no highlight is trusted at all: the
                # restore's own callback has the last word.
                if bank_id != self._current_bank and not self._restoring:
                    self._fill(bank_id)
                    self._save_ui_state(bank_index=row)
        elif event.data_table.id == "slot-table":
            self._detail(event.cursor_row)
            # Only save the slot cursor when the slot table is focused --
            # the user is actively navigating. Programmatic cursor moves
            # during startup (while the bank pane has focus) must not
            # overwrite the saved position they are busy restoring, and
            # neither must a queued highlight while the restore settles.
            if event.data_table.has_focus and not self._restoring:
                self._save_ui_state(slot_cursor=event.cursor_row)
                self._schedule_auto_load()

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a slot. It arrives here, not as a binding."""
        if event.data_table.id == "slot-table":
            self.action_select()

    def action_switch_pane(self) -> None:
        left = self.query_one("#bank-table", DataTable)
        if left.has_focus:
            self.action_focus_right_pane()
        else:
            self.action_focus_left_pane()

    def action_focus_left_pane(self) -> None:
        if self._auto_load_timer is not None:
            self._auto_load_timer.stop()
            self._auto_load_timer = None
        self.query_one("#bank-table", DataTable).focus()

    def action_focus_right_pane(self) -> None:
        self.query_one("#slot-table", DataTable).focus()
        self._schedule_auto_load()

    def action_toggle_auto_load(self) -> None:
        """Turn cursor-follow selection on or off; remember the choice."""
        self._auto_load = not self._auto_load
        self._save_ui_state(auto_load=self._auto_load)
        if not self._auto_load and self._auto_load_timer is not None:
            self._auto_load_timer.stop()
            self._auto_load_timer = None
        state = "on" if self._auto_load else "off"
        self.notify_status(f"auto-load {state}")
        if self._auto_load:
            self._schedule_auto_load()

    def _schedule_auto_load(self) -> None:
        """Send the focused preset after a short pause, not on every repeat."""
        if not self._auto_load or self._restoring or self._filling:
            return
        slots = self.query_one("#slot-table", DataTable)
        if not slots.has_focus:
            return
        if self._auto_load_timer is not None:
            self._auto_load_timer.stop()
        self._auto_load_timer = self.set_timer(0.12, self._auto_load_focused)

    def _auto_load_focused(self) -> None:
        self._auto_load_timer = None
        if not self._auto_load or self._restoring or self._filling:
            return
        slots = self.query_one("#slot-table", DataTable)
        if not slots.has_focus:
            return
        row = slots.cursor_row
        if not 0 <= row < len(self._current):
            return
        if self._busy:
            return
        if not self._exchange.acquire(blocking=False):
            return
        self._start_selection(row)

    # --- operations ---------------------------------------------------------

    def action_select(self) -> None:
        if self._auto_load_timer is not None:
            self._auto_load_timer.stop()
            self._auto_load_timer = None
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not 0 <= row < len(self._current):
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        # The exchange is claimed here, on the main thread, before any
        # worker exists: a @work(thread=True) method returns at once, so
        # two quick presses both passed every check run on their own
        # thread -- two Program Changes from one intent, and for `r` two
        # bulk requests back-to-back, which is the traffic that draws
        # "data format error" from this unit (item 1). The worker
        # releases the exchange in a ``finally``; entering the busy gate
        # is what marks the exchange in progress for an idle close.
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._start_selection(row)

    def _start_selection(self, row: int) -> None:
        """Send one selection, changing mode first when the track says so."""
        if self._current_bank == MIXES_BANK:
            self._select_mix_worker(row, self._unit_mode != "mix")
            return
        self._select_worker(self._current[row], self._unit_mode != "program")

    def _record_unit_mode(self, mode: str) -> None:
        """Remember the mode this app last sent; the unit cannot report it."""
        self._unit_mode = mode
        self._last_mode_sent = mode == "mix"

    @work(thread=True)
    def _select_worker(self, entry: banks.Slot, mode_change: bool = False) -> None:
        """**MIDI only.** The caller claimed the exchange; this frees it."""
        failure: BaseException | None = None
        mode_sent = False
        try:
            with self._busy_gate, self._lock:
                if mode_change:
                    self.device.mode_select(False)
                    mode_sent = True
                self.device.select(entry)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if mode_sent:
            self.call_from_thread(self._record_unit_mode, "program")
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"select: {failure}", refused=True
            )
            return
        prefix = "selected Program mode, then " if mode_sent else ""
        self.call_from_thread(
            self.notify_status,
            f"{prefix}selected {entry.display} — Bank Select "
            f"{entry.bank.select} then Program Change {entry.program_change} "
            f"on channel {self.device.channel + 1}",
        )

    @work(thread=True)
    def _select_mix_worker(self, number: int, mode_change: bool = False) -> None:
        """**MIDI only.** Mix mode first if needed, then Program Change."""
        failure: BaseException | None = None
        mode_sent = False
        try:
            with self._busy_gate, self._lock:
                if mode_change:
                    self.device.mode_select(True)
                    mode_sent = True
                self.device.select_mix(number)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if mode_sent:
            self.call_from_thread(self._record_unit_mode, "mix")
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"select mix: {failure}", refused=True
            )
            return
        prefix = "selected Mix mode, then " if mode_sent else ""
        self.call_from_thread(
            self.notify_status,
            f"{prefix}selected Mixes {number:03d} — Program Change {number} "
            f"on channel {self.device.channel + 1}",
        )

    def action_read_names(self) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if self._current_bank == MIXES_BANK:
            self._mix_names_loaded = False
            self._ensure_mix_names()
            return
        entry = banks.bank(self._current_bank)
        if not entry.readable:
            self.notify_status(
                f"{entry.label} is ROM and the protocol has no request for "
                f"it; only the User bank can be read back",
                refused=True,
            )
            return
        # Main thread; see action_select for why it is claimed here.
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._read_worker(self._current_bank)

    @work(thread=True)
    def _read_worker(self, bank_id: str) -> None:
        """**MIDI only** -- the catalog is updated on the main thread.

        128 separate requests, not one bulk dump. The only bulk request
        this protocol has returns everything the instrument holds, about
        79 kB of it, and nearly all of that is data this program does not
        use. The caller claimed the exchange; this frees it.
        """

        def progress(done, total):
            self.call_from_thread(
                self.notify_status, f"reading the User bank, {done}/{total} (silent)..."
            )

        failure: BaseException | None = None
        names: dict[int, str] | None = None
        try:
            with self._busy_gate, self._lock:
                names = self.device.read_program_names(on_progress=progress)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self.notify_status, f"read: {failure}", refused=True)
            return
        if names is None:  # pragma: no cover -- the failure path caught it
            return
        self.call_from_thread(self._adopt, bank_id, names)

    def _adopt(self, bank_id: str, names: dict[int, str]) -> None:
        for program_change, name in names.items():
            self.catalog.set_live_name(bank_id, program_change, name)
        differing = sum(1 for pc in names if self.catalog.differs(bank_id, pc))
        # The same names must be here next launch without one read: they
        # are kept in the sidecar beside the catalog. Only OSError is
        # swallowed -- a read-only directory keeps the session's names in
        # the catalog above and does not end the program over a cache.
        try:
            livenames.save(
                livenames.path_for(self._catalog_path),
                {livenames.key(bank_id, pc): name for pc, name in names.items()},
            )
        except OSError:
            pass
        # Rows already favourited keep the name they were added with, so a
        # favourite named from the manual stays stale forever unless
        # something re-asks the store for its names. This runs on the main
        # thread, where ``_adopt`` always runs: the favourites database is
        # sqlite and refuses cross-thread use.
        if self.favorites is not None:
            self.favorites.refresh_names(self.catalog.live_name)
        if bank_id == self._current_bank:
            self._fill(bank_id)
        self.notify_status(
            f"read {len(names)} names from {bank_id}"
            + (f"; {differing} differ from the catalog" if differing else "")
        )

    # --- the write path -----------------------------------------------------
    #
    # Four rules, each the family's and each the reason a step here exists:
    #
    # * the gate decides whether anything is sent, and it is asked on the
    #   main thread before a worker exists;
    # * the destination is read in full before a byte is written, and that
    #   read is the backup -- if it fails, nothing is written;
    # * the store is verified by reading the record back and comparing it,
    #   because this unit answers a store with silence either way;
    # * only an agreed read-back is recorded for undo, so `z` can never
    #   "restore" a write the unit refused.

    def action_toggle_write_gate(self) -> None:
        """Arm or lock the fence in front of every write. Sends nothing."""
        self._write_gate.toggle()
        self.notify_status(self._write_gate.describe())

    def _undo_gate(self) -> str | None:
        """Refuse undo while an exchange is in flight, in one word."""
        return "busy" if self._busy else None

    def _undo_status(self, message: str) -> None:
        """The undo log's sentence for the status bar."""
        self.notify_status(message)

    def _undo_apply(self, record: Record) -> bool:
        """The synchronous door, deliberately not used.

        :meth:`_undo` takes the ``plan``/``settle`` door because the re-send
        belongs on a worker: doing it here would block the interface for a
        round trip. The hook is still passed to :class:`UndoLog` because the
        library refuses to undo a non-empty log without one -- and if some
        future caller reaches ``undo()`` instead, raising is the honest
        answer: nothing was sent, so the entry must stay on the log.
        """
        raise RuntimeError(
            "undo runs on a worker here; use action_undo, not UndoLog.undo"
        )

    def action_undo(self) -> None:
        self._undo(1)

    def action_undo_all(self) -> None:
        self._undo(None)

    def _undo(self, count: int | None) -> None:
        """Take a plan on the main thread, then re-send it on a worker."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        wanted = len(self._undo_log) if count is None else count
        taken = self._undo_log.plan(wanted)
        if not taken:
            refusal = self._undo_log.last_refusal
            if refusal is not None:
                self.notify_status(refusal, refused=True)
            else:
                self.notify_status("nothing to undo")
            return
        # Claimed on the main thread, before the worker exists, as every
        # other MIDI action is. If the claim loses a race the plan is put
        # back: nothing was sent, so the entries are still what the unit
        # holds.
        if not self._exchange.acquire(blocking=False):
            for record in reversed(taken):
                self._undo_log.push(record)
            self.notify_status("busy", refused=True)
            return
        self._undo_worker(taken)

    def _rewrite(
        self,
        edit: EditRecord | MixEditRecord | EffectsEditRecord | GlobalEditRecord,
    ) -> bytes:
        """Re-send one edit's previous bytes; return what the unit read back.

        Four kinds, one door: a program store names a user slot, a mix
        names one of the hundred mixes, effects name one of the 128 patches,
        and the global set has no number. The worker below reads back through
        the same kind it wrote, so an undo of a mix can never be verified
        against a program slot.
        """
        if isinstance(edit, MixEditRecord):
            self.device.write_mix(edit.number, edit.previous)
            return self.device.read_mix(edit.number)
        if isinstance(edit, EffectsEditRecord):
            self.device.write_effects(edit.number, edit.previous)
            return self.device.read_effects(edit.number)
        if isinstance(edit, GlobalEditRecord):
            self.device.write_global(edit.previous)
            return self.device.read_global()
        self.device.write_program(edit.number, edit.previous)
        return self.device.read_program(edit.number)

    @work(thread=True)
    def _undo_worker(self, records: list[Record]) -> None:
        """**MIDI only.** Re-send each previous record and read it back.

        A record that cannot be re-sent, or whose read-back disagrees, is a
        ``False`` in the results; ``_undo_done`` puts it back on the log so
        the next `z` can try again rather than pretending it is restored.
        """
        results: list[bool] = []
        sentences: list[str] = []
        try:
            with self._busy_gate, self._lock:
                for i in range(len(records)):
                    record = records[i]
                    edit = record.payload
                    if isinstance(edit, (ImportRecord, RestoreRecord)):
                        failed_edits: list = []
                        detail_sentences: list[str] = []
                        for item in reversed(edit.edits):
                            try:
                                read_back = self._rewrite(item)
                            except _BRIDGE_ERRORS as exc:
                                failed_edits.append(item)
                                detail_sentences.append(f"{item.label}: {exc}")
                                continue
                            if verify.mismatches(item.previous, read_back):
                                failed_edits.append(item)
                                detail_sentences.append(
                                    verify.describe(
                                        item.previous,
                                        read_back,
                                        what=item.label,
                                    )
                                )
                        if failed_edits:
                            reduced = type(edit)(edits=tuple(failed_edits))
                            records[i] = Record(edit.label, reduced)
                            results.append(False)
                            sentences.append(", ".join(detail_sentences))
                            continue
                        results.append(True)
                        sentences.append("")
                        continue
                    if not isinstance(
                        edit,
                        (
                            EditRecord,
                            MixEditRecord,
                            EffectsEditRecord,
                            GlobalEditRecord,
                        ),
                    ):
                        results.append(False)
                        sentences.append(f"{record.label}: not an edit record")
                        continue
                    try:
                        read_back = self._rewrite(edit)
                    except _BRIDGE_ERRORS as exc:
                        results.append(False)
                        sentences.append(f"{edit.label}: {exc}")
                        continue
                    agreed = not verify.mismatches(edit.previous, read_back)
                    results.append(agreed)
                    if not agreed:
                        sentences.append(
                            verify.describe(
                                edit.previous,
                                read_back,
                                what=edit.label,
                            )
                        )
        finally:
            self._exchange.release()
        self.call_from_thread(self._undo_done, records, results, sentences)

    def _undo_done(
        self,
        records: list[Record],
        results: list[bool],
        sentences: list[str],
    ) -> None:
        """Report the batch on the main thread, and keep what did not land."""
        summary = self._undo_log.settle(results)
        failed = [record for record, ok in zip(records, results, strict=True) if not ok]
        # Oldest first again, so the log still describes the order the
        # changes happened in -- not the newest-first order they were tried.
        for record in reversed(failed):
            self._undo_log.push(record)
        if failed:
            detail = (
                "; ".join(sentence for sentence in sentences if sentence)
                or "the unit refused it"
            )
            self.notify_status(f"{summary}; {detail}", refused=True)
            return
        for record in records:
            edit = record.payload
            if isinstance(edit, EditRecord):
                self.catalog.set_live_name("USER", edit.number, edit.name)
                self._bind_memory_slot(edit.number, edit.previous)
            elif isinstance(edit, (ImportRecord, RestoreRecord)):
                for item in edit.edits:
                    if isinstance(item, EditRecord):
                        self.catalog.set_live_name("USER", item.number, item.name)
                        self._bind_memory_slot(item.number, item.previous)
        if self._current_bank == "USER":
            self._refill_keeping_place()

    def action_edit_program(self) -> None:  # noqa: PLR0911
        """Read the User program under the cursor, then open the editor.

        The gate is asked **first**, before the cursor is even read: a
        locked gate means the key does nothing at all, and the refusal names
        the gate. Program 127 is refused next -- it is hardwired silent and
        the unit will not take a store for it -- and a ROM bank after that,
        since only the User bank can be read back.
        """
        if self._current_bank == MIXES_BANK:
            self._open_mix_focused()
            return
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        entry = self._cursor_entry()
        if entry is None:
            return
        if (entry.bank_id, entry.number) == banks.SILENT_PROGRAM:
            self.notify_status(
                f"{entry.display} is the hardwired silent program and "
                f"cannot be changed",
                refused=True,
            )
            return
        if not entry.bank.readable:
            self.notify_status(
                f"{entry.display} is ROM; only the User bank can be edited",
                refused=True,
            )
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._edit_worker(entry)

    @work(thread=True)
    def _edit_worker(self, entry: banks.Slot) -> None:
        """**MIDI only.** One program read; the modal is opened on the main
        thread. The caller claimed the exchange; this frees it."""
        failure: BaseException | None = None
        record: bytes | None = None
        try:
            with self._busy_gate, self._lock:
                record = self.device.read_program(entry.number)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self.notify_status, f"edit: {failure}", refused=True)
            return
        if record is None:  # pragma: no cover -- the failure path caught it
            return
        self.call_from_thread(self._open_editor, entry, record)

    def _open_editor(self, entry: banks.Slot, record: bytes) -> None:
        """Show the modal. Main thread; sends nothing."""
        editor = ProgramEditor(entry.number, record)
        self.push_screen(
            EditorScreen(
                editor,
                slot=entry.display,
                replaced=rec.program_name(editor.original).rstrip(),
            ),
            lambda new: self._edited(entry, new),
        )

    def _edited(self, entry: banks.Slot, record: bytes | None) -> None:
        """A fired editor's record, on the main thread. Sends nothing yet."""
        if record is None:
            return
        # Asked again, and not only at `e`: the gate can be locked while the
        # modal is open, and the last answer is the one that decides.
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if (entry.bank_id, entry.number) == banks.SILENT_PROGRAM:
            self.notify_status(
                f"{entry.display} is the hardwired silent program and "
                f"cannot be changed",
                refused=True,
            )
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._store_worker(entry, record)

    @work(thread=True)
    def _store_worker(self, entry: banks.Slot, record: bytes) -> None:
        """**MIDI only**, plus one backup file, which is the point of it.

        The five steps are the family's and the order is not negotiable:

        1. read the destination in full -- if it cannot be read, no store is
           sent, because a write that cannot be undone is not performed;
        2. save what was there, once per slot per session, and name the file;
        3. send the store;
        4. read the record back and compare it byte for byte;
        5. hand the previous bytes to the main thread, which records them
           for undo only if step 4 agreed.

        ``stage`` says where a failure happened: before the store it means
        nothing was written, and saying "nothing was written" is what keeps
        a failed backup from looking like a failed write.
        """
        from nano import backup as bk

        previous: bytes | None = None
        read_back: bytes | None = None
        path: str | None = None
        failure: BaseException | None = None
        stage = "read"
        try:
            with self._busy_gate, self._lock:
                previous = self.device.read_program(entry.number)
                if entry.key not in self._backed_up:
                    stage = "backup"
                    name = rec.program_name(previous).rstrip()
                    path = bk.save(
                        entry.key,
                        kind="program",
                        name=name,
                        blocks={"program": previous},
                    )
                    self._backed_up.add(entry.key)
                stage = "write"
                self.device.write_program(entry.number, record)
                stage = "read back"
                read_back = self.device.read_program(entry.number)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._store_done, entry, record, previous, path, read_back, failure, stage
        )

    def _adopt_slot_favourite(self, number: int, digest: str) -> None:
        """Carry an existing slot favourite into a memory entry, lazily.

        The memory's own annotations win when it already has any. Otherwise
        the active slot rows already bound to this digest are the evidence;
        an earliest-added row wins deterministically, and a blank row only
        establishes the content-level favourite flag. No record is read
        here: this is the first-seen path, not a bank scan.
        """
        if self.memory is None or self.favorites is None:
            return
        current = self.memory.get(digest)
        if current is not None and (current.rating or current.tags or current.note):
            self.memory.set_favourite(digest, True)
            return
        candidates: dict[tuple[str, int], Any] = {}
        for bank_id, slot in self.memory.slots_for(digest):
            favourite = self.favorites.get(bank_id, slot)
            if favourite is not None:
                candidates[(bank_id, slot)] = favourite
        favourite = self.favorites.get("USER", number)
        if favourite is not None:
            candidates[("USER", number)] = favourite
        if not candidates:
            return
        earliest = min(
            candidates.values(),
            key=lambda row: (row.added, row.bank_id, row.number),
        )
        if earliest.rating or earliest.tags or earliest.note:
            self.memory.set_favourite(
                digest,
                True,
                rating=earliest.rating,
                tags=earliest.tags,
                note=earliest.note,
            )
        else:
            self.memory.set_favourite(digest, True)

    def _bind_memory_slot(self, number: int, record: bytes) -> None:
        """Rebind a slot after an undo put ``record`` back."""
        if self.memory is None:
            return
        name = rec.program_name(record).rstrip()
        entry = self.memory.remember(record, name=name)
        self.memory.bind_slot("USER", number, entry.digest)

    def _remember_program(
        self,
        bank_id: str,
        number: int,
        record: bytes,
        *,
        manual: bool,
        previous: bytes | None = None,
    ) -> preset_memory.MemoryEntry | None:
        """Remember verified program bytes and restore their favourite mark.

        The content digest is the identity; the slot row is only the
        occurrence the browser paints. A remembered favourite activates that
        occurrence with the memory's annotations. Anything that is merely
        seen clears an old active mark, because the slot now holds different
        bytes. ``manual`` is documentation for the caller: a manual edit of
        a favourite carries the old annotations to the new digest before it
        reaches here.

        Lazy adoption only applies when the slot already holds the same
        content. Importing a different preset over a favourite slot is an
        overwrite, not a migration, and must clear the old mark.
        """
        if self.memory is None or bank_id != "USER":
            return None
        old_favourite = (
            self.favorites.get("USER", number) if self.favorites is not None else None
        )
        old_record = previous if previous else None
        old_digest = identity.digest(old_record) if old_record is not None else None
        name = rec.program_name(record).rstrip()
        entry = self.memory.remember(record, name=name)
        self.memory.bind_slot("USER", number, entry.digest)
        if (
            old_record is not None
            and old_digest is not None
            and old_digest != entry.digest
        ):
            # This import replaces different content. The old bytes were
            # favourite content if the slot still carried a mark; preserve
            # that identity before the slot mark is cleared, so re-importing
            # the old file can bring the heart back.
            if old_favourite is not None:
                old_name = rec.program_name(old_record).rstrip()
                self.memory.remember(old_record, name=old_name)
                self.memory.set_favourite(
                    old_digest,
                    True,
                    rating=old_favourite.rating,
                    tags=old_favourite.tags,
                    note=old_favourite.note,
                )
        else:
            self._adopt_slot_favourite(number, entry.digest)
        entry = self.memory.get(entry.digest) or entry
        if self.favorites is not None:
            if entry.favourite:
                self.favorites.add(
                    "USER",
                    number,
                    name=entry.name or name,
                    rating=entry.rating,
                    tags=entry.tags,
                    note=entry.note,
                )
            else:
                self.favorites.remove("USER", number)
        return entry

    def _store_done(  # noqa: PLR0913, PLR0917 -- one argument per worker fact
        self,
        entry: banks.Slot,
        record: bytes,
        previous: bytes | None,
        path: str | None,
        read_back: bytes | None,
        failure: BaseException | None,
        stage: str,
    ) -> None:
        """Main thread: report what happened, and log only what read back."""
        if failure is not None:
            if stage in ("read", "backup"):
                self.notify_status(
                    f"{stage}: {failure} — nothing was written", refused=True
                )
            else:
                self.notify_status(f"store: {failure}", refused=True)
            return
        if previous is None or read_back is None:  # pragma: no cover
            self.notify_status("store: no read-back; nothing was logged", refused=True)
            return
        where = f"; what was there is in {literal(path)}" if path else ""
        sentence = verify.describe(
            record, read_back, what=f"user program {entry.number:03d}"
        )
        if verify.mismatches(record, read_back):
            self.notify_status(f"{entry.display}: {sentence}{where}", refused=True)
            return
        # Agreed: the slot now holds what was sent, so the previous bytes are
        # a real undo entry rather than a guess about a write that "probably"
        # landed. The log lives on the main thread; this is that thread.
        old_name = rec.program_name(previous).rstrip()
        self._undo_log.push(
            Record(
                f"{entry.key}: {old_name}",
                EditRecord(number=entry.number, previous=previous, name=old_name),
            )
        )
        new_name = rec.program_name(record).rstrip()
        if self.memory is not None and entry.bank_id == "USER":
            old_favourite = (
                self.favorites.get("USER", entry.number)
                if self.favorites is not None
                else None
            )
            if old_favourite is not None:
                # The user edited a favourite. Both the old and the new bytes
                # stay remembered as favourite content; the slot occurrence
                # carries the new digest and keeps its annotations.
                old_entry = self.memory.remember(previous, name=old_name)
                self.memory.set_favourite(
                    old_entry.digest,
                    True,
                    rating=old_favourite.rating,
                    tags=old_favourite.tags,
                    note=old_favourite.note,
                )
                new_entry = self.memory.remember(record, name=new_name)
                self.memory.bind_slot("USER", entry.number, new_entry.digest)
                self.memory.set_favourite(
                    new_entry.digest,
                    True,
                    rating=old_favourite.rating,
                    tags=old_favourite.tags,
                    note=old_favourite.note,
                )
                if self.favorites is not None:
                    self.favorites.add(
                        "USER",
                        entry.number,
                        name=new_name,
                        rating=old_favourite.rating,
                        tags=old_favourite.tags,
                        note=old_favourite.note,
                    )
            else:
                self._remember_program(
                    entry.bank_id,
                    entry.number,
                    record,
                    manual=True,
                    previous=previous,
                )
            self._refresh_bank_fav_count("USER")
        self.catalog.set_live_name(entry.bank_id, entry.number, new_name)
        if entry.bank_id == self._current_bank:
            self._refill_keeping_place()
        self.notify_status(
            f"stored {entry.display} as {literal(new_name) or '(blank)'}; "
            f"{sentence}{where}"
        )

    # --- mixes, the global set, and the mode ---------------------------------

    @staticmethod
    def _mix_key(number: int) -> str:
        """What a mix is called in the backup set and the undo history.

        One spelling, used by the backup's once-per-session set, the file's
        slot label and the undo entry, so a reader of any of the three can
        match them up.
        """
        return f"mix:{number:03d}"

    def _open_mix_focused(self) -> None:
        """Read and edit the mix under the cursor in the Mixes pane."""
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        table = self.query_one("#slot-table", DataTable)
        row = table.cursor_row
        if not 0 <= row < banks.MIXES:
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._mix_number = row
        self._save_ui_state(mix_number=row)
        self._mix_read_worker(row)

    @work(thread=True)
    def _mix_read_worker(self, number: int) -> None:
        """**MIDI only.** One mix read; the modal opens on the main thread.

        The caller claimed the exchange; this frees it.
        """
        failure: BaseException | None = None
        record: bytes | None = None
        try:
            with self._busy_gate, self._lock:
                record = self.device.read_mix(number)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self.notify_status, f"mix: {failure}", refused=True)
            return
        if record is None:  # pragma: no cover -- the failure path caught it
            return
        self.call_from_thread(self._open_mix, number, record)

    def _open_mix(self, number: int, record: bytes) -> None:
        """Show the mix modal. Main thread; sends nothing."""
        self.push_screen(
            MixScreen(
                record,
                number=number,
                replaced=rec.mix_name(record).rstrip(),
                gate=self._write_gate,
            ),
            lambda new: self._mix_edited(number, new),
        )

    def _mix_edited(self, number: int, record: bytes | None) -> None:
        """A fired mix editor's record, on the main thread. Sends nothing yet."""
        if record is None:
            return
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._mix_store_worker(number, record)

    @work(thread=True)
    def _mix_store_worker(self, number: int, record: bytes) -> None:
        """**MIDI only**, plus one backup file, in the program store's order.

        1. read the mix in full -- unreadable means no store, because a
           write that cannot be undone is not performed;
        2. save what was there, once per mix per session, and name the file;
        3. send the store;
        4. read the mix back and compare it byte for byte;
        5. hand the previous bytes to the main thread, which records them
           for undo only if step 4 agreed.

        ``stage`` says where a failure happened, so a failed backup is never
        reported as a failed write.
        """
        from nano import backup as bk

        key = self._mix_key(number)
        previous: bytes | None = None
        read_back: bytes | None = None
        path: str | None = None
        failure: BaseException | None = None
        stage = "read"
        try:
            with self._busy_gate, self._lock:
                previous = self.device.read_mix(number)
                if key not in self._backed_up:
                    stage = "backup"
                    name = rec.mix_name(previous).rstrip()
                    path = bk.save(
                        key,
                        kind="mix",
                        name=name,
                        blocks={"mix": previous},
                    )
                    self._backed_up.add(key)
                stage = "write"
                self.device.write_mix(number, record)
                stage = "read back"
                read_back = self.device.read_mix(number)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._mix_store_done,
            number,
            record,
            previous,
            path,
            read_back,
            failure,
            stage,
        )

    def _mix_store_done(  # noqa: PLR0913, PLR0917 -- one argument per worker fact
        self,
        number: int,
        record: bytes,
        previous: bytes | None,
        path: str | None,
        read_back: bytes | None,
        failure: BaseException | None,
        stage: str,
    ) -> None:
        """Main thread: report what happened, and log only what read back."""
        key = self._mix_key(number)
        if failure is not None:
            if stage in ("read", "backup"):
                self.notify_status(
                    f"{stage}: {failure} — nothing was written", refused=True
                )
            else:
                self.notify_status(f"store: {failure}", refused=True)
            return
        if previous is None or read_back is None:  # pragma: no cover
            self.notify_status("store: no read-back; nothing was logged", refused=True)
            return
        where = f"; what was there is in {literal(path)}" if path else ""
        sentence = verify.describe(record, read_back, what=f"mix {number:03d}")
        if verify.mismatches(record, read_back):
            self.notify_status(f"{key}: {sentence}{where}", refused=True)
            return
        old_name = rec.mix_name(previous).rstrip()
        self._undo_log.push(
            Record(
                f"{key}: {old_name}",
                MixEditRecord(number=number, previous=previous, name=old_name),
            )
        )
        new_name = rec.mix_name(record).rstrip()
        self.notify_status(
            f"stored mix {number:03d} as {literal(new_name) or '(blank)'}; "
            f"{sentence}{where}"
        )

    def action_mode_select(self) -> None:
        """Put the unit in Program or Mix mode. **Changes what plays.**

        Not a store: nothing is written to memory, so there is nothing to
        back up and nothing to undo -- and the unit does not answer a Mode
        Select, so nothing here claims the switch happened. The dialog is
        where the second decision is made: `M` alone sends nothing, and
        the list names both modes because the message carries one rather
        than a yes/no. The current *unit* mode cannot be read back over
        this protocol; the pre-selected entry is only the one last asked
        for, and the dialog says so.
        """
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        current = 1 if self._last_mode_sent is None else int(self._last_mode_sent)
        self.push_screen(
            ChoiceScreen(
                "Mode select — this changes what plays and stores nothing",
                ["program mode", "mix mode"],
                current,
                status_message=(
                    "the unit does not report its current mode; Esc sends nothing"
                ),
            ),
            self._mode_chosen,
        )

    def _mode_chosen(self, choice: int | None) -> None:
        if choice is None:
            return
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        mix_mode = choice == 1
        self._last_mode_sent = mix_mode
        self._mode_worker(mix_mode)

    @work(thread=True)
    def _mode_worker(self, mix_mode: bool) -> None:
        """**MIDI only.** One Mode Select; nothing is stored or read back."""
        failure: BaseException | None = None
        try:
            with self._busy_gate, self._lock:
                self.device.mode_select(mix_mode)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self.notify_status, f"mode: {failure}", refused=True)
            return
        mode = "mix" if mix_mode else "program"
        self.call_from_thread(self._record_unit_mode, mode)
        self.call_from_thread(
            self.notify_status,
            f"sent Mode Select: {mode} mode — the unit does not acknowledge it, "
            f"and nothing was stored",
        )

    def action_edit_global(self) -> None:
        """Read the global set, then open its table-driven editor.

        The gate is asked first, as it is for `e`: a locked gate means the
        unit sees no traffic at all. A global read is one dump, so there is
        no slot to choose.
        """
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._global_read_worker()

    @work(thread=True)
    def _global_read_worker(self) -> None:
        """**MIDI only.** One global dump; the modal opens on the main thread."""
        failure: BaseException | None = None
        record: bytes | None = None
        try:
            with self._busy_gate, self._lock:
                record = self.device.read_global()
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"global: {failure}", refused=True
            )
            return
        if record is None:  # pragma: no cover -- the failure path caught it
            return
        self.call_from_thread(self._open_global, record)

    def _open_global(self, record: bytes) -> None:
        """Show the global modal. Main thread; sends nothing."""
        self.push_screen(
            GlobalScreen(GlobalEditor(record), gate=self._write_gate),
            self._global_edited,
        )

    def _global_edited(self, record: bytes | None) -> None:
        """A fired global editor's record, on the main thread."""
        if record is None:
            return
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._global_store_worker(record)

    @work(thread=True)
    def _global_store_worker(self, record: bytes) -> None:
        """**MIDI only**, plus one backup file, in the program store's order.

        The global set has no number, so the backup's slot is the word
        ``global``; there is one set, and a session writes one file for it.
        """
        from nano import backup as bk

        key = "global"
        previous: bytes | None = None
        read_back: bytes | None = None
        path: str | None = None
        failure: BaseException | None = None
        stage = "read"
        try:
            with self._busy_gate, self._lock:
                previous = self.device.read_global()
                if key not in self._backed_up:
                    stage = "backup"
                    path = bk.save(
                        key,
                        kind="global",
                        name="global settings",
                        blocks={"global": previous},
                    )
                    self._backed_up.add(key)
                stage = "write"
                self.device.write_global(record)
                stage = "read back"
                read_back = self.device.read_global()
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._global_store_done, record, previous, path, read_back, failure, stage
        )

    def _global_store_done(  # noqa: PLR0913, PLR0917 -- one argument per worker fact
        self,
        record: bytes,
        previous: bytes | None,
        path: str | None,
        read_back: bytes | None,
        failure: BaseException | None,
        stage: str,
    ) -> None:
        """Main thread: report what happened, and log only what read back."""
        if failure is not None:
            if stage in ("read", "backup"):
                self.notify_status(
                    f"{stage}: {failure} — nothing was written", refused=True
                )
            else:
                self.notify_status(f"store: {failure}", refused=True)
            return
        if previous is None or read_back is None:  # pragma: no cover
            self.notify_status("store: no read-back; nothing was logged", refused=True)
            return
        where = f"; what was there is in {literal(path)}" if path else ""
        sentence = verify.describe(record, read_back, what="the global settings")
        if verify.mismatches(record, read_back):
            self.notify_status(f"global: {sentence}{where}", refused=True)
            return
        self._undo_log.push(
            Record("global settings", GlobalEditRecord(previous=previous))
        )
        self.notify_status(f"stored the global settings; {sentence}{where}")

    # --- effects ------------------------------------------------------------

    def action_edit_effects(self) -> None:
        """Read the effects set, then open its table-driven editor.

        The gate is asked first, as it is for `e` and `g`: a locked gate
        means the unit sees no traffic at all. An effects read is one dump,
        so there is no slot to choose.
        """
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._effects_read_worker()

    def action_edit_parameter(self) -> None:
        """Put the unit in Mix mode, then open the parameter editor.

        Opening `p` sends one Mode Select, because a Program ``10`` edit
        lands only in the per-channel Mix buffer (see
        ``docs/PARAMETER_VERIFICATION_RUN_LOG.md`` and section 20 of
        ``docs/RESOLUTION_NOTES.md``). That is a send the app treats as a
        write everywhere else, so it asks the gate first and claims the
        exchange before a worker exists -- a locked gate means no Mode
        Select and no editor, and a busy port means the same. The screen
        itself sends nothing on mount.
        """
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._parameter_open_worker()

    @work(thread=True)
    def _parameter_open_worker(self) -> None:
        """**MIDI only.** One Mode Select; the modal opens on the main thread."""
        failure: BaseException | None = None
        try:
            with self._busy_gate, self._lock:
                self.device.mode_select(True)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(self._open_parameter, failure)

    def _open_parameter(self, failure: BaseException | None) -> None:
        """Show the parameter modal, or say why it did not open. Main thread."""
        if failure is not None:
            self.notify_status(f"parameters: {failure}", refused=True)
            return
        self.push_screen(
            ParameterScreen(self.device, self._write_gate, channel=self._channel())
        )

    @work(thread=True)
    def _effects_read_worker(self) -> None:
        """**MIDI only.** One effects dump; the modal opens on the main thread."""
        failure: BaseException | None = None
        record: bytes | None = None
        try:
            with self._busy_gate, self._lock:
                record = self.device.read_effects(0)  # User effects bank, slot 0
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"effects: {failure}", refused=True
            )
            return
        if record is None:  # pragma: no cover -- the failure path caught it
            return
        self.call_from_thread(self._open_effects, record)

    def _open_effects(self, record: bytes) -> None:
        """Show the effects modal. Main thread; sends nothing."""
        self.push_screen(
            EffectsScreen(EffectsEditor(record), gate=self._write_gate),
            self._effects_edited,
        )

    def _effects_edited(self, record: bytes | None) -> None:
        """A fired effects editor's record, on the main thread."""
        if record is None:
            return
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._effects_store_worker(record)

    @work(thread=True)
    def _effects_store_worker(self, record: bytes) -> None:
        """**MIDI only**, plus one backup file.

        The effects set has no number, so the backup's slot is the word
        ``effects``; there is one set, and a session writes one file for it.
        """
        from nano import backup as bk

        key = "effects"
        previous: bytes | None = None
        read_back: bytes | None = None
        path: str | None = None
        failure: BaseException | None = None
        stage = "read"
        try:
            with self._busy_gate, self._lock:
                previous = self.device.read_effects(0)  # User effects, slot 0
                if key not in self._backed_up:
                    stage = "backup"
                    path = bk.save(
                        key,
                        kind="effects",
                        name="effects settings",
                        blocks={"effects": previous},
                    )
                    self._backed_up.add(key)
                stage = "write"
                self.device.write_effects(0, record)
                stage = "read back"
                read_back = self.device.read_effects(0)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        self.call_from_thread(
            self._effects_store_done, record, previous, path, read_back, failure, stage
        )

    def _effects_store_done(  # noqa: PLR0913, PLR0917 -- one argument per worker fact
        self,
        record: bytes,
        previous: bytes | None,
        path: str | None,
        read_back: bytes | None,
        failure: BaseException | None,
        stage: str,
    ) -> None:
        """Main thread: report what happened, and log only what read back."""
        if failure is not None:
            if stage in ("read", "backup"):
                self.notify_status(
                    f"{stage}: {failure} — nothing was written", refused=True
                )
            else:
                self.notify_status(f"store: {failure}", refused=True)
            return
        if previous is None or read_back is None:  # pragma: no cover
            self.notify_status("store: no read-back; nothing was logged", refused=True)
            return
        where = f"; what was there is in {literal(path)}" if path else ""
        sentence = verify.describe(record, read_back, what="the effects settings")
        if verify.mismatches(record, read_back):
            self.notify_status(f"effects: {sentence}{where}", refused=True)
            return
        self._undo_log.push(
            Record("effects settings", EffectsEditRecord(previous=previous))
        )
        self.notify_status(f"stored the effects settings; {sentence}{where}")

    # --- scanning -----------------------------------------------------------

    def _maybe_offer_scan(self) -> None:
        """Offer a scan when there is nothing to start from.

        "Nothing" means neither layer: no printed catalog *and* no names
        already read from the unit and kept in the sidecar. Offering while
        the sidecar is full is how the offer came back on every launch.

        An injected ``None`` config path means a test asked for no disk
        access at all, so there is nowhere to remember "never" and nothing
        to offer against; the real launch always has a path.
        """
        path = self._ui_state_path
        if path is None or self._busy:
            return
        if self._scan_offer_shown:
            return
        if self.catalog or self._has_live_names():
            return
        from nano import config as _cfg

        try:
            if _cfg.load_ui_bool("scan_offer_dismissed", path, default=False):
                return
        except Exception:
            pass
        self._scan_offer_shown = True
        self.push_screen(ScanOfferScreen(SCAN_OFFER), self._scan_offer_answered)

    def _has_live_names(self) -> bool:
        """Whether any slot carries a name read off the unit."""
        return any(
            self.catalog.is_live(bank_id, number)
            for bank_id in self._bank_ids
            for number in range(banks.PROGRAMS_PER_BANK)
        )

    def _scan_offer_answered(self, answer: str | None) -> None:
        if answer == "never":
            self._save_ui_state(scan_offer_dismissed=True)
            return
        if answer == "scan":
            self.action_scan_device()

    def action_scan_device(self) -> None:
        """Read the names this unit will answer for, with progress.

        That is **one bank**, not five: only the User bank has a dump
        request in this protocol. The General MIDI and preset banks are
        ROM, and their names can only come from the printed catalog
        (``tools/extract_catalog.py``). A "scan" here is therefore the
        same 128 silent requests as `r`, given a progress bar and a
        Cancel button -- and it is the whole of what the unit can answer.
        """
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        # Claimed on the main thread, before the screen's worker exists;
        # ``_scan_read`` releases it in a ``finally``.
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        screen = ScanScreen(
            self._scan_read,
            title="Reading the User bank's names",
            total=banks.PROGRAMS_PER_BANK,
        )
        self.push_screen(screen, lambda names: self._scan_done(screen, names))

    def _scan_read(self, on_progress, cancel) -> dict[int, str] | None:
        """**MIDI only.** The body of a scan, on the scan screen's thread.

        ``read_program_names`` is the one request-at-a-time loop the
        bridge and the demo both honour -- keeping its pacing rather than
        writing a second loop here matters, because 128 requests
        back-to-back is what draws "data format error" from this unit.
        Cancel is honoured at the only safe boundary it has: the callback
        that runs once per program, after that program's reply has landed.
        """

        def report(done: int, total: int) -> None:
            if cancel.is_set():
                raise _ScanCancelled
            on_progress(done, total)

        try:
            with self._busy_gate, self._lock:
                return self.device.read_program_names(on_progress=report)
        except _ScanCancelled:
            return None
        finally:
            self._exchange.release()

    def _scan_done(self, screen: ScanScreen, names: dict[int, str] | None) -> None:
        """Adopt the names, or say why there are none.

        The screen only knows "no result"; the exception it caught is
        handed back here so a bridge fault is reported as one and a
        programming error still raises out of the app rather than being
        dressed up as a device fault.
        """
        if screen.error is not None:
            failure = screen.error
            if isinstance(failure, _BRIDGE_ERRORS):
                self.notify_status(f"scan: {failure}", refused=True)
                return
            raise failure
        if names is None:
            self.notify_status("scan cancelled; nothing read")
            return
        self._adopt("USER", names)

    def action_search(self) -> None:
        """Search names, tags and notes, with the family's field picker."""

        def done(result: tuple[str, dict[str, bool]] | None) -> None:
            if result is None:
                return
            needle, fields = result
            needed = needle.strip()
            if not needed:
                return
            rows = self._search_rows(needed, fields)
            if not rows:
                # literal on the typed text too: whatever came back from
                # the search form goes into a markup widget, and the form
                # is where a bracket the user typed is most at home.
                self.notify_status(f"nothing matching {literal(needed)!r}")
                return
            lines = [f"{len(rows)} match(es) for {literal(needed)!r}", ""]
            shown, more = self._search_lines(rows)
            lines.extend(shown)
            if more:
                lines.append(f"... and {more} more (narrow the search)")
            self.push_screen(ReportScreen("Search", "\n".join(lines)))

        self.push_screen(SearchScreen("Search"), done)

    def _search_rows(
        self, needle: str, fields: dict[str, bool]
    ) -> dict[tuple[str, int], list[str]]:
        """Gather hits by slot, with what matched beside each one.

        The catalog holds only names, so tags and notes come from the
        favourites store: ``with_tag`` for an exact tag -- a substring
        match would make "pad" find "padded" and "lead" find "misleading"
        -- and ``search`` narrowed to the note column for notes. The
        annotations are rendered here, through ``literal()``, because all
        three kinds of text are user-supplied and the report is a markup
        widget.
        """
        rows: dict[tuple[str, int], list[str]] = {}
        if fields.get("names"):
            for bank_id, _kind, number, _name in self.catalog.search(needle):
                rows.setdefault((bank_id, number), [])
        if self.favorites is None:
            return rows
        if fields.get("tags"):
            for favourite in self.favorites.with_tag(needle):
                rows.setdefault((favourite.bank_id, favourite.number), []).append(
                    f"tags {literal(favourite.tags)}"
                )
        if fields.get("notes"):
            lower = needle.lower()
            for favourite in self.favorites.search(needle):
                if not favourite.note or lower not in favourite.note.lower():
                    continue
                rows.setdefault((favourite.bank_id, favourite.number), []).append(
                    f"note {literal(favourite.note)}"
                )
        return rows

    def _search_lines(
        self, rows: dict[tuple[str, int], list[str]]
    ) -> tuple[list[str], int]:
        """Render the hits in bank order, and how many spilled past 400."""
        order = {bank_id: index for index, bank_id in enumerate(self._bank_ids)}
        lines: list[str] = []
        for bank_id, number in sorted(
            rows, key=lambda where: (order.get(where[0], len(order)), where[1])
        ):
            try:
                entry = banks.slot(bank_id, number)
            except LookupError:
                # A favourite naming a bank this build does not know is
                # skipped, as _all_favourites does.
                continue
            shown = literal(
                self.catalog.display_name(bank_id, entry.program_change).rstrip()
            )
            if self.catalog.differs(bank_id, entry.program_change):
                shown += " *"
            detail = rows[(bank_id, number)]
            suffix = "  " + "; ".join(detail) if detail else ""
            lines.append(
                f"{entry.display:<6} {shown:<12} PC {entry.program_change:>3}{suffix}"
            )
            if len(lines) >= 400:
                # Count the ones that were skipped as unrenderable too,
                # so "and N more" is a count of hits, not of drawn lines.
                return lines, len(rows) - len(lines)
        return lines, 0

    def action_device_info(self) -> None:
        """Busy-guarded like every other MIDI action.

        `i` needs no guard so urgently as the others: ``identify`` is one
        request -- but the reply is held and flushed on the *next*
        message, so an `i` interleaved with the 128 requests of `r` steals
        one of its User Dump replies and leaves the read one short. The
        gate and the exchange are claimed here, before the worker exists.
        """
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        self._info_worker()

    @work(thread=True)
    def _info_worker(self) -> None:
        """**MIDI only** -- the report is built on the main thread."""
        failure: BaseException | None = None
        fields: dict | None = None
        try:
            with self._busy_gate, self._lock:
                fields = self.device.identify()
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"device: {failure}", refused=True
            )
            return
        self.call_from_thread(self._show_info, fields)

    def _show_info(self, fields) -> None:
        lines = [f"connection      {literal(self.device.description)}", ""]
        if fields and fields.get("is_alesis"):
            import nano.messages as msg

            lines.append(
                "manufacturer    "
                + ".".join(f"{b:02X}" for b in msg.ALESIS_ID)
                + "  (Alesis, extended ID)"
            )
            lines.append(
                f"family          {fields['family'][0]:#04x}"
                + ("  (QS)" if fields.get("is_qs_family") else "")
            )
            member = fields.get("member")
            if member is not None:
                lines.append(
                    f"member          {member[0]:#04x}"
                    + ("  (NanoSynth)" if member[0] == msg.NANOSYNTH_MEMBER else "")
                )
            if fields.get("version"):
                lines.append(f"software        {fields['version']}")
            lines.append("")
            if fields.get("inferred"):
                lines.append("It answered a QS dump request, but no Identity")
                lines.append("Reply was waiting to be flushed, so the member")
                lines.append("number above is what it must be, not what it")
                lines.append("said.")
            else:
                lines.append("This unit never answers an Identity Request when")
                lines.append("it gets one: it holds the reply and sends it the")
                lines.append("next time it answers anything else. nanosyned")
                lines.append("prompts it with a Global Dump Request.")
        else:
            lines.append("nothing Alesis answered.")
            lines.append("")
            lines.append("Other instruments on the chain may have answered;")
            lines.append("this reports only the one it is looking for.")
        lines.append("")
        lines.append(
            f"catalog         {len(self.catalog)} names"
            + (f" from {self.catalog.source}" if self.catalog.source else "")
        )
        lines.append(
            "favourites      "
            + (
                f"{len(self.favorites)}"
                if self.favorites is not None
                else "(none open)"
            )
        )
        lines.append("")
        lines.append(_build_line())
        self.push_screen(ReportScreen("Device", "\n".join(lines)))

    def action_import(self) -> None:
        """Open the import flow: picker, source bank, whole bank or single.

        The flow is read-only up to the screens it pushes, so a locked gate
        does not stop it; the screens show the gate state and re-check it
        before any plan leaves them. ``None`` as the starting path lets the
        picker consult its remembered folder rather than overriding it.
        """
        run_import_flow(
            self,
            None,  # type: ignore[arg-type]
            open_whole_bank=self._open_whole_bank,
            open_append=self._open_append,
            open_single=self._open_single,
        )

    def action_export_favourites(self) -> None:
        """Export favourited User programs to a .syx file."""
        if self.favorites is None:
            self.notify_status("no favourites database", refused=True)
            return
        try:
            numbers = exporting.favourite_numbers(self.favorites)
        except ValueError as exc:
            self.notify_status(str(exc), refused=True)
            return
        remembered = cfg.load_ui_str("import.folder", self._ui_state_path)
        folder = remembered if remembered is not None else os.path.expanduser("~")
        default = os.path.join(folder, "nanosyned-favourites.syx")

        def after_path(path: str | None) -> None:
            if not path:
                return
            path = os.path.expanduser(path)
            if os.path.exists(path):

                def after_confirm(answer) -> None:
                    if not answer:
                        return
                    self._start_export(numbers, path)

                self.push_screen(
                    ConfirmScreen(f"{literal(path)} already exists; replace it?"),
                    after_confirm,
                )
                return
            self._start_export(numbers, path)

        self.push_screen(PromptScreen("Export favourites to:", default), after_path)

    def _start_export(self, numbers, path: str) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        cancel = threading.Event()
        progress = ImportProgressScreen(
            total=len(numbers), on_stop=cancel.set, verb="exporting"
        )
        self.push_screen(progress)
        self._export_worker(numbers, path, progress, cancel)

    @work(thread=True)
    def _export_worker(self, numbers, path: str, progress, cancel) -> None:
        try:
            with self._busy_gate, self._lock:
                result = exporting.export_selected(
                    self.device,
                    numbers,
                    path,
                    overwrite=True,
                    on_read=lambda number, name, done, total: self.call_from_thread(
                        progress.set_progress, done, total, number, name, 0
                    ),
                    cancelled=cancel.is_set,
                )
        except exporting.ExportCancelled as exc:
            self.call_from_thread(self._export_done, progress, None, str(exc))
            return
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(self._export_done, progress, None, str(exc))
            return
        finally:
            self._exchange.release()
        self.call_from_thread(self._export_done, progress, result, None)

    def _export_done(self, progress, result, error) -> None:
        try:
            progress.dismiss(None)
        except Exception:
            pass
        if error is not None:
            self.notify_status(error, refused=True)
            return
        if result is None:
            self.notify_status("export cancelled", refused=True)
            return
        self.notify_status(
            f"exported {result.count} program(s) to {literal(result.path)}"
        )

    def action_backup(self) -> None:
        """Back up the whole unit to a .syx file."""
        remembered = cfg.load_ui_str("import.folder", self._ui_state_path)
        folder = remembered if remembered is not None else os.path.expanduser("~")
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        default = os.path.join(folder, f"nanosyned-backup-{timestamp}.syx")

        def after_path(path: str | None) -> None:
            if not path:
                return
            path = os.path.expanduser(path)
            if os.path.exists(path):

                def after_confirm(answer) -> None:
                    if not answer:
                        return
                    self._start_backup(path)

                self.push_screen(
                    ConfirmScreen(f"{literal(path)} already exists; replace it?"),
                    after_confirm,
                )
                return
            self._start_backup(path)

        self.push_screen(PromptScreen("Back up to:", default), after_path)

    def _start_backup(self, path: str) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        cancel = threading.Event()
        progress = ImportProgressScreen(
            total=fullbackup.TOTAL_RECORDS, on_stop=cancel.set, verb="backing up"
        )
        self.push_screen(progress)
        self._backup_worker(path, progress, cancel)

    @work(thread=True)
    def _backup_worker(self, path: str, progress, cancel) -> None:
        try:
            with self._busy_gate, self._lock:
                result = fullbackup.backup_device(
                    self.device,
                    path,
                    overwrite=True,
                    on_read=lambda kind, number, name, done, total: (
                        self.call_from_thread(
                            progress.set_progress, done, total, number, name, 0
                        )
                    ),
                    cancelled=cancel.is_set,
                )
        except fullbackup.BackupCancelled as exc:
            self.call_from_thread(self._backup_done, progress, None, str(exc))
            return
        except _BRIDGE_ERRORS as exc:
            self.call_from_thread(self._backup_done, progress, None, str(exc))
            return
        except OSError as exc:
            self.call_from_thread(self._backup_done, progress, None, str(exc))
            return
        finally:
            self._exchange.release()
        self.call_from_thread(self._backup_done, progress, result, None)

    def _backup_done(self, progress, result, error) -> None:
        try:
            progress.dismiss(None)
        except Exception:
            pass
        if error is not None:
            self.notify_status(error, refused=True)
            return
        if result is None:
            self.notify_status("backup cancelled", refused=True)
            return
        self.notify_status(
            f"backed up {result.count} record(s) to {literal(result.path)}"
        )

    def action_restore(self) -> None:
        """Choose a full-backup file and open its confirmation screen."""
        self.push_screen(FilePickerScreen(path=None), self._restore_file_chosen)

    def _restore_file_chosen(self, path: str | None) -> None:
        """Read the chosen file offline, plan every record, then ask."""
        if not path:
            return
        try:
            source = importing.read_import(path)
        except (OSError, ValueError) as exc:
            self._restore_report(f"could not read {path}: {exc}")
            return
        if len(source.banks) != 1:
            self._restore_report(
                f"{path} holds {len(source.banks)} banks; full restore expects one"
            )
            return
        try:
            plan = importplan.plan_restore(source.banks[0])
        except ValueError as exc:
            self._restore_report(str(exc))
            return
        if not plan.steps:
            self._restore_report(f"{path} holds no records this app can restore")
            return
        self.push_screen(
            FullRestoreScreen(plan, path=path, gate=self._write_gate),
            self._restore_confirmed,
        )

    def _restore_report(self, sentence: str) -> None:
        """A read-only restore refusal, in the same report screen as import."""
        self.push_screen(ReportScreen("Restore", sentence), lambda _answer: None)

    def _restore_confirmed(self, plan) -> None:
        """Start a confirmed full restore through the normal fence."""
        if plan is not None:
            self._import_plan(plan, label="restore")

    def _open_whole_bank(self, plan) -> None:
        """Push the whole-bank screen; run the plan when it confirms."""

        def done(result) -> None:
            if result is None:
                return
            self._import_plan(result)

        self.push_screen(
            WholeBankScreen(plan, gate=self._write_gate, catalog=self.catalog),
            done,
        )

    def _open_append(self, bank) -> None:
        """Scan the User bank for free trailing slots, then show the append plan."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        cancel = threading.Event()
        progress = ImportProgressScreen(
            total=127, on_stop=cancel.set, verb="reading free slots"
        )
        self.push_screen(progress)
        self._append_scan_worker(bank, progress, cancel)

    @work(thread=True)
    def _append_scan_worker(self, bank, progress, cancel) -> None:
        """**MIDI only.** Find the first free trailing slot and plan the append."""
        failure: BaseException | None = None
        plan = None
        start = 127
        try:
            with self._busy_gate, self._lock:
                off = writing.read_record(self.device, "program", 127)
                template = initbank.init_record(off)

                def read(number: int) -> bytes:
                    if cancel.is_set():
                        raise RuntimeError("cancelled")
                    self.call_from_thread(
                        progress.set_progress,
                        127 - number,
                        127,
                        number,
                        "",
                        0,
                    )
                    return writing.read_record(self.device, "program", number)

                start = initbank.append_start(read, template)
                plan = importplan.plan_append(bank, range(start, 127))
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self._append_scan_failed, progress, failure)
            return
        self.call_from_thread(self._open_append_screen, bank, plan, start, progress)

    def _append_scan_failed(self, progress, failure: BaseException) -> None:
        try:
            progress.dismiss(None)
        except Exception:
            pass
        self.notify_status(f"append: {failure}", refused=True)

    def _open_append_screen(self, bank, plan, start: int, progress) -> None:
        """Main thread: dismiss the scan progress and show the append plan."""
        try:
            progress.dismiss(None)
        except Exception:
            pass

        def done(result) -> None:
            if result is None:
                return
            if isinstance(result, str) and result == MANUAL:
                self._open_single(bank)
                return
            self._import_plan(result)

        self.push_screen(
            AppendBankScreen(
                bank=bank,
                plan=plan,
                start=start,
                gate=self._write_gate,
            ),
            done,
        )

    def _open_single(self, bank) -> None:
        """Push the mapping screen; plan its assignments when it confirms."""

        def done(result) -> None:
            if not result:
                return
            try:
                plan = importplan.plan_single(bank, list(result))
            except ValueError as exc:
                self.notify_status(str(exc), refused=True)
                return
            self._import_plan(plan)

        def preview(record) -> bool:
            return self._preview_import(record)

        self.push_screen(
            SingleMappingScreen(
                bank=bank,
                gate=self._write_gate,
                catalog=self.catalog,
                on_preview=preview,
            ),
            done,
        )

    def _import_plan(self, plan, *, label: str = "import") -> None:
        """Hand a confirmed plan to the import or restore worker.

        The gate is asked here, on the main thread, before a port is opened:
        a locked gate means nothing is sent and the refusal names what to do
        next. The progress screen is pushed before the worker starts so the
        user can cancel between records.
        """
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        cancel = threading.Event()
        verb = "restoring" if label == "restore" else "importing"
        progress = ImportProgressScreen(
            total=len(plan.steps), on_stop=cancel.set, verb=verb
        )
        self.push_screen(progress)
        self._import_worker(plan, progress, cancel, label)

    @work(thread=True)
    def _import_worker(self, plan, progress, cancel, label: str = "import") -> None:
        """**MIDI only.** Import or restore a plan one record at a time.

        Each step is read, backed up, stored and read back in turn; the
        progress screen is updated between steps so a cooperative cancel can
        stop before the next record starts. Only an agreed read-back is
        recorded for undo, and a partial failure keeps a reduced batch entry
        with only the edits that succeeded.
        """
        results: list[writing.Result] = []
        try:
            with self._busy_gate, self._lock:
                results = self._run_plan_locked(plan, progress, cancel)
        finally:
            self._exchange.release()
        self.call_from_thread(self._import_done, plan, results, progress, label)

    def _run_plan_locked(self, plan, progress, cancel) -> list[writing.Result]:
        """Run one plan while the caller holds the busy gate and lock."""
        results: list[writing.Result] = []
        for index, step in enumerate(plan.steps):
            if cancel.is_set():
                break
            number = step.target
            name = self._step_name(step)
            failures = sum(1 for result in results if result.failure)
            self.call_from_thread(
                progress.set_progress,
                index,
                len(plan.steps),
                number,
                name,
                failures,
            )
            results.append(self._import_one_step(step, number))
        return results

    def action_init_bank(self) -> None:
        """Push the init-bank confirmation screen."""
        self.push_screen(
            InitBankScreen(gate=self._write_gate), self._init_bank_confirmed
        )

    def _init_bank_confirmed(self, confirmed: bool | None) -> None:
        if confirmed:
            self._start_init()

    def _start_init(self) -> None:
        """Start the confirmed init: gate, busy, exchange, then the worker."""
        refusal = self._write_gate.check()
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return
        cancel = threading.Event()
        progress = ImportProgressScreen(
            total=127, on_stop=cancel.set, verb="initialising"
        )
        self.push_screen(progress)
        self._init_worker(progress, cancel)

    @work(thread=True)
    def _init_worker(self, progress, cancel) -> None:
        """**MIDI only.** Read 127 Off, build Init, then run the normal fence."""
        failure: BaseException | None = None
        plan = None
        results: list[writing.Result] = []
        try:
            with self._busy_gate, self._lock:
                off = writing.read_record(self.device, "program", 127)
                template = initbank.init_record(off)
                plan = importplan.plan_init(template)
                results = self._run_plan_locked(plan, progress, cancel)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(self._init_failed, progress, failure)
            return
        self.call_from_thread(self._import_done, plan, results, progress, "init")

    def _init_failed(self, progress, failure: BaseException) -> None:
        """Main thread: dismiss the progress screen and report a template failure."""
        try:
            progress.dismiss(None)
        except Exception:
            pass
        self.notify_status(f"init: {failure}", refused=True)

    def _import_one_step(self, step, number: int | None) -> writing.Result:
        """Read, back up, store and verify one step; never raises."""
        result = writing.Result(
            kind=step.kind, number=number, record=bytes(step.record)
        )
        what = (
            f"the {writing.RECORD_NAMES[step.kind]} "
            f"at {writing.label(step.kind, number)}"
        )
        try:
            previous = writing.read_record(self.device, step.kind, number)
        except _BRIDGE_ERRORS as exc:
            result.failure = str(exc)
            result.stage = "read"
            return result
        result.previous = writing.truncate(step.kind, previous, what)
        try:
            result.backup = writing.save_backup(step.kind, number, result.previous)
        except _BRIDGE_ERRORS as exc:
            result.failure = str(exc)
            result.stage = "backup"
            return result
        try:
            writing.write_record(self.device, step.kind, number, step.record)
        except _BRIDGE_ERRORS as exc:
            result.failure = str(exc)
            result.stage = "store"
            return result
        result.sent = True
        try:
            read_back = writing.read_record(self.device, step.kind, number)
            result.read_back = writing.truncate(step.kind, read_back, what)
        except _BRIDGE_ERRORS as exc:
            result.failure = str(exc)
            result.stage = "read-back"
            return result
        result.sentence = verify.describe(
            step.record,
            result.read_back,
            what=writing.label(step.kind, number, self._step_name(step)),
        )
        if verify.mismatches(step.record, result.read_back):
            result.failure = result.sentence
            result.stage = "verify"
        else:
            result.stage = "verified"
        return result

    @staticmethod
    def _step_name(step) -> str:
        """The name inside a step's record, or ``""`` for a kind that has none."""
        if step.kind == "program":
            return rec.program_name(step.record).rstrip()
        if step.kind == "mix":
            return rec.mix_name(step.record).rstrip()
        return ""

    def _import_done(  # noqa: C901, PLR0912
        self, plan, results, progress, label: str = "import"
    ) -> None:
        """Main thread: refresh names, push undo, report the summary."""
        if progress is not None:
            try:
                progress.dismiss(None)
            except Exception:
                pass
        agreed = [r for r in results if r.stage == "verified"]
        failed = [r for r in results if r.failure]
        remembered = 0
        remarked = 0
        for result in agreed:
            name = self._step_name_for(result)
            if result.kind == "program" and result.number is not None:
                self.catalog.set_live_name("USER", result.number, name)
                entry = self._remember_program(
                    "USER",
                    result.number,
                    result.record,
                    manual=False,
                    previous=result.previous or None,
                )
                if entry is not None:
                    remembered += 1
                    if entry.favourite and self.favorites is not None:
                        remarked += 1
        if self.memory is not None and remembered:
            self._refresh_bank_fav_count("USER")
        if self._current_bank == "USER":
            self._refill_keeping_place()
        # One undo entry for the whole session; an edit's name is the name
        # that was there before the store, so `z` restores both bytes and name.
        # A full restore spans every record kind, so its batch is a
        # RestoreRecord; an ordinary program import keeps its older shape.
        if label == "restore":
            batch = tuple(self._batch_edit(r) for r in agreed)
            if batch:
                self._undo_log.push(Record("restore", RestoreRecord(edits=batch)))
        else:
            edits = tuple(
                EditRecord(
                    number=r.number,
                    previous=r.previous,
                    name=writing.record_name(r.kind, r.previous),
                )
                for r in agreed
                if r.kind == "program" and r.number is not None
            )
            if edits:
                self._undo_log.push(Record("import", ImportRecord(edits=edits)))
        memory_note = (
            f"; remembered {remembered}, re-marked {remarked}"
            if self.memory is not None
            else ""
        )
        if label == "init":
            memory_note += "; favourite marks hidden; z restores programs, not marks"
        if failed:
            first = failed[0]
            self.notify_status(
                f"{label}: {len(agreed)} of {len(results)} stored; "
                f"{first.failure}{memory_note}",
                refused=True,
            )
        else:
            self.notify_status(
                f"{label}: {len(agreed)} of {len(results)} stored{memory_note}"
            )

    @staticmethod
    def _step_name_for(result: writing.Result) -> str:
        """The name inside a result's record, or ``""`` for a kind that has none."""
        if result.kind == "program":
            return rec.program_name(result.record).rstrip()
        if result.kind == "mix":
            return rec.mix_name(result.record).rstrip()
        return ""

    @staticmethod
    def _batch_edit(
        result: writing.Result,
    ) -> EditRecord | MixEditRecord | EffectsEditRecord | GlobalEditRecord:
        """The undo record for one verified full-restore step."""
        name = writing.record_name(result.kind, result.previous)
        if result.kind == "program":
            return EditRecord(
                number=cast(int, result.number),
                previous=result.previous,
                name=name,
            )
        if result.kind == "mix":
            return MixEditRecord(
                number=cast(int, result.number),
                previous=result.previous,
                name=name,
            )
        if result.kind == "effects":
            return EffectsEditRecord(
                number=result.number or 0,
                previous=result.previous,
                name=name,
            )
        return GlobalEditRecord(previous=result.previous)

    def _preview_import(self, record) -> bool:
        """Load a source record into the program edit buffer (no store).

        A load (opcode ``02``) is not a store, so it needs no write gate --
        but it is still a MIDI send, and every send in this app is claimed
        before it goes out. The claim is taken here, on the main thread,
        before the message exists: while a worker holds the exchange (an
        ``r`` read, a store) the preview is refused rather than
        interleaved. ``write_edit_program`` drains the port first, so an
        unclaimed preview would steal the replies of whatever is running.

        Returns ``True`` when the record was loaded, ``False`` when it was
        refused or the device failed; the screen uses that to decide
        whether it may claim a load in its own status line.
        """
        if self._busy:
            self.notify_status("busy", refused=True)
            return False
        if not self._exchange.acquire(blocking=False):
            self.notify_status("busy", refused=True)
            return False
        failure: BaseException | None = None
        try:
            with self._lock:
                self.device.write_edit_program(record, edit=0)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.notify_status(f"preview: {failure}", refused=True)
            return False
        self.notify_status("loaded into the edit buffer; nothing stored")
        return True

    def action_help(self) -> None:
        self.push_screen(ReportScreen("nanosyned", f"{_HELP}\n\n{_build_line()}"))


_HELP = """The five banks

  General MIDI  128 programs, GM order. ROM.
  User          128 programs. The only bank this unit will dump, and the
                only one you can change. Program 127 is hardwired silent:
                selecting it is how a MIDI channel gets muted.
  Preset 1-3    128 each. ROM, and reachable **only over MIDI** -- the
                front panel cannot get to them at all, which is most of
                the reason for a program like this one.

640 programs. Bank Select is Controller 0 and the unit ignores Controller
32, so a sequencer that sends only 32 will never leave the bank it is in.

Names

Only the User bank can be read back, so its names come from the
instrument and are shown in bold; the rest come from a catalog generated
from the manual, and a `*` marks a slot where the two disagree.

Keys

  ↑↓        move; this never sends anything
  tab       switch pane
  ⏎         select on the unit -- Bank Select then Program Change
  r         read the User bank's names (silent; 128 requests)
  S         the same read with a progress bar and a Cancel button
  /         search names, tags or notes
  [ ]       previous / next MIDI channel
  c         set the MIDI channel
  a         auto-load the focused preset (PC/LSB/MSB)
  ← →       switch pane
  f         favourite the slot under the cursor
  F         all slots / favourites here / every favourite
  t n       tags, note
  *         rate the slot under the cursor, 0-5
  V         show only slots at/above a star rating
  e         edit the focused program, or the focused mix in Mixes
  M         send Mode Select: program mode or mix mode
  g         edit the global settings
  w         arm or lock the write gate
  z Z       undo / undo all of this session's stores
  i         what the unit says it is
  I         import programs from a .syx / .sqs file
  E         export favourited User programs to a .syx file
  B         back up the whole unit to a .syx file
  R         restore a full backup from a .syx file
  N         initialise the User bank (programs 000-126)
  q         quit

Writing

The write gate starts locked and `e` refuses until `w` arms it. A store is
never one keystroke: `a` arms it, naming the slot and the program it is about
to replace, and `w` fires only while armed. The destination is read in full
and backed up to a file first; if that read fails, nothing is written. After
the store the record is read back and compared, and the result is reported
byte for byte -- this unit answers a store with silence whether it took it or
not, so the read-back is the only evidence there is. Only a store that reads
back is remembered for undo.

Mixes and the global set go through the same five steps. A mix is 138 bytes
and sixteen channels; the editor stages a channel's program, volume or pan in
a working copy and sends nothing until armed. The global set is one record
and one store: rows the specification documents for another model, the
deleted parameters and rows an older dump does not carry are shown but not
written, because writing a value the unit is documented to ignore and
reporting success would be a lie. `M` is not a store: it changes what plays
and writes no memory, so it is gated and confirmed but cannot be undone.
"""


def _build_line() -> str:
    """One line naming both builds: this tool, and the library under it.

    A checkout nobody installed has no version to name and a wheel has no
    commit; each degrades to the words for what it is (compare
    :func:`vinsynlib.build.build_of`, which never guesses) rather than
    dressing a ``None`` up as something proved.
    """
    parts = []
    for name, origin in (("nanosyned", __file__), ("vinsynlib", None)):
        build = build_of(name, origin=origin)
        where = build.version or "an unknown version"
        if build.commit:
            tagged = ""
            if build.tag:
                tagged = f", {build.tag.removeprefix('refs/tags/')}"
            where += f" (commit {build.commit[:7]}{tagged})"
        parts.append(f"{name} {where}")
    return " · ".join(parts)


def _say_sweep(bridge: Any) -> None:
    """One line when the launch swept for the port, and silence otherwise.

    A sweep takes minutes on a busy host; saying so, once, is what keeps
    a slow launch from being mistaken for the normal one. Read
    defensively: the attribute is the bridge's business, and a device
    that does not track a sweep (the demo does not) simply gets silence.
    """
    if not getattr(bridge, "swept", False):
        return
    seconds = getattr(bridge, "probe_seconds", None)
    port = getattr(bridge, "port", None)
    if not seconds or not port:
        return
    print(f"swept for {seconds:.1f} s; found {port}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser("nanosyned", "Browse an Alesis NanoSynth's sounds.")
    # Every flag's help text is the family's, from vinsynlib.spec. This tool
    # used to word four of them its own way, which is how the same option
    # came to read one way in one program and another in the other eight.
    #
    # --midi-channel is the family's older spelling of --device-channel and
    # is still accepted: the NanoSynth's own base channel is a different
    # number from the channel a program change is sent on, and the old name
    # is on nine command lines already.
    add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        device_channel=True,
        catalog=True,
        config=True,
        favorites=True,
        # The write path is opt-in: without `--allow-write` the gate starts
        # locked and the only way to arm it is `w`, deliberately.
        allow_write=True,
    )
    cfg.apply_config_help(parser, tool="nanosyned")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config_path = getattr(args, "config", None) or cfg.DEFAULT_PATH
    # The family's range checks, before anything is opened: a mistyped
    # channel costs a message rather than a wrong program change sent to a
    # real instrument.
    validate_common(args)

    if args.config is None:
        cfg.migrate_legacy_config("nanosyned")
        import os

        os.makedirs(cfg.config_dir("nanosyned"), exist_ok=True)

    #: DemoDevice and NanoBridge are structurally interchangeable -- the
    #: demo mirrors the bridge's interface without inheriting from it -- so
    #: the local is deliberately untyped rather than forced into a Protocol.
    device: Any
    if args.demo:
        from nanosyned.demo import DemoDevice

        device = DemoDevice()
    else:
        from nano import bridge as b

        b.install_clean_exit()
        # The channel on the command line wins; otherwise the one used last
        # time, so it does not have to be given again every run.
        remembered = cfg.load_channel(config_path)
        try:
            if args.port:
                device = b.NanoBridge.open(
                    args.port,
                    recv_port=args.recv_port,
                    channel=(
                        (args.device_channel - 1)
                        if args.device_channel is not None
                        else (remembered if remembered is not None else 0)
                    ),
                )
            else:
                # One Global Dump Request to the remembered port; the sweep
                # only when there is nothing remembered, when the
                # remembered port no longer answers, or on --scan.
                device = b.NanoBridge.connect(
                    config_path=config_path,
                    channel=(
                        (args.device_channel - 1)
                        if args.device_channel is not None
                        else (remembered if remembered is not None else 0)
                    ),
                    scan=args.scan,
                    on_try=lambda n: print(f"  probing {n}...", file=sys.stderr),
                )
        except Exception as exc:
            sys.exit(f"error: {exc}")

        # One line when the launch swept: a slow start explained is not
        # a hung one.
        _say_sweep(device)

        # Remember whatever channel is actually in use -- which after a
        # sweep is the one the unit reported, not the one asked for. The
        # port pair is saved by `connect` itself, and only after a sweep: the
        # fast path must not rewrite the file it was asked to trust.
        try:
            cfg.save_channel(getattr(device, "channel", 0), config_path)
        except OSError:
            pass

    from nano.favorites import Favorites

    try:
        store = Favorites(args.favorites)
    except Exception as exc:
        # _migrate refuses a database written by a newer build, which is the
        # right refusal, and sqlite3 raises on a file that is not a database
        # at all. Every other startup failure here leaves by sys.exit; these
        # two used to print a traceback.
        raise SystemExit(f"error: {exc}") from None
    app = NanosynedApp(
        device,
        catalog=cat.load(args.catalog),
        favorites=store,
        config_path=config_path,
        catalog_path=args.catalog or cat.DEFAULT_PATH,
        memory_path=preset_memory.default_path(),
        allow_write=args.allow_write,
    )
    try:
        app.run()
    finally:
        store.close()
        if app.memory is not None:
            app.memory.close()
        # Never close mid-exchange: waits for the gate to be neither
        # refused nor in progress, then closes.
        with close_when_idle(device, gate=app._busy_gate):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
