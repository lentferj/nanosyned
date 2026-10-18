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

"""Print the file paths of the modules held to ``--strict``.

The strict-module list is the per-module ``[[tool.mypy.overrides]]`` blocks in
``pyproject.toml`` that carry the individual checks ``strict`` would enable —
the same opt-in shape :file:`docs/CHECKS.md` describes. The count can only
grow, so ``make typecheck-strict`` runs ``mypy --strict`` over exactly those
modules and nothing else.

One implementation, in the repository rather than in a virtualenv, so a fresh
checkout and a CI runner resolve the same list the developer's ``make`` does.
"""

from __future__ import annotations

import os
import sys
import tomllib

#: The keys that mark a ``[[tool.mypy.overrides]]`` block as a strict opt-in.
#: ``rtmidi`` is a block like any other, but it is a third-party stub waiver
#: (``ignore_missing_imports``), not a strictness promise, so it has none of
#: these and is skipped by construction rather than by name.
_STRICT_KEYS = (
    "disallow_untyped_defs",
    "disallow_incomplete_defs",
    "check_untyped_defs",
    "no_implicit_reexport",
    "strict_equality",
    "warn_return_any",
)


def _path_of(module: str) -> str | None:
    """The file a dotted module name lives in, or ``None``.

    A module is either a package's ``__init__.py`` or a ``.py`` file. Tried
    without importing anything, so a module with an import error still
    resolves.
    """
    stem = module.replace(".", os.sep)
    for candidate in (f"{stem}.py", os.path.join(stem, "__init__.py")):
        if os.path.isfile(candidate):
            return candidate
    return None


def strict_modules(pyproject: str = "pyproject.toml") -> list[str]:
    """The strict opt-in module names, in declaration order, de-duplicated."""
    with open(pyproject, "rb") as handle:
        data = tomllib.load(handle)
    blocks = data.get("tool", {}).get("mypy", {}).get("overrides", [])
    names: list[str] = []
    for block in blocks:
        if not isinstance(block, dict) or "module" not in block:
            continue
        if not any(key in block for key in _STRICT_KEYS):
            continue
        for name in block["module"]:
            if name not in names:
                names.append(name)
    return names


def main() -> int:
    paths: list[str] = []
    for module in strict_modules():
        path = _path_of(module)
        if path is None:
            print(
                f"get_strict_modules: no file for module {module!r}",
                file=sys.stderr,
            )
            return 1
        paths.append(path)
    print(" ".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
