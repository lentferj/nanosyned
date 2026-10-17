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

"""The widgets the application opens.

Split out of :mod:`nanosyned.app` so the browser itself stays readable, on
the same shape as :mod:`rxved.screens` and :mod:`emorphed.screens`. This
module holds every widget the application opens. It imports nothing from
:mod:`nanosyned.app`, so the dependency runs one way only and any part of
the program can import it without a cycle.

``ReportScreen`` and ``PromptScreen`` used to be defined in the browser
itself, eight copies of the same class across the family. They are the
library's now -- :mod:`vinsynlib.ui.report` and :mod:`vinsynlib.ui.prompt`,
imported below and re-exported so every call site reads exactly as it did,
with the one difference each sibling keeps: ``enter`` closes the report,
so the frame's words are the library's and the key is this tool's.
"""

from __future__ import annotations

from typing import Any, ClassVar

from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.hints import KeyHints as _LibraryKeyHints
from vinsynlib.ui.prompt import PromptScreen
from vinsynlib.ui.report import ReportScreen as _Frame

__all__ = ["ConfirmScreen", "KeyHints", "PromptScreen", "ReportScreen"]


#: rxved's shape: ``enter`` closes as well. Three lines, no rewrite --
#: so the frame's words are the library's and the only difference is the
#: key that closes it.
class ReportScreen(_Frame):
    """nanosyned's shape: ``enter`` closes as well. Three lines, no rewrite."""

    BINDINGS: ClassVar[list[Any]] = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("enter", "close", "Close"),
    ]


class KeyHints(_LibraryKeyHints):
    """The library legend, relaid out after every re-wrap.

    The library widget re-wraps its text on mount and on resize but never
    asks for a layout, so ``height: auto`` keeps whatever height the first
    render gave it. That first render happens before the widget has a width:
    the wrap falls back to its minimum, the whole legend stacks into about a
    dozen lines, and the footer stays that tall -- a band of empty panel
    under the keys -- until the terminal is resized. Requesting the layout
    after each re-wrap keeps the footer only as tall as the wrapped text,
    which is the point of wrapping it here at all.
    """

    def on_mount(self) -> None:
        super().on_mount()
        self.call_after_refresh(self.refresh, layout=True)

    def on_resize(self) -> None:
        super().on_resize()
        self.call_after_refresh(self.refresh, layout=True)
