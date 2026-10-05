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

"""What the Alesis calls things, declared once.

**The instrument's word is the instrument's.** The NanoSynth's own front
panel and manual say PROGRAM and BANK, so those are the words every string
a user reads uses here -- the list view, the pane headings, the help, the
README.

The wire's word is different and stays in the code that builds wire
messages: on the wire this is reached by Controller 0 (Bank Select) and a
program change, and this unit ignores Controller 32 entirely, which is the
detail that costs people an afternoon. That is a protocol fact rather than
a naming one, so it stays in ``nano.banks``.
"""

from __future__ import annotations

from vinsynlib.terms import Terminology, register

__all__ = ["TERMS"]

TERMS = Terminology(
    app_name="nanosyned",
    sound="program",
    container="bank",
    device="Alesis NanoSynth",
)

#: Registered at import so the family's registry knows what this tool calls
#: its concepts. Registration rather than a monkeypatched module global: a
#: library cannot know the name of the program using it, and passing it in
#: is honest where patching is global.
register(TERMS)
