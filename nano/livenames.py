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
#
# A thin binding of vinsynlib.livenames, which holds the format, the lenient
# reader and the write-then-rename save. That code is the library's; credit
# for it belongs there.

"""Names read off the unit, kept between runs.

The live layer -- the names read off the unit rather than out of the
generated catalog -- is expensive to get and true only as of the moment it
was read. It is cached here, in a per-project sidecar file, and loaded at
startup so the browser shows the right names *before* anything has talked
to the unit; the hardware read that follows confirms them and is saved
back through this module, so the next start is right again without one.

Deliberately not inside the catalog file. That file is generated from the
manufacturer's own documentation, and the printed-versus-live distinction
is the whole point of having two name sources: a cache of one
instrument's current contents does not belong in a document describing
what the manual says, and overwriting one with the other would destroy
the disagreement the browser exists to show.

The sidecar sits beside whichever catalog is in use -- see :func:`path_for`
-- so a catalog and the names read against it travel together. A missing
file is normal and means nothing has been read yet; a corrupt one is worth
a warning rather than an exception, because names are a convenience and
refusing to open the browser over one would be the wrong trade. The
format, the lenient reader and the safe save are
:mod:`vinsynlib.livenames`'s and live in one place.
"""

from __future__ import annotations

import os

from nano import catalog as cat
from vinsynlib import livenames

__all__ = ["FILE_NAME", "apply_to", "key", "load", "path_for", "save"]

#: The filename, beside the project's own catalog file.
FILE_NAME = livenames.FILE_NAME


def path_for(catalog_path: str | None = None) -> str:
    """The sidecar beside ``catalog_path``, or beside the built-in catalog.

    The live names are one instrument's current contents, read against a
    particular catalog's bank layout, so the two files travel together:
    point the browser at another catalog and it reads that catalog's
    names, not this one's.
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(catalog_path or cat.DEFAULT_PATH)),
        FILE_NAME,
    )


#: Thin delegations, re-exported. The library's reader and writer each want
#: an explicit path; :func:`path_for` supplies it at the call site, so the
#: default is not guessed here.
load = livenames.load
save = livenames.save
apply_to = livenames.apply_to
key = livenames.key
