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

r"""Textual renders widget text as console markup, so unit text is escaped.

Any string that came from the instrument -- a User-bank program name, a
tag, a note, a search hit -- can contain `[`, and an unclosed markup tag
kills the pane. Names read from hardware are user-editable, so this is
reachable: nobody stops a panel from naming a program `[quicksort]`.
Everything from the device or the user goes through `literal()` before it
meets a markup-parsing widget; the project's own `[b]`/`[dim]` styling
does not, because the project knows what it wrote.

**Textual's escape is a backslash, not a doubled bracket.** From 8.x,
`Content.from_markup` (which `Static.update` uses) treats `\[` as a
literal `[`; a doubled `[[` is not an escape, and a stray `[` swallows the
next real tag -- which is how a unit name like `/?q[uc?` crashed the
detail pane with "closing tag '[/dim]' does not match any open tag".

This module imports nothing from the rest of :mod:`nanosyned`, so any part
of the app can quote it without a cycle.
"""

from __future__ import annotations

__all__ = ["literal"]


def literal(text: str) -> str:
    r"""``text`` escaped so markup renders it exactly as written.

    Every ``[`` becomes ``\[``, Textual 8.x's escape a literal bracket. A
    backslash *immediately before* a bracket needs one more of its own
    (``\\[``), because the parser consumes the pair; every other
    backslash copies through. A closing ``]`` carries no state on its own.
    """
    chars = str(text)
    out: list[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if char == "\\" and index + 1 < len(chars) and chars[index + 1] == "[":
            out.append("\\\\[")
            index += 2
            continue
        out.append("\\[" if char == "[" else char)
        index += 1
    return "".join(out)
