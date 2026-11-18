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

"""Unit-supplied text survives markup: escaping, before a pane dies."""

from textual.content import Content

from nanosyned.text import literal


class TestLiteral:
    """Every ``[`` escaped with a backslash, Textual 8.x's own escape."""

    def test_a_markup_tag_renders_as_itself(self):
        assert literal("[b]x[/b]") == r"\[b]x\[/b]"

    def test_plain_text_copies_through(self):
        assert literal("plain") == "plain"

    def test_a_lone_open_bracket_is_escaped(self):
        assert literal("a[b") == r"a\[b"

    def test_every_name_round_trips_through_the_parser(self):
        names = (
            # The name the returned unit held, which crashed the detail pane:
            # its '[' swallowed the [dim] that followed.
            "/?q[uc?\x7fQE",
            "[b]x[/b]",
            "[/dim]",
            "[quicksort]  ",
            "[g <`-^^",
            "a \\ b",
            "a \\[ b",
            "\\[",
            "no brackets",
        )
        for name in names:
            assert Content.from_markup(literal(name)).plain == name, name

    def test_the_crashing_name_parses_in_the_real_sentence(self):
        name = "/?q[uc?\x7fQE"
        content = f"[b]User 000[/b]  {literal(name)}   [dim]Piano[/dim]"
        rendered = Content.from_markup(content)
        assert rendered.plain.endswith("Piano")
        assert name in rendered.plain

    def test_a_backslash_before_a_bracket_keeps_its_backslash(self):
        assert literal("\\[") == r"\\["
        assert Content.from_markup(literal("\\[")).plain == "\\["
