# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The legend, the workers, and the file the app writes its state to.

Neither the wrapping nor the AST checks need an event loop, so they live
outside the asyncio-marked module. The family properties here are p2ked's
``tests/test_legend.py``, retargeted:

* a footer that truncates teaches the user its last keys do not exist;
* a worker does MIDI and hands off -- it touches no SQLite store, no
  widget, and no shared attribute;
* the application never writes ``config.toml`` without being told the
  path, so the suite cannot drop one into the checkout.

:class:`tests.test_app.TestTheLegendIsComplete` already pins two of the
worker rules (``self.favorites``/``self.catalog``, and ``_busy = True``).
They are deliberately not repeated here; this file adds the rest of the
family's rule and a stronger "nothing is stored on self" check.
"""

import ast
import os
import shutil

from nanosyned.app import KEY_HINTS, NanosynedApp, wrap_blocks
from vinsynlib import devchecks, keys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_SOURCE = os.path.join(_ROOT, "nanosyned", "app.py")

#: The hints this tool adds to the shared legend that this file exists to
#: pin: the scan key and the two rating keys. The write path adds its own
#: on top (see ``nanosyned.app.WRITE_HINTS``); :func:`_extras` reads those
#: from the module rather than spelling them a second time, so the
#: properties below still hold when an editor adds a key.
REQUIRED_EXTRAS = ("S scan device", "* rating", "V rating filter")

#: Widths a terminal can plausibly hand the footer, plus the degenerate
#: ones a widget asks for before it has been laid out (zero) and a
#: negative width from a confused container.
_WIDTHS = (0, 1, 2, 5, 12, 20, 40, 80, 132, 500)


def _app_tree():
    with open(APP_SOURCE, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _family_blocks():
    """``keys.CANONICAL_LEGEND`` with this tool's one rename applied."""
    return tuple(
        "v favourites view" if block == "F favourites view" else block
        for block in keys.CANONICAL_LEGEND
    )


def _extras():
    """Every block in the legend that is not one of the family's.

    Derived from the module so the write path can add its hints without
    this file growing a second list to keep in step; the position and
    vocabulary checks below still apply to all of them.
    """
    family = set(_family_blocks())
    return tuple(block for block in KEY_HINTS if block not in family)


def _unpack(packed, sep=keys.LEGEND_SEPARATOR):
    """Split a wrapped legend back into its blocks."""
    blocks = []
    for line in packed.split("\n"):
        blocks.extend(line.split(sep))
    return blocks


class TestWrapBlocks:
    def test_every_block_survives_every_width(self):
        """A footer that drops its last keys teaches they do not exist.

        Textual's own Footer is one line and truncates. rxved hit exactly
        that: in a 132-column window its legend wanted 251, and the keys
        that fell off were the newest ones. Unpacking the wrapped text and
        comparing it with the input is the strongest form of "nothing was
        truncated, duplicated or reordered".
        """
        for width in _WIDTHS:
            assert _unpack(wrap_blocks(KEY_HINTS, width)) == list(KEY_HINTS), width

    def test_no_line_exceeds_the_width_unless_one_block_does(self):
        for width in _WIDTHS:
            for line in wrap_blocks(KEY_HINTS, width).splitlines():
                assert len(line) <= width or keys.LEGEND_SEPARATOR not in line, (
                    width,
                    line,
                )

    def test_a_narrow_window_still_shows_everything(self):
        packed = wrap_blocks(KEY_HINTS, 12)
        for hint in KEY_HINTS:
            assert hint in packed.splitlines()

    def test_a_wide_window_uses_one_line(self):
        assert "\n" not in wrap_blocks(KEY_HINTS, 500)

    def test_a_degenerate_width_wraps_one_block_per_line(self):
        """A width of zero must not switch wrapping off.

        The guard used to be ``if width and ...``, so a non-positive width
        made the test false on every candidate and the legend came out as
        one very long line -- the exact failure this function exists to
        prevent, reached by a different route. The only caller clamps, so
        nothing ever passed 0; a function that silently degrades on an
        argument its own docstring does not mention is the thing here.
        """
        for width in (0, -1, -100):
            assert wrap_blocks(("a hint", "b hint"), width) == "a hint\nb hint", width

    def test_the_legend_is_not_empty(self):
        """Guard against the checks above passing on an empty tuple."""
        assert len(KEY_HINTS) >= len(_family_blocks())


class TestTheLegendFollowsTheFamily:
    def test_family_blocks_keep_the_family_order(self):
        family = _family_blocks()
        shown = [block for block in KEY_HINTS if block in family]
        assert shown == list(family)

    def test_the_extras_sit_where_the_family_leaves_room(self):
        """After ``n note``, before ``i device`` -- the one gap there is."""
        extras = _extras()
        start = KEY_HINTS.index("n note") + 1
        assert KEY_HINTS[start : start + len(extras)] == extras
        assert KEY_HINTS[start + len(extras)] == "i device"

    def test_the_required_extras_are_present(self):
        assert set(REQUIRED_EXTRAS) <= set(_extras())
        assert len(set(KEY_HINTS)) == len(KEY_HINTS), "a hint is shown twice"

    def test_v_takes_the_family_favourites_slot(self):
        """``f`` writes the store and ``F`` does not; ``v`` has no twin.

        The family asks a tool that renames a shared key to say why --
        see :mod:`tests.test_conformance`.
        """
        assert "F favourites view" not in KEY_HINTS
        assert (
            KEY_HINTS.index("v favourites view") == KEY_HINTS.index("f favourite") + 1
        )

    def test_the_legend_is_the_library_builder_with_the_declared_extras(self):
        extras = _extras()
        expected = tuple(
            "v favourites view" if block == "F favourites view" else block
            for block in keys.legend(extras=extras)
        )
        assert expected == KEY_HINTS

    def test_the_extras_do_not_take_a_key_the_family_already_shows(self):
        """A tool's own key must not mean two things in the same tool.

        ``keys`` puts this rule in its module docstring: ``s`` is "Scan
        bank" in rxved and "SCSI" in s3ked, which is fine because no tool
        is both. An extra reusing ``f``, say, would make the legend lie
        about one of the two keys.
        """

        def key_of(block):
            return block.split(" ", 1)[0]

        family_keys = {key_of(block) for block in _family_blocks()}
        extra_keys = {key_of(block) for block in _extras()}
        assert not (extra_keys & family_keys)
        bound = {binding.key for binding in NanosynedApp.BINDINGS}
        assert {"S", "asterisk", "V"} <= bound


# --- the workers -------------------------------------------------------------


def _work_methods(tree):
    """Every function decorated with Textual's ``@work``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(
            (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "work")
            or getattr(d, "id", "") == "work"
            for d in node.decorator_list
        ):
            yield node


def _worker_calls(tree, wanted):
    """Workers that call a method with this name."""
    offenders = []
    for node in _work_methods(tree):
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            if not isinstance(inner.func, ast.Attribute):
                continue
            if inner.func.attr == wanted:
                offenders.append(node.name)
    return offenders


def _worker_saves(tree):
    """Workers that write a settings file."""
    offenders = []
    for node in _work_methods(tree):
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            if not isinstance(inner.func, ast.Attribute):
                continue
            if inner.func.attr.startswith("save_"):
                offenders.append(f"{node.name}: {inner.func.attr}")
    return offenders


def _worker_self_writes(tree):
    """Workers that assign anything to ``self``.

    ``self.favorites``/``self.catalog`` and ``_busy = True`` are already
    checked in :mod:`tests.test_app`; this is the stronger rule that keeps
    the next shared attribute from being added, whatever it is called.
    """
    offenders = []
    for node in _work_methods(tree):
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign):
                targets = inner.targets
            elif isinstance(inner, (ast.AnnAssign, ast.AugAssign)):
                targets = [inner.target]
            else:
                continue
            for target in targets:
                for name in ast.walk(target):
                    if (
                        isinstance(name, ast.Attribute)
                        and name.attr
                        and isinstance(name.value, ast.Name)
                        and name.value.id == "self"
                    ):
                        offenders.append(f"{node.name}: self.{name.attr}")
    return offenders


class TestWorkersOnlyDoMidi:
    """Workers talk to the device and hand off. Nothing else.

    An AST check rather than a convention, because the sibling rxved
    learned this the expensive way: a worker that touched a SQLite
    connection raised out of the worker and ended the application.
    """

    def test_there_are_workers_to_check(self):
        """Guard against this passing because it found nothing to check."""
        assert list(_work_methods(_app_tree()))

    def test_no_worker_queries_widgets(self):
        offenders = _worker_calls(_app_tree(), "query_one")
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} query widgets directly; "
            f"that is the main thread's job"
        )

    def test_no_worker_writes_a_settings_file(self):
        offenders = _worker_saves(_app_tree())
        assert not offenders, (
            f"worker(s) write settings: {sorted(set(offenders))}. `update` "
            f"rewrites the whole file, so two writers interleave and the "
            f"port can end up half of each. Hand it off instead."
        )

    def test_no_worker_stores_anything_on_self(self):
        """Stronger than ``_busy`` alone, and the reason for it.

        A worker returns at once, so any attribute it sets is set on its
        own thread, after the caller was told the work had started. The
        fix is always the same: compute locally, then
        ``call_from_thread`` the main-thread half. ``test_app`` pins the
        ``_busy`` case; this catches the next attribute somebody adds.
        """
        offenders = _worker_self_writes(_app_tree())
        assert not offenders, (
            f"worker(s) assign shared state: {sorted(set(offenders))}; "
            f"workers do MIDI and hand off with call_from_thread"
        )

    def test_a_bad_worker_is_caught(self):
        """The guard above must be able to fail.

        Written against a synthetic source, because a guard that passes
        because it matched nothing is worse than none -- and the edit that
        would make this one vacuous is exactly the one a future write
        feature is tempted into.
        """
        synthetic = ast.parse(
            "from textual import work\n"
            "\n"
            "class Fake:\n"
            "    @work(thread=True)\n"
            "    def _bad(self):\n"
            "        self.query_one('#slot-table')\n"
            "        self._busy = True\n"
            "        config.save_channel(1)\n"
            "        return self.favorites\n"
        )
        assert _worker_calls(synthetic, "query_one") == ["_bad"]
        assert _worker_saves(synthetic) == ["_bad: save_channel"]
        assert _worker_self_writes(synthetic) == ["_bad: self._busy"]


# --- the config file ---------------------------------------------------------

#: Calls on the config module under every spelling app.py uses. Its two
#: function-local imports are ``config`` and ``_cfg``; ``main`` imports it
#: as ``cfg``. A save through any of them writes the same file.
_CONFIG_ALIASES = frozenset({"config", "cfg", "_cfg"})

#: How many values each writer takes before ``path``. app.py uses the
#: first two; ``save_ports`` is listed because it is the other writer in
#: this project's config module and a table that forgets it would read
#: ``save_ports("In", "Out")`` as safe.
_VALUES_BEFORE_PATH = {"save_channel": 1, "save_ports": 2, "save_ui_state": 2}


def _config_saves(tree):
    """Every config-writing call in a parsed module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not node.func.attr.startswith("save_"):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id in _CONFIG_ALIASES:
            yield node


def _pathless_saves(tree):
    offenders = []
    for node in _config_saves(tree):
        before = _VALUES_BEFORE_PATH.get(node.func.attr, 1)
        named = len(node.args) > before or any(
            keyword.arg == "path" for keyword in node.keywords
        )
        if not named:
            offenders.append(f"{node.func.attr} at line {node.lineno}")
    return offenders


class TestTheAppNeverSavesAConfigWithoutAPath:
    """``config.DEFAULT_PATH`` is relative, so a pathless save hits the CWD.

    That is the right default for the application -- ``config.toml`` is a
    disposable per-checkout cache, gitignored -- and exactly the wrong
    thing for a test. :mod:`tests.test_config_paths` pins the test suite;
    this pins the *application source*, which is where a pathless save
    would be a real bug rather than a lost cache: when a test drives the
    app, ``main``'s relative default is the checkout too.

    The library's checker is used first, then the two spellings it cannot
    see: :func:`devchecks.config_saves_without_path` looks only at calls
    written ``config.save_*`` and sizes an unknown writer at one value,
    while app.py also says ``cfg``/``_cfg`` and ``save_ui_state`` takes
    two values before its path.
    """

    def test_devchecks_finds_nothing_in_the_app_source(self, tmp_path):
        """``config_saves_without_path`` is directory-scoped over tests.

        Copying the module in under a ``test_*.py`` name runs the library
        check against the real text of app.py -- parsed, never imported --
        without teaching this project a second copy of it. This catches
        the ``config.save_*`` spelling; the alias-aware test below catches
        the rest.
        """
        shutil.copyfile(APP_SOURCE, tmp_path / "test_app_source.py")
        assert devchecks.config_saves_without_path(str(tmp_path)) == []

    def test_every_config_save_in_the_app_names_its_file(self):
        assert _pathless_saves(_app_tree()) == [], (
            "app.py saves to config.DEFAULT_PATH, which is relative to the "
            "working directory. Pass the path."
        )

    def test_the_check_has_something_to_check(self):
        """Guard against the search passing because it matched nothing."""
        saves = list(_config_saves(_app_tree()))
        assert saves, "no config.save_* calls found in app.py; the check is vacuous"

    def test_a_pathless_save_is_caught(self):
        """And the alias-aware half can fail, on all three spellings."""
        synthetic = ast.parse(
            "config.save_channel(3)\n"
            "cfg.save_channel(3, path)\n"
            "_cfg.save_ui_state('view_mode', 'all')\n"
            "_cfg.save_ui_state('view_mode', 'all', path)\n"
            "config.save_ports('In', 'Out', path)\n"
        )
        assert len(_pathless_saves(synthetic)) == 2, _pathless_saves(synthetic)
