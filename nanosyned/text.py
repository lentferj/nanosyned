# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The escaping of unit-supplied text is ported from the sibling emorphed
# and rxved projects, which fix the same bug, and which carry the same
# licence:
#   Copyright (C) 2026  emorphed / rxved contributors
#                                     - GPL-2.0-or-later
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

"""Textual renders widget text as console markup, so unit text is escaped.

Any string that came from the instrument -- a User-bank program name, a
tag, a note, a search hit -- can contain `[, and an unclosed markup tag
kills the pane. Names read from hardware are user-editable, so this is
reachable: nobody stops a panel from naming a program `[quicksort]`.
Everything from the device or the user goes through `literal()` before it
meets a markup-parsing widget; the project's own `[b]`/`[dim]` styling
does not, because the project knows what it wrote.

This module imports nothing from the rest of :mod:`nanosyned`, so any part
of the app can quote it without a cycle.
"""

from __future__ import annotations

__all__ = ["literal"]


def literal(text: str) -> str:
    """``text`` escaped so markup renders it exactly as written.

    The reliable escape is to double every ``[`` -- Textual's documented
    markup escape for a literal bracket, since a doubled ``[[`` displays
    as ``[``. A closing ``]`` carries no state on its own, so it and every
    other character copy through untouched.
    """
    return str(text).replace("[", "[[")
