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

from nanosyned.text import literal


class TestLiteral:
    """Every '[' doubled is Textual's own escape for a literal one."""

    def test_a_markup_tag_renders_as_itself(self):
        assert literal("[b]x[/b]") == "[[b]x[[/b]"

    def test_plain_text_copies_through(self):
        assert literal("plain") == "plain"

    def test_a_lone_open_bracket_is_doubled(self):
        assert literal("a[b") == "a[[b"

    def test_no_unescaped_bracket_survives(self):
        """Whatever the name carries, a markup parse has no tag to choke on."""
        for name in ("[g <`-^^", "[b]x[/b]", "[/dim]", "[quicksort]  "):
            escaped = literal(name)
            assert "[" not in escaped.replace("[[", "")
