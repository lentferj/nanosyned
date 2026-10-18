# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""``nanocli fav`` and ``nanocli tags``, end to end and entirely offline."""

import pytest

from nano.favorites import Favorites
from nanosyned import cli

USER_1 = "USER"
NUMBER_1 = 1
NUMBER_2 = 2
NUMBER_3 = 3


def _argv(tmp_path, *argv):
    return ["--favorites", str(tmp_path / "favorites.db"), *argv]


def _args(tmp_path, *argv):
    return cli.build_parser().parse_args(_argv(tmp_path, *argv))


def _fav(args):
    return Favorites(args.favorites)


def _listed(capsys):
    """The ``#`` column of every favourites row printed so far."""
    lines = capsys.readouterr().out.splitlines()
    rows = []
    for line in lines:
        if not line.startswith("USER"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) >= 2:
            rows.append(parts[1])
    return rows


class TestRate:
    def test_it_sets_the_rating_and_leaves_the_rest_alone(self, tmp_path) -> None:
        args = _args(
            tmp_path, "fav", "USER", "1", "--add", "--rate", "4", "--tags", "lead"
        )
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "USER", "1", "--rate", "2")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(USER_1, NUMBER_1)
            assert found is not None
            assert (found.rating, found.tags) == (2, "lead")

    def test_it_refuses_a_slot_that_is_not_a_favourite(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "USER", "3", "--rate", "3")
        with pytest.raises(SystemExit) as caught:
            cli._cmd_fav(None, args)
        assert "not a favourite" in str(caught.value)
        with _fav(args) as store:
            assert store.get(USER_1, NUMBER_3) is None

    def test_a_rating_outside_zero_to_five_is_one_line_not_a_traceback(
        self, tmp_path
    ) -> None:
        args = _args(tmp_path, "fav", "USER", "1", "--add")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "USER", "1", "--rate", "9")
        with pytest.raises(SystemExit) as caught:
            cli._cmd_fav(None, args)
        assert "--rate wants 0-5" in str(caught.value)
        with _fav(args) as store:
            found = store.get(USER_1, NUMBER_1)
            assert found is not None
            assert found.rating == 0


class TestAddIsNotAWipe:
    def test_re_adding_without_a_rating_keeps_it(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "USER", "1", "--add", "--rate", "5")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "USER", "1", "--add")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(USER_1, NUMBER_1)
            assert found is not None
            assert found.rating == 5

    def test_re_adding_with_a_rating_replaces_only_that(self, tmp_path) -> None:
        args = _args(
            tmp_path, "fav", "USER", "1", "--add", "--rate", "5", "--note", "top"
        )
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "USER", "1", "--add", "--rate", "1")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(USER_1, NUMBER_1)
            assert found is not None
            assert (found.rating, found.note) == (1, "top")

    def test_add_rejects_a_rating_outside_zero_to_five(self, tmp_path) -> None:
        for bad in ("7", "-1"):
            args = _args(tmp_path, "fav", "USER", "1", "--add", "--rate", bad)
            with pytest.raises(SystemExit) as caught:
                cli._cmd_fav(None, args)
            assert "--rate wants 0-5" in str(caught.value)
        args = _args(tmp_path, "fav")
        with _fav(args) as store:
            assert store.get(USER_1, NUMBER_1) is None


class TestAnnotations:
    def test_tags_and_note_create_the_favourite(self, tmp_path) -> None:
        args = _args(tmp_path, "fav", "USER", "4", "--tags", "pad, warm")
        cli._cmd_fav(None, args)
        args = _args(tmp_path, "fav", "USER", "4", "--note", "for the intro")
        cli._cmd_fav(None, args)
        with _fav(args) as store:
            found = store.get(USER_1, 4)
            assert found is not None
            assert (found.tags, found.note) == ("pad, warm", "for the intro")

    def test_an_action_without_a_slot_is_one_line_not_a_traceback(
        self, tmp_path
    ) -> None:
        args = _args(tmp_path, "fav", "--add")
        with pytest.raises(SystemExit) as caught:
            cli._cmd_fav(None, args)
        assert "give a bank and a number" in str(caught.value)


class TestListing:
    def _seeded(self, tmp_path):
        for number, rating, tags in (
            (NUMBER_1, "5", "lead"),
            (NUMBER_2, "3", "pad"),
            (NUMBER_3, "0", ""),
        ):
            argv = ["fav", "USER", str(number), "--add", "--rate", rating]
            if tags:
                argv += ["--tags", tags]
            cli._cmd_fav(None, _args(tmp_path, *argv))
        return _args(tmp_path, "fav")

    def test_at_least_keeps_the_rated_and_up(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-at-least", "3"))
        assert _listed(capsys) == ["002", "001"]

    def test_it_stacks_on_a_tag_filter(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(
            None,
            _args(tmp_path, "fav", "--tag", "lead", "--rating-at-least", "3"),
        )
        assert _listed(capsys) == ["001"]

    def test_search_finds_a_note(self, tmp_path, capsys) -> None:
        args = _args(tmp_path, "fav", "USER", "2", "--note", "bell-like")
        cli._cmd_fav(None, args)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--search", "bell"))
        assert _listed(capsys) == ["002"]

    def test_bank_order_is_the_slot_order(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--order", "bank"))
        assert _listed(capsys) == ["001", "002", "003"]

    def test_the_column_shows_the_stars(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--rating-at-least", "5"))
        out = capsys.readouterr().out
        assert "★★★★★" in out

    def test_nothing_matching_says_so_and_exits_zero(self, tmp_path, capsys) -> None:
        self._seeded(tmp_path)
        cli._cmd_fav(None, _args(tmp_path, "fav", "--tag", "zzz"))
        assert "no favourites" in capsys.readouterr().err


class TestParser:
    def test_add_and_remove_together_is_a_usage_error(self, tmp_path, capsys) -> None:
        with pytest.raises(SystemExit):
            _args(tmp_path, "fav", "USER", "1", "--add", "--remove")
        assert "not allowed with" in capsys.readouterr().err

    def test_favorites_is_an_alias_for_fav(self, tmp_path) -> None:
        args = _args(tmp_path, "favorites")
        assert args.command == "favorites"
        cli._cmd_fav(None, args)

    def test_the_store_path_may_follow_the_subcommand(self, tmp_path) -> None:
        # The smoke command people type is `tags --favorites PATH`; argparse
        # only takes a parent's option before the subcommand, so the two
        # subcommands that read the store declare it again.
        args = cli.build_parser().parse_args(
            ["tags", "--favorites", str(tmp_path / "other.db")]
        )
        assert args.favorites == str(tmp_path / "other.db")

    def test_the_store_path_before_the_subcommand_still_wins(self, tmp_path) -> None:
        path = str(tmp_path / "before.db")
        args = cli.build_parser().parse_args(["--favorites", path, "tags"])
        assert args.favorites == path


class TestTagsCommand:
    def test_it_counts_each_tag(self, tmp_path, capsys) -> None:
        cli._cmd_fav(
            None,
            _args(tmp_path, "fav", "USER", "1", "--tags", "lead, bright"),
        )
        cli._cmd_fav(
            None,
            _args(tmp_path, "fav", "USER", "2", "--tags", "lead"),
        )
        cli._cmd_tags(None, _args(tmp_path, "tags"))
        out = capsys.readouterr().out
        rows = [
            [part.strip() for part in line.split("|")]
            for line in out.splitlines()
            if "lead" in line or "bright" in line
        ]
        assert ["lead", "2"] in rows
        assert ["bright", "1"] in rows

    def test_an_empty_store_says_no_tags(self, tmp_path, capsys) -> None:
        cli._cmd_tags(None, _args(tmp_path, "tags"))
        assert "no tags" in capsys.readouterr().err
