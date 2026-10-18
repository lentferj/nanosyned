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

"""The mix view model and the mix/global write paths, with no MIDI and no unit.

Every fixture here is invented. The record bytes are built through this
project's own encoders rather than transcribed, so a wrong bit address in the
parameter table cannot hide behind a fixture that was written from the same
wrong address -- the two places a raw byte *is* asserted are noted, and they
come from the spec's arithmetic (10 common bytes plus eight per channel).
"""

import pytest
from textual.widgets import Input

from nano import catalog as cat
from nano import messages as m
from nano import params, verify
from nano import records as rec
from nanosyned import mix as mixview
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import GlobalEditor
from nanosyned.screens import GlobalScreen, MixScreen
from vinsynlib.ui.modals import ChoiceScreen
from vinsynlib.ui.prompt import PromptScreen


def _mix(name: str = "Test Mix") -> bytes:
    """A 138-byte mix with ``name`` and a high bit in the last spare.

    The high bit is channel 15's spare (bit 143 + 15 * 64, the record's last
    bit), so any field edit that reaches past its own block shows up as a
    changed last byte rather than passing unseen.
    """
    record = bytearray(rec.MIX_BYTES)
    m.encode_name(record, name, rec.MIX_NAME_BIT_OFFSET)
    record[-1] = 0x80
    return bytes(record)


class TestDecoding:
    def test_a_synthetic_mix_decodes_channel_by_channel(self):
        record = _mix()
        for label, value in (
            ("program", 42),
            ("program_type", 1),
            ("enable", 1),
            ("volume", 87),
            ("pan", 5),
            ("output", 2),
            ("effect_level", 64),
            ("effect_bus", 3),
        ):
            record = mixview.set_channel_field(record, 0, label, value)
        record = mixview.set_channel_field(record, 15, "program", 127)

        decoded = mixview.channels(record)
        assert len(decoded) == rec.MIX_CHANNELS == 16
        first = decoded[0]
        assert first.channel == 0
        assert (
            first.program,
            first.program_type,
            first.enable,
            first.volume,
            first.pan,
            first.output,
            first.effect_level,
            first.effect_bus,
        ) == (42, 1, True, 87, 5, 2, 64, 3)
        # Channels are independent, and the last one is its own block.
        assert decoded[1].program == 0
        assert decoded[15].program == 127
        # Two raw checks from the spec's arithmetic: the common area is ten
        # bytes and the program field is the low seven bits of each block's
        # first byte -- byte 10 + 8 * channel.
        assert record[rec.MIX_COMMON] & 0x7F == 42
        assert record[rec.MIX_COMMON + 15 * rec.MIX_CHANNEL_BYTES] & 0x7F == 127

    def test_the_name_starts_five_bits_in(self):
        record = _mix("Hello Mix")
        assert mixview.mix_name(record) == "Hello Mix "
        assert mixview.mix_name(record) == rec.mix_name(record)

    def test_a_field_the_table_lacks_is_none_not_a_guess(self, monkeypatch):
        """Honest None: the view model never reads a neighbouring field."""
        real = params.at

        def missing(  # noqa: PLR0913 -- mirrors nano.params.at's signature
            mode, function, page, pot, *, sound=None, channel=None
        ):
            if (function, page, pot) == mixview.FIELD_ADDRESSES["pan"]:
                return None
            return real(mode, function, page, pot, sound=sound, channel=channel)

        monkeypatch.setattr(params, "at", missing)
        decoded = mixview.channels(_mix())
        assert [channel.pan for channel in decoded] == [None] * rec.MIX_CHANNELS
        assert all(channel.program is not None for channel in decoded)
        assert mixview.get_channel_field(_mix(), 3, "pan") is None

    def test_a_short_record_is_refused(self):
        with pytest.raises(m.ProtocolError):
            mixview.channels(bytes(rec.MIX_BYTES - 1))
        with pytest.raises(m.ProtocolError):
            mixview.set_channel_field(bytes(rec.MIX_BYTES - 1), 0, "program", 1)


class TestEditing:
    def test_set_channel_field_is_pure_and_round_trips(self):
        original = _mix()
        changed = mixview.set_channel_field(original, 4, "volume", 33)
        assert changed != original
        assert mixview.get_channel_field(changed, 4, "volume") == 33
        # The argument is untouched and no other channel moved.
        assert mixview.get_channel_field(original, 4, "volume") == 0
        assert mixview.get_channel_field(changed, 3, "volume") == 0
        assert mixview.get_channel_field(changed, 5, "volume") == 0
        # The far spare bit past the last channel block is untouched.
        assert changed[-1] == original[-1]

    def test_values_are_clamped_to_the_documented_range(self):
        record = _mix()
        cases = (
            ("volume", 500, 99),
            ("volume", -5, 0),
            ("pan", 9, 7),
            ("pan", -1, 0),
            ("program", 200, 127),
            ("program", -1, 0),
            ("effect_bus", 9, 4),
        )
        for label, asked, expected in cases:
            changed = mixview.set_channel_field(record, 0, label, asked)
            assert mixview.get_channel_field(changed, 0, label) == expected, label

    def test_an_unknown_field_or_channel_is_a_caller_error(self):
        with pytest.raises(ValueError):
            mixview.set_channel_field(_mix(), 0, "reverb", 1)
        with pytest.raises(ValueError):
            mixview.set_channel_field(_mix(), rec.MIX_CHANNELS, "program", 1)
        with pytest.raises(ValueError):
            mixview.param_for(0, "reverb")


class TestGlobalEditor:
    def test_every_documented_row_is_shown_and_the_specials_are_not_writable(self):
        editor = GlobalEditor(bytes(rec.GLOBAL_BYTES))
        rows = editor.rows()
        assert len(rows) == len(params.GLOBAL_PARAMS)
        writable = [row.param.label for row in rows if row.writable]
        assert "Pitch transpose*" in writable
        assert "General MIDI" in writable
        # The model-specific rows, the deleted parameters and rows with no
        # direct-edit address are shown with the reason they are not written.
        curve = next(row for row in rows if "Keyboard curve" in row.param.label)
        assert curve.writable is False
        assert "QS6/7/8" in (curve.refusal or "")
        spare = next(row for row in rows if "deleted parameter" in row.param.label)
        assert spare.writable is False
        assert "deleted parameter" in (spare.refusal or "")
        clock = next(row for row in rows if row.param.label.startswith("Clock"))
        assert clock.writable is False

    def test_a_signed_row_round_trips_in_twos_complement(self):
        editor = GlobalEditor(bytes(rec.GLOBAL_BYTES))
        assert editor.set_value("Pitch transpose*", -7) is None
        assert editor.value(params.by_label("Pitch transpose")[0]) == -7
        # Byte 1 holds Pitch transpose, right-justified; -7 is 0xF9.
        assert editor.record()[1] == 0xF9
        assert editor.dirty is True
        editor.reset()
        assert editor.dirty is False
        assert editor.record()[1] == 0

    def test_a_value_is_clamped_and_a_refused_row_will_not_move(self):
        editor = GlobalEditor(bytes(rec.GLOBAL_BYTES))
        assert editor.set_value("Pitch transpose*", 99) is None
        assert editor.value(params.by_label("Pitch transpose")[0]) == 12
        before = editor.record()
        problem = editor.set_value("Keyboard curve *(QS6,7,8 only)", 1)
        assert problem is not None
        assert "QS6/7/8" in problem
        assert editor.record() == before
        # A refusal on an untouched record leaves it untouched, so the
        # screen's arm step cannot be reached by a row it will not write.
        fresh = GlobalEditor(bytes(rec.GLOBAL_BYTES))
        assert fresh.set_value("Keyboard curve *(QS6,7,8 only)", 1) is not None
        assert fresh.dirty is False

    def test_a_dump_that_predates_a_row_says_so(self):
        """Software before 2.00 carries seventeen bytes, not twenty."""
        editor = GlobalEditor(bytes(17))
        general_midi = next(
            row for row in editor.rows() if row.param.label == "General MIDI"
        )
        assert general_midi.value is None
        assert general_midi.writable is False
        assert "predates" in (general_midi.refusal or "")


class _AppCase:
    """The plumbing the app tests share: a wait and a backup recorder."""

    @staticmethod
    def _backup_into(monkeypatch, tmp_path, saved, *, before_write=None):
        from nano import backup as bk

        def save(slot, *, kind, name, blocks, **kwargs):
            if before_write is not None:
                before_write()
            saved.append(
                {"slot": slot, "kind": kind, "name": name, "blocks": dict(blocks)}
            )
            return str(tmp_path / f"{kind}.backup.json")

        monkeypatch.setattr(bk, "save", save)

    @staticmethod
    async def _wait(pilot, predicate, tries=200):
        for _ in range(tries):
            await pilot.pause()
            if predicate():
                return
        assert predicate(), "the worker never finished"


class TestMixStore(_AppCase):
    async def test_the_store_writes_once_reads_back_and_backs_up(
        self, monkeypatch, tmp_path
    ):
        saved = []
        writes_at_backup = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        self._backup_into(
            monkeypatch,
            tmp_path,
            saved,
            before_write=lambda: writes_at_backup.append(len(app.device.mix_writes)),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_mix(0)
            changed = mixview.set_channel_field(original, 2, "volume", 42)
            app._mix_edited(0, changed)
            await self._wait(pilot, lambda: len(app._undo_log) == 1)

            assert len(app.device.mix_writes) == 1
            number, written = app.device.mix_writes[0]
            assert number == 0
            assert verify.mismatches(changed, written) == []
            read_back = app.device.read_mix(0)
            assert verify.mismatches(changed, read_back) == []
            # The backup happened first, and holds what the mix held then.
            assert writes_at_backup == [0]
            assert len(saved) == 1
            assert saved[0]["slot"] == "mix:000"
            assert saved[0]["kind"] == "mix"
            assert saved[0]["blocks"]["mix"] == original
            assert saved[0]["name"] == rec.mix_name(original).rstrip()

    async def test_m_while_locked_refuses_and_reads_nothing(self):
        reads = []

        class CountingDevice(DemoDevice):
            def read_mix(self, number, *, timeout=None):
                reads.append(number)
                return super().read_mix(number, timeout=timeout)

        app = NanosynedApp(CountingDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            for _ in range(8):
                await pilot.pause()
            assert not isinstance(app.screen, PromptScreen)
            assert reads == []
            assert app.device.mix_writes == []
            assert "write gate" in str(app.query_one("#status").content)

    async def test_m_picks_the_mix_and_the_screen_stages_then_stores(
        self, monkeypatch, tmp_path
    ):
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "7"
            await pilot.press("enter")
            await self._wait(pilot, lambda: isinstance(app.screen, MixScreen))

            # Stage volume 44 on channel 1 through the two small dialogs.
            await pilot.press("e")
            await self._wait(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            app.screen.dismiss(1)  # "volume"
            await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "44"
            await pilot.press("enter")
            await self._wait(pilot, lambda: isinstance(app.screen, MixScreen))
            assert (
                mixview.get_channel_field(app.device.read_mix(7), 0, "volume") == 0
            ), "a staged edit must not have been sent"

            await pilot.press("a")
            await pilot.pause()
            assert app.screen.armed is True
            # Any key but `w` is a change of mind, not a store.
            await pilot.press("x")
            await pilot.pause()
            assert app.screen.armed is False
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("w")
            await self._wait(pilot, lambda: len(app._undo_log) == 1)
            assert len(app.device.mix_writes) == 1
            assert app.device.mix_writes[0][0] == 7
            assert mixview.get_channel_field(app.device.read_mix(7), 0, "volume") == 44

    async def test_z_puts_the_mix_back(self, monkeypatch, tmp_path):
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_mix(0)
            changed = mixview.set_channel_field(original, 5, "program", 12)
            app._mix_edited(0, changed)
            await self._wait(pilot, lambda: len(app._undo_log) == 1)
            assert app.device.read_mix(0) != original

            await pilot.press("z")
            await self._wait(pilot, lambda: len(app.device.mix_writes) == 2)
            for _ in range(10):
                await pilot.pause()
            assert app.device.mix_writes[-1] == (0, original)
            assert app.device.read_mix(0) == original


class TestGlobalStore(_AppCase):
    async def test_g_opens_edits_and_stores_with_a_backup_and_undo(
        self, monkeypatch, tmp_path
    ):
        saved = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        self._backup_into(monkeypatch, tmp_path, saved)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_global()
            await pilot.press("g")
            await self._wait(pilot, lambda: isinstance(app.screen, GlobalScreen))
            # Row 1 is Pitch transpose (row 0 is a deleted spare).
            app.screen.query_one("#global-table").move_cursor(row=1)
            await pilot.pause()
            await pilot.press("e")
            await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "7"
            await pilot.press("enter")
            await self._wait(pilot, lambda: isinstance(app.screen, GlobalScreen))
            assert app.device.global_writes == []

            await pilot.press("a")
            await pilot.pause()
            assert app.screen.armed is True
            await pilot.press("x")
            await pilot.pause()
            assert app.screen.armed is False
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("w")
            await self._wait(pilot, lambda: len(app._undo_log) == 1)

            assert len(app.device.global_writes) == 1
            assert (
                rec.global_record_bytes(app.device.read_global())["Pitch transpose*"]
                == 7
            )
            assert saved[0]["slot"] == "global"
            assert saved[0]["kind"] == "global"
            assert saved[0]["blocks"]["global"] == original

            await pilot.press("z")
            await self._wait(pilot, lambda: len(app.device.global_writes) == 2)
            for _ in range(10):
                await pilot.pause()
            assert app.device.read_global() == original

    async def test_a_model_specific_row_is_refused_by_the_screen(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g")
            await self._wait(pilot, lambda: isinstance(app.screen, GlobalScreen))
            screen = app.screen
            curve = next(
                index
                for index, row in enumerate(screen.editor.rows())
                if "Keyboard curve" in row.param.label
            )
            screen.query_one("#global-table").move_cursor(row=curve)
            await pilot.pause()
            await pilot.press("e")
            for _ in range(6):
                await pilot.pause()
            assert isinstance(app.screen, GlobalScreen)
            assert "QS6/7/8" in str(screen.query_one("#global-status").content)
            assert app.device.global_writes == []

    async def test_g_while_locked_refuses_and_reads_nothing(self):
        reads = []

        class CountingDevice(DemoDevice):
            def read_global(self, *, timeout=None):
                reads.append(True)
                return super().read_global(timeout=timeout)

        app = NanosynedApp(CountingDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("g")
            for _ in range(8):
                await pilot.pause()
            assert not isinstance(app.screen, GlobalScreen)
            assert reads == []
            assert app.device.global_writes == []
            assert "write gate" in str(app.query_one("#status").content)


class TestModeSelect(_AppCase):
    async def test_M_sends_nothing_until_a_mode_is_chosen(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("M")
            await self._wait(pilot, lambda: isinstance(app.screen, ChoiceScreen))
            assert app.device.mode_selects == []
            app.screen.dismiss(1)
            await self._wait(pilot, lambda: len(app.device.mode_selects) == 1)
            assert app.device.mode_selects == [True]
            # Not a store: no backup, no undo entry, nothing read back.
            assert app.device.global_writes == []
            assert len(app._undo_log) == 0

    async def test_M_while_locked_does_not_even_open_the_dialog(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("M")
            for _ in range(6):
                await pilot.pause()
            assert not isinstance(app.screen, ChoiceScreen)
            assert app.device.mode_selects == []
            assert "write gate" in str(app.query_one("#status").content)
