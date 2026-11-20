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

"""The local settings cache: which port answered, and which channel.

Now a binding of :class:`vinsynlib.config.bind` rather than a second
copy of it. The behaviour, including the traps it is written around, is
the family's and lives in one place:

* A TOML boolean is not a channel. ``isinstance(True, int)`` is true, so a
  hand-edited ``channel = true`` used to come back as ``True``, pass every
  range check, and then ``0xC0 | True`` is MIDI channel 2 -- a wrong
  channel being not an error anywhere.
* Everything written is escaped. A port name is whatever ALSA reports, and
  a quote in one produces a file that is not TOML, which the writer then
  refuses to overwrite: a cache that never heals.
* Only :class:`OSError` is swallowed -- a read-only directory or a full
  disk, where forgetting a preference beats refusing to run.

What is added here is the name. One string decides what the one warning
message says, and it has to be right: several of these programs can be
open in one session, and a user who is told a file could not be parsed has
to be able to tell which one is unhappy.

The ui-state wrappers are the 0.4.0 API, and :data:`UNSET` forwards "not
given" rather than a value: a caller that omits *default* gets the
library's sentinel back, so the caller can tell "no preference remembered"
apart from any value a preference could hold.

The cache is per-user/per-tool, not per-checkout: its location is the
platform directory for the tool ``nanosyned``, not the working directory.
"""

from __future__ import annotations

import argparse
import os
import re
import tomllib

from vinsynlib.config import (
    UNSET,
    bind,
    config_dir,
    config_help,
    default_config_path,
    migrate_legacy_config,
)

DEFAULT_PATH = default_config_path("nanosyned")

#: The ui-state file's name beside the settings file. The library derives
#: the same name from its own default; naming it here lets the app and its
#: tests agree on one path without either reaching into a private helper.
UI_STATE_NAME = "ui-state.toml"

__all__ = [
    "DEFAULT_PATH",
    "UI_STATE_NAME",
    "UNSET",
    "apply_config_help",
    "bind",
    "config_dir",
    "config_help",
    "default_config_path",
    "load_channel",
    "load_device_id",
    "load_last_port",
    "load_last_recv_port",
    "load_port_pair",
    "load_ui_bool",
    "load_ui_int",
    "load_ui_state",
    "load_ui_str",
    "migrate_legacy_config",
    "migrate_legacy_ui_state",
    "read_ui_state",
    "save_channel",
    "save_device_id",
    "save_last_port",
    "save_last_recv_port",
    "save_ports",
    "save_ui_state",
    "ui_state_path",
]

_settings = bind("nanosyned", DEFAULT_PATH)


def apply_config_help(parser: argparse.ArgumentParser, tool: str = "nanosyned") -> None:
    """Set the help text for the --config argument in the parser.

    This is used to ensure the help text mentions the per-tool default path
    rather than always being ./config.toml.
    """
    for action in parser._actions:
        if action.dest == "config":
            action.help = config_help(tool)
            break


#: Module-level aliases, so every existing call site reads the same as it
#: did before: ``config.load_channel(path)``.
load_channel = _settings.load_channel
save_channel = _settings.save_channel
load_last_port = _settings.load_port
save_last_port = _settings.save_port
load_last_recv_port = _settings.load_recv_port
save_last_recv_port = _settings.save_recv_port
load_device_id = _settings.load_device_id
save_device_id = _settings.save_device_id
#: Both ports at once, in one write. What the connection policy saves after a
#: sweep: a half-written pair is a pair where the second half is lost.
save_ports = _settings.save_ports
#: UI-state wrappers, the 0.4.0 API: key, value, path last where asked.
load_ui_state = _settings.load_ui_state
load_ui_int = _settings.load_ui_int
load_ui_bool = _settings.load_ui_bool
load_ui_str = _settings.load_ui_str
read_ui_state = _settings.read_ui_state
save_ui_state = _settings.save_ui_state

#: The ui-state keys an older build wrote into the settings file. The
#: dotted one is the trap: TOML reads an unquoted ``import.folder`` as the
#: table ``[import]``, which the settings writer then refuses to touch.
_LEGACY_UI_KEYS = (
    "bank_index",
    "slot_cursor",
    "view_mode",
    "mix_number",
    "rating_stars",
    "rating_at_least",
    "scan_offer_dismissed",
    "import.folder",
)


def ui_state_path(config_path: str) -> str:
    """The ui-state file beside ``config_path``.

    Still the library's store, not this module's: the name exists only so
    the app and its tests read and write one agreed path. The library
    derives the same name from the settings path when no ui-state path is
    passed (:meth:`vinsynlib.config.Settings._ui_path`, private by
    design), so the two spellings cannot drift.
    """
    return os.path.join(os.path.dirname(config_path), UI_STATE_NAME)


def _legacy_ui_value(data: dict, key: str) -> str | int | float | bool | None:
    """One known ui-state value an older build left in the settings file."""
    if key == "import.folder":
        table = data.get("import")
        if not isinstance(table, dict):
            return None
        folder = table.get("folder")
        if not isinstance(folder, str) or table != {"folder": folder}:
            # Anything else under ``import`` is not ours to remove.
            return None
        return folder
    value = data.get(key)
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def _legacy_ui_values(data: dict) -> dict[str, str | int | float | bool]:
    """The known ui-state keys an older build left in the settings file."""
    values: dict[str, str | int | float | bool] = {}
    for key in _LEGACY_UI_KEYS:
        value = _legacy_ui_value(data, key)
        if value is not None:
            values[key] = value
    return values


def _drop_legacy_ui_lines(text: str, keys: set[str]) -> str | None:
    """``text`` without the settings-file lines for ``keys``."""
    patterns = [re.compile(rf"^\s*{re.escape(key)}\s*=") for key in keys]
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if not any(p.match(line) for p in patterns)]
    if len(kept) == len(lines):
        return None
    cleaned = "".join(kept)
    try:
        tomllib.loads(cleaned)
    except ValueError:
        return None
    return cleaned


def _replace_text(path: str, text: str) -> bool:
    """Write ``text`` through a temporary beside ``path``; False on OSError."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def migrate_legacy_ui_state(
    config_path: str, ui_state_path: str
) -> tuple[str, ...] | None:
    """Move ui-state keys an older build left in the settings file.

    Every screen value used to be written into ``config.toml``. The dotted
    one is the trap: an unquoted ``import.folder = "..."`` is a TOML table,
    and the settings writer refuses a file holding tables -- correctly,
    because it will not destroy something it did not write. That refusal
    also stopped the port and channel being remembered. This moves the
    known screen keys into the ui-state sidecar and removes their lines,
    leaving every other line untouched.

    Returns the migrated keys, or ``None`` when there was nothing to move.
    A newer value already in the sidecar is kept; a line is only dropped
    once the sidecar holds a value, so a read-only directory never loses
    the only copy.
    """
    if os.path.abspath(config_path) == os.path.abspath(ui_state_path):
        return None
    try:
        with open(config_path, encoding="utf-8") as handle:
            text = handle.read()
        data = tomllib.loads(text)
    except (OSError, ValueError):
        return None
    values = _legacy_ui_values(data)
    if not values:
        return None
    moved: set[str] = set()
    for key, value in values.items():
        if _settings.load_ui_state(key, ui_state_path) is UNSET:
            _settings.save_ui_state(key, value, ui_state_path)
        if _settings.load_ui_state(key, ui_state_path) is not UNSET:
            moved.add(key)
    cleaned = _drop_legacy_ui_lines(text, moved) if moved else None
    if cleaned is None:
        return None
    if not _replace_text(config_path, cleaned):
        return None
    return tuple(sorted(moved))


def load_port_pair(path: str | None = None) -> tuple[str, str] | None:
    """The remembered port pair, or None.

    :meth:`vinsynlib.config.Settings.load_ports` answers only when *both*
    keys are present, because for most of the family a half-remembered pair
    is not a pair. Here it would also be wrong in the other direction: this
    tool has always written ``recv_port`` only when it differed from
    ``port``, so every config written before the remembered-port path existed
    would read as nothing remembered and the next launch would sweep every
    port again -- the exact thing the pair is for. One remembered output port
    is a complete pair unless the file says otherwise.
    """
    send = _settings.load_port(path)
    if not send:
        return None
    return (send, _settings.load_recv_port(path) or send)
