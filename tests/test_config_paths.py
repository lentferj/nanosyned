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

"""The suite must not write the application's config into the checkout.

``config.DEFAULT_PATH`` is the relative string ``"config.toml"``. That is
the right default for the application -- it is a disposable per-checkout
cache of which port answered last, gitignored in all four sibling projects,
as distinct from the favourites store, which is the user's own work and
lives in the platform data directory. It is the wrong thing for a test,
which would drop the file into whatever directory pytest was started from.

Being gitignored is what makes this worth a test rather than a habit: the
file never appears in ``git status``, so the only evidence is somebody
noticing it sitting next to the source. One was, dated during a test run.
The sibling rxved had the same shape of bug with backup files and fixed it
in ``1f5aa3a``; p2ked, kwsed and nanosyned all carried the same copied line.
"""

import ast
import os


def _test_sources():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(here)):
        if name.startswith("test_") and name.endswith(".py"):
            with open(os.path.join(here, name), encoding="utf-8") as handle:
                yield name, ast.parse(handle.read())


def _config_saves():
    for name, tree in _test_sources():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr.startswith("save_")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "config"):
                yield name, node


def test_every_config_save_in_the_suite_names_its_file():
    offenders = []
    for name, node in _config_saves():
        # the path is either the last positional argument or path=
        if not (len(node.args) >= 2
                or any(kw.arg == "path" for kw in node.keywords)):
            offenders.append(f"{name}:{node.lineno} {node.func.attr}")
    assert not offenders, (
        f"{offenders} save to config.DEFAULT_PATH, which is relative to the "
        f"working directory. Pass a tmp_path.")


def test_the_check_has_something_to_check():
    """Guard against the search passing because it matched nothing."""
    assert list(_config_saves()), (
        "no config.save_* calls found; the check is vacuous")
