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

"""Favourites. Names here are invented."""

from typing import ClassVar

from nano.favorites import Favorites
from nanosyned.app import (
    KEY_HINTS,
    VIEW_ALL,
    VIEW_ALL_FAVOURITES,
    VIEW_BANK_FAVOURITES,
    VIEW_CYCLE,
    NanosynedApp,
)


class TestStore:
    def test_the_slot_is_the_identity_not_the_name(self, tmp_path):
        db = str(tmp_path / "f.db")
        with Favorites(db) as store:
            store.add("USER", 7, name="Glass Meridian")
        with Favorites(db) as store:
            store.add("USER", 7, name="renamed entirely")
            assert len(store) == 1

    def test_the_same_number_in_two_banks_is_two_favourites(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("USER", 7)
            store.add("B", 7)
            assert len(store) == 2


class TestTheCycle:
    def test_three_steps_starting_at_all(self):
        assert len(VIEW_CYCLE) == 3
        assert VIEW_CYCLE[0] == VIEW_ALL
        assert set(VIEW_CYCLE) == {VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES}

    def test_it_wraps(self):
        seen, mode = [], VIEW_ALL
        for _ in range(4):
            seen.append(mode)
            mode = VIEW_CYCLE[(VIEW_CYCLE.index(mode) + 1) % len(VIEW_CYCLE)]
        assert seen == [*VIEW_CYCLE, VIEW_ALL]

    def test_the_keys_are_in_the_legend(self):
        legend = " ".join(KEY_HINTS)
        assert "f favourite" in legend
        # The favourites view is on `v`, not the family's `F`: `f` writes the
        # database and cycling the view only reads it, so the shift-pair left
        # a write one slip away from a read. rxved, p2ked and emorphed moved
        # off `F` for the same reason.
        assert "v favourites" in legend


class TestTheChannelIsRemembered:
    """The channel set last time should be the default next time.

    rxved had the save function from its first commit and never called it,
    so it loaded a channel from a file nothing ever wrote. The round trip is
    what makes that impossible to repeat quietly.
    """

    def test_saving_then_loading_round_trips(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        config.save_channel(9, path)
        assert config.load_channel(path) == 9

    def test_another_setting_does_not_drop_it(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        config.save_channel(5, path)
        config.save_last_port("some port", path)
        assert config.load_channel(path) == 5
        assert config.load_last_port(path) == "some port"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        from nano import config

        assert config.load_channel(str(tmp_path / "nope.toml")) is None

    def test_an_out_of_range_channel_is_ignored(self, tmp_path):
        """A hand-edited file must not put the app on channel 99."""
        from nano import config

        path = str(tmp_path / "config.toml")
        path_obj = tmp_path / "config.toml"
        path_obj.write_text("channel = 99\n", encoding="utf-8")
        assert config.load_channel(path) is None

    def test_an_unparsable_file_is_not_fatal(self, tmp_path):
        from nano import config

        path_obj = tmp_path / "config.toml"
        path_obj.write_text("this is not toml = = =\n", encoding="utf-8")
        assert config.load_channel(str(path_obj)) is None


class TestTheLegendIsComplete:
    """A legend that omits a key teaches the user the key does not exist."""

    #: Textual key names are not what a legend prints.
    SHOWN_AS: ClassVar[dict[str, str]] = {
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "slash": "/",
        "question_mark": "?",
        "asterisk": "*",
    }
    IMPLIED: ClassVar[set[str]] = {"enter", "tab"}

    def test_every_binding_appears(self):
        legend = " ".join(KEY_HINTS)
        missing = []
        for binding in NanosynedApp.BINDINGS:
            if binding.key in self.IMPLIED:
                continue
            shown = self.SHOWN_AS.get(binding.key, binding.key)
            if f"{shown} " not in legend:
                missing.append(binding.key)
        assert not missing, f"bound but missing from the legend: {missing}"


class TestUnfavouritingKeepsWhatTheUserTyped:
    """Un-favouriting used to delete the row, annotations and all.

    `f` in the browser unfavourites without asking, so a rating, tags, a
    note and the date it was first favourited were one keystroke from
    destruction -- on the one store this project calls the user's own. The
    row is now kept with its `active` flag cleared, and the same keystroke
    brings it back.
    """

    def test_a_toggle_cycle_keeps_rating_tags_and_note(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("BANK", 5, name="Invented", rating=4, tags="a, b", note="hello")
            before = store.get("BANK", 5)

            assert store.toggle("BANK", 5) is False
            assert store.get("BANK", 5) is None
            assert store.toggle("BANK", 5) is True

            after = store.get("BANK", 5)
            assert (after.rating, after.tags, after.note) == (4, "a, b", "hello")
            assert after.added == before.added

    def test_an_unfavourited_slot_is_not_a_favourite(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("BANK", 5, name="Invented", rating=3)
            store.remove("BANK", 5)
            assert len(store) == 0
            assert store.keys() == set()
            assert store.all() == []
            assert store.search("Invented") == []

    def test_forget_really_deletes(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("BANK", 5, name="Invented", rating=3)
            store.remove("BANK", 5)
            assert [f.rating for f in store.dormant()] == [3]
            assert store.forget("BANK", 5) is True
            assert store.dormant() == []

    def test_a_v1_database_upgrades_without_losing_rows(self, tmp_path):
        import sqlite3

        path = str(tmp_path / "old.db")
        db = sqlite3.connect(path)
        db.executescript(
            """
            CREATE TABLE favorites (
                bank_id TEXT NOT NULL, number INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                rating INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                added REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (bank_id, number));
            """
        )
        db.execute(
            "INSERT INTO favorites (bank_id, number, name, rating) "
            "VALUES ('BANK', 7, 'Invented', 5)"
        )
        db.execute("PRAGMA user_version = 1")
        db.commit()
        db.close()

        with Favorites(path) as store:
            kept = store.get("BANK", 7)
            assert kept is not None, "an existing row must stay a favourite"
            assert kept.rating == 5


class TestTheConfigIsWrittenSafely:
    """A quote in a port name once made the file unparsable for good.

    ALSA client names are arbitrary, and `_update` refuses to overwrite a
    file it cannot parse -- the right refusal, and the reason the cache
    never healed. Every sibling had some version of this.
    """

    def test_a_quoted_port_name_round_trips(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        nasty = 'Odd "quoted"\tport\\with slash'
        config.save_last_port(nasty, path)
        assert config.load_last_port(path) == nasty

    def test_the_cache_heals(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        config.save_last_port('has a " in it', path)
        config.save_last_port("a sane port", path)
        assert config.load_last_port(path) == "a sane port"

    def test_the_channel_round_trips(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        config.save_channel(9, path)
        assert config.load_channel(path) == 9

    def test_one_setting_does_not_drop_another(self, tmp_path):
        from nano import config

        path = str(tmp_path / "config.toml")
        config.save_channel(5, path)
        config.save_last_port("some port", path)
        assert config.load_channel(path) == 5
        assert config.load_last_port(path) == "some port"


class TestABoolIsNotANumber:
    """`isinstance(True, int)` is True, and every range check passes for
    it. A hand-edited `channel = true` came back as `True`, and
    `0xC0 | True` is `0xC1` -- MIDI channel 2 when channel 1 was asked
    for. A wrong channel is not an error anywhere: the instrument plays
    nothing, or something else does.

    The device-ID guard was written first and this one was missed, one
    function away in the same file, in all seven projects. That is the
    reason this test walks *every* loader rather than naming two.
    """

    def _loaders(self):
        import importlib

        module = importlib.import_module("nano.config")
        for name, fn in vars(module).items():
            if not name.startswith("load_") or not callable(fn):
                continue
            hints = getattr(fn, "__annotations__", {})
            if "int" in str(hints.get("return", "")):
                yield name, fn

    def test_there_are_numeric_loaders_to_check(self):
        assert list(self._loaders()), "the search matched nothing"

    def test_no_numeric_loader_accepts_true(self, tmp_path):
        offenders = []
        for name, fn in self._loaders():
            key = name[len("load_") :]
            path = str(tmp_path / f"{key}.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"{key} = true\n")
            if fn(path) is not None:
                offenders.append(name)
        assert not offenders, f"{offenders} accept a TOML boolean as a number"

    def test_no_numeric_loader_accepts_an_absurd_value(self, tmp_path):
        offenders = []
        for name, fn in self._loaders():
            key = name[len("load_") :]
            path = str(tmp_path / f"{key}.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"{key} = 9999\n")
            if fn(path) is not None:
                offenders.append(name)
        assert not offenders, f"{offenders} accept an out-of-range number"
