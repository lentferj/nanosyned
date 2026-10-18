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

**Moving the cursor never sends anything.** Selecting a program changes
what the instrument plays. Selection is bound to Enter and nothing else,
and a test enforces it.

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
import sys
import threading
from typing import Any, ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Header, Static

from nano import banks, livenames
from nano import catalog as cat
from nano.config import UNSET
from nano.favorites import rating_cell
from nanosyned.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen
from nanosyned.screens import KeyHints, PromptScreen, ReportScreen
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
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all slots",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}


def _view_key(blocks: tuple[str, ...]) -> tuple[str, ...]:
    """Swap the family's ``F favourites view`` for this tool's ``v``.

    ``f`` writes the favourites database and ``F`` does not, so the
    family's shift-pair left a write one slip away from a read; ``v`` has
    no such twin. rxved and p2ked made the same swap, and the family asks
    a tool that renames a shared key to say why in its own test -- see
    tests/test_conformance.py, where the whole divergence is two
    sentences.
    """
    return tuple(
        "v favourites view" if block == "F favourites view" else block
        for block in blocks
    )


#: The legend. Every binding the app has, in the order somebody meets them.
#: Built from the family's shared legend rather than hand-written: it used
#: to be a tuple of its own, in its own order. ``keys.legend`` puts this
#: tool's own hints in the one place the family leaves for them -- after
#: `n note`, before `i device` -- and this tool has three: the scan key
#: and the two rating keys, none of which another browser in the family
#: shares yet. `v` apart, every other key it binds is a shared one, which
#: `_view_key` renames.
KEY_HINTS = _view_key(
    keys.legend(extras=("S scan device", "* rating", "V rating filter"))
)


def wrap_blocks(blocks, width: int, sep: str = _SEP) -> str:
    """Pack hints into lines no wider than ``width``.

    Re-exported from :func:`vinsynlib.keys.wrap_blocks`, which every tool
    in this family now uses. Kept as a name because it is part of this
    module's published surface.
    """
    return _wrap_blocks(blocks, width, sep)


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
        # `v`, not the family's `F`: `f` writes the favourites database and
        # `F` does not, so the family's shift-pair left a write one slip away
        # from a read. `v` has no such twin. rxved and p2ked made the same
        # swap; the rename is declared in tests/test_conformance.py.
        Binding("v", "cycle_favorites", "Favourites view"),
        Binding("t", "edit_tags", "Tags"),
        Binding("n", "edit_note", "Note"),
        Binding("asterisk", "edit_rating", "Rating"),
        Binding("V", "rating_filter", "Rating filter"),
        Binding("slash", "search", "Search"),
        Binding("i", "device_info", "Device"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        device,
        *,
        catalog=None,
        favorites=None,
        config_path: str | None = None,
        catalog_path: str | None = None,
    ) -> None:
        super().__init__()
        self.device = device
        self.catalog = catalog if catalog is not None else cat.empty()
        #: Injected, never opened here, so a test cannot write into the
        #: user's real database.
        self.favorites = favorites
        #: Where the send channel is remembered. Injected and None
        #: in tests, so a test cannot drop a config into the
        #: working directory.
        self._config_path = config_path
        #: Which catalog file this browser is pointed at. The live-names
        #: sidecar travels beside it -- see :func:`nano.livenames.path_for`
        #: -- so a run against another catalog reads that catalog's names.
        self._catalog_path = catalog_path or cat.DEFAULT_PATH
        self.view_mode = VIEW_ALL
        self._lock = threading.RLock()
        self._bank_ids: list[str] = banks.bank_ids()
        self._current_bank = self._bank_ids[0]
        self._current: list[banks.Slot] = []
        self._filling = False
        #: The family's busy gate, over the old boolean. It tracks whether
        #: an exchange is in flight (for an idle close) and refuses a
        #: second one before a worker is spawned.
        self._busy_gate = BusyGate()
        #: One exchange at a time, claimed on the main thread before the
        #: worker is spawned and released by the worker in a ``finally``.
        #: The gate alone cannot carry this: entering it *clears* a
        #: refusal, so between claiming and entering a second action would
        #: find neither signal set and start a second worker. ``_busy``
        #: reads this claim as the third signal.
        self._exchange = threading.Lock()
        #: Restore the remembered browser state: which bank the left pane
        #: was on, which row the right pane's cursor was on, and where the
        #: cycling ``v`` view stood. Loaded here, not in ``on_mount``,
        #: because the first ``_fill`` down there builds its rows out of
        #: ``view_mode`` and ``_current_bank``; restoring anything later
        #: would mean filling twice. An injected path only -- ``None``
        #: means a test that asked for silence and gets it. The cursor is
        #: clamped to whatever the first fill produced, in ``on_mount``.
        self._saved_slot_cursor: int | None = None
        #: The remembered rating filter, or None for "show everything".
        #: Restored here rather than in ``on_mount`` for the same reason
        #: as the view: the first ``_fill`` builds rows through
        #: ``_visible``, which applies it.
        self.rating_filter: RatingFilter | None = None
        if self._config_path is not None:
            from nano import config as _cfg

            try:
                saved_view = _cfg.load_ui_state(
                    "view_mode", self._config_path, default=UNSET
                )
                # Never trust a stored value: a view this build renamed
                # or a stale bank index is ignored, and the app opens on
                # its defaults.
                if saved_view is not UNSET and saved_view in VIEW_CYCLE:
                    self.view_mode = saved_view
                saved_bank = _cfg.load_ui_int("bank_index", self._config_path)
                if saved_bank is not None and 0 <= saved_bank < len(self._bank_ids):
                    self._current_bank = self._bank_ids[saved_bank]
                self._saved_slot_cursor = _cfg.load_ui_int(
                    "slot_cursor", self._config_path
                )
                # The rating filter, likewise clamped rather than trusted:
                # a hand-edited 9 stars is not a filter, it is a typo.
                saved_stars = _cfg.load_ui_int("rating_stars", self._config_path)
                if saved_stars is not None and 0 <= saved_stars <= 5:
                    saved_at_least = _cfg.load_ui_bool(
                        "rating_at_least", self._config_path
                    )
                    self.rating_filter = RatingFilter(
                        stars=saved_stars, at_least=bool(saved_at_least)
                    )
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
            yield DataTable(id="bank-table", cursor_type="row")
            yield DataTable(id="slot-table", cursor_type="row")
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
        ):
            slots.add_column(label, key=key, width=width)
        # Open on the bank that was on screen last time: the left pane's
        # cursor has to sit on it before anything else moves.
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
        # A focus change can reset the slot table's visual cursor, so the
        # saved row is re-applied once the dust settles -- rxved's shape,
        # and for the same reason. The handler's unchanged-bank guard is
        # what makes the queued first highlight harmless: it either matches
        # the bank already shown, or its refill lands and the next event
        # puts the restored bank back.
        if saved_slot_cursor is not None:
            self.set_timer(0.1, lambda: self._restore_slot_cursor(saved_slot_cursor))
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

    def _restore_slot_cursor(self, cursor: int) -> None:
        """Re-apply the saved slot row after focus changes have settled.

        Best-effort and one-shot: the row may not exist any more (a filter
        was remembered with it), so a stale cursor is dropped rather than
        raising out of a timer callback.
        """
        try:
            table = self.query_one("#slot-table", DataTable)
        except LookupError:
            return
        if self._current:
            table.move_cursor(row=min(cursor, len(self._current) - 1))

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
        rating_stars: Any = UNSET,
        rating_at_least: Any = UNSET,
        scan_offer_dismissed: Any = UNSET,
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
        if self._config_path is None:
            return
        from nano import config as _cfg

        try:
            for key, value in (
                ("bank_index", bank_index),
                ("slot_cursor", slot_cursor),
                ("view_mode", view_mode),
                ("rating_stars", rating_stars),
                ("rating_at_least", rating_at_least),
                ("scan_offer_dismissed", scan_offer_dismissed),
            ):
                if value is UNSET:
                    continue
                _cfg.save_ui_state(key, value, self._config_path)
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

    def action_toggle_favorite(self) -> None:
        """Mark or unmark the slot under the cursor. Sends no MIDI."""
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
        self.notify_status(f"{'favourited' if now else 'unfavourited'} {literal(name)}")
        self._refill_keeping_place()

    def _favourite_under_cursor(self):
        """The favourite row for the slot under the cursor, if there is one.

        Tags and notes hang off a favourite, so there is nothing to attach
        them to until `f` has been pressed. Saying so is better than
        silently creating one: the user asked to annotate, not to favourite.
        """
        entry = self._cursor_entry()
        if entry is None or self.favorites is None:
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

    def _fill(self, bank_id: str) -> None:
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
                    key=entry.key,
                )
        finally:
            self._filling = False
        self._detail(0)

    def _detail(self, row: int) -> None:
        if not self._current or row >= len(self._current):
            self.query_one("#detail", Static).update("")
            return
        entry = self._current[row]
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
            f"Bank Select (CC0) [b]{entry.bank.select}[/b] · Program Change "
            f"[b]{entry.program_change}[/b] · {where} · {source}{silent}"
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
                # pane over a newer fill.
                if bank_id != self._current_bank:
                    self._fill(bank_id)
                    self._save_ui_state(bank_index=row)
        elif event.data_table.id == "slot-table":
            self._detail(event.cursor_row)
            # Only save the slot cursor when the slot table is focused --
            # the user is actively navigating. Programmatic cursor moves
            # during startup (while the bank pane has focus) must not
            # overwrite the saved position they are busy restoring.
            if event.data_table.has_focus:
                self._save_ui_state(slot_cursor=event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a slot. It arrives here, not as a binding."""
        if event.data_table.id == "slot-table":
            self.action_select()

    def action_switch_pane(self) -> None:
        left = self.query_one("#bank-table", DataTable)
        right = self.query_one("#slot-table", DataTable)
        (right if left.has_focus else left).focus()

    # --- operations ---------------------------------------------------------

    def action_select(self) -> None:
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
        self._select_worker(self._current[row])

    @work(thread=True)
    def _select_worker(self, entry: banks.Slot) -> None:
        """**MIDI only.** The caller claimed the exchange; this frees it."""
        failure: BaseException | None = None
        try:
            with self._busy_gate, self._lock:
                self.device.select(entry)
        except _BRIDGE_ERRORS as exc:
            failure = exc
        finally:
            self._exchange.release()
        if failure is not None:
            self.call_from_thread(
                self.notify_status, f"select: {failure}", refused=True
            )
            return
        self.call_from_thread(
            self.notify_status,
            f"selected {entry.display} — Bank Select {entry.bank.select} "
            f"then Program Change {entry.program_change} on channel "
            f"{self.device.channel + 1}",
        )

    def action_read_names(self) -> None:
        if self._busy:
            self.notify_status("busy", refused=True)
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
        if self._config_path is None or self._busy:
            return
        if self.catalog or self._has_live_names():
            return
        from nano import config as _cfg

        try:
            if _cfg.load_ui_bool(
                "scan_offer_dismissed", self._config_path, default=False
            ):
                return
        except Exception:
            pass
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
  f         favourite the slot under the cursor
  v         all slots / favourites here / every favourite
  t n       tags, note
  *         rate the slot under the cursor, 0-5
  V         show only slots at/above a star rating
  i         what the unit says it is
  q         quit
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
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from nano import config as cfg

    config_path = getattr(args, "config", None) or cfg.DEFAULT_PATH
    # The family's range checks, before anything is opened: a mistyped
    # channel costs a message rather than a wrong program change sent to a
    # real instrument.
    validate_common(args)

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
    )
    try:
        app.run()
    finally:
        store.close()
        # Never close mid-exchange: waits for the gate to be neither
        # refused nor in progress, then closes.
        with close_when_idle(device, gate=app._busy_gate):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
