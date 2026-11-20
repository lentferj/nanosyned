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

"""nanosyned keeps the contract the other eight projects in the family keep.

Every check below is the same one, run against this program rather than
written out again here. The reasons are in docs/UX-SPEC.md section 5 and
in the library: what drifted was never a bug anyone chose, it was a copy
that nobody had a second copy to compare against.
"""

from nano.terms import TERMS
from nanosyned import cli
from nanosyned.app import KEY_HINTS, WRITE_HINTS, NanosynedApp, build_parser
from vinsynlib import conformance
from vinsynlib.config import config_help


def test_flags_match_the_family() -> None:
    # A tuple rather than the set in the template: check_flags takes a
    # Sequence, and mypy is right that a set is not one.
    #
    # --config is checked separately below. The family's spec still spells
    # the old relative default (./config.toml); this tool binds the per-tool
    # platform path (D01), so the family's literal is the one thing that must
    # differ. Everything else about the flag is still checked.
    assert not conformance.check_flags(
        build_parser(),
        required=("port", "scan", "recv-port", "demo", "catalog"),
    )


def test_the_cli_flags_match_the_family() -> None:
    # The command line keeps the same contract as the browser, from the
    # same table. `favorites` is the store `fav` and `tags` open, so it is
    # part of what this CLI offers and is checked as such. --config is
    # excluded here for the same reason it is above, and checked separately.
    assert not conformance.check_flags(
        cli.build_parser(),
        required=(
            "port",
            "scan",
            "recv-port",
            "channel",
            "demo",
            "catalog",
            "favorites",
            "yes",
            "allow-write",
        ),
    )


def test_the_config_flag_names_this_tools_own_cache() -> None:
    """The one deliberate difference from the family's flag text."""
    for parser in (build_parser(), cli.build_parser()):
        action = next(a for a in parser._actions if a.dest == "config")
        assert action.help == config_help("nanosyned")
        assert "--config" in action.option_strings


def test_keys_match_the_family() -> None:
    # select=False, and the reason is in nanosyned/app.py: a focused
    # DataTable consumes Enter for its own row selection, so it arrives as
    # RowSelected and calls action_select from there. The key works and the
    # legend promises it; what it cannot be is a BINDINGS entry, because
    # binding it would mean the App taking Enter from the table and every
    # other table key with it. Checked from the other side below.
    problems = conformance.check_bindings(
        NanosynedApp, favourites=True, channel=True, select=False
    )
    assert not problems, "\n".join(problems)


def test_the_legend_matches_the_family() -> None:
    # The two rating hints are this tool's own, and so is `S scan device`
    # -- the family has no scan key and this instrument has one readable
    # bank. They are passed as extras on both sides, so they sit in the
    # family's gap after `n note` and are checked for order like every
    # shared hint. test_favorites.py checks that every binding appears.
    problems = conformance.check_legend(
        KEY_HINTS,
        extras=("S scan device", "* rating", "V rating filter", *WRITE_HINTS),
    )
    assert not problems, "\n".join(problems)


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)
