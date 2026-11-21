#!/usr/bin/env python3
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

"""Capture ``docs/screenshots`` from the browser in ``--demo`` mode.

Drives the Textual app headlessly through ``App.run_test``, exports each
screen with ``App.export_screenshot`` and converts the SVG to PNG. The app is
constructed around :class:`nanosyned.demo.DemoDevice` directly: **no MIDI
port is opened and nothing is sent**. Every name on screen is invented by the
demo's word pool, so a shot can never pass off Alesis's program names as this
project's.

**PNG conversion needs** ``cairosvg``. It is deliberately not a runtime
dependency -- the browser does not use it and a user should not pay for a
renderer to browse patches. Install it with::

    .venv/bin/pip install -e '.[tools]'

Without it the SVGs are still written, and ``--svg-only`` says that is what
was asked for. A run without either is an error after the SVGs land, rather
than a silent half-success.

Rules this script follows, in the family's shape:

* **One fresh app per shot.** Every shot starts from launch state, so a modal
  left open by one shot cannot leak into the next. The empty-catalog app for
  the scan offer is the only variant: it is built with no catalog on purpose.
* **A text marker must be in every shot.** A stale image is worse than no
  image: the run fails loudly when a marker goes missing rather than leaving
  a plausible picture behind.
* **The SVG is fixed up before it is written.** The terminal font becomes
  DejaVu Sans Mono (which carries every glyph in the legend), the remote
  ``@font-face`` blocks are removed so capture works offline, and Rich's
  macOS window chrome is stripped so the shot reads as a plain terminal.
* **The editor is optional.** It may be landing concurrently; a missing
  editor is reported and the rest of the run continues.

Only this checkout's demo is driven. There is no ``--port`` here, on purpose:
the README's pictures must never depend on what happens to be plugged in.

    python3 tools/capture_screenshots.py
    python3 tools/capture_screenshots.py --svg-only
    python3 tools/capture_screenshots.py --output-dir /tmp/shots
"""

from __future__ import annotations

import argparse
import asyncio
import html
import importlib
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.widgets import DataTable

try:
    from cairosvg import svg2png  # type: ignore[import-not-found,import-untyped]
except ImportError:  # pragma: no cover - environment check
    svg2png = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from nano import (  # noqa: E402
    banks,
    fullbackup,
)
from nano import catalog as cat  # noqa: E402
from nano.favorites import Favorites  # noqa: E402
from nanosyned.app import MIXES_BANK, NanosynedApp  # noqa: E402
from nanosyned.demo import DemoDevice, demo_name  # noqa: E402
from nanosyned.restorebank import FullRestoreScreen  # noqa: E402
from nanosyned.scan import ScanOfferScreen  # noqa: E402
from nanosyned.screens import KeyHints, ReportScreen  # noqa: E402
from vinsynlib.ui.modals import SearchScreen  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "docs" / "screenshots"
SCREEN_W = 820
BROWSER_SIZE = (132, 42)
MODAL_SIZE = (120, 36)
SCAN_SIZE = (150, 30)


class SkipShot(Exception):
    """A shot this checkout cannot take yet. Never fatal."""


@dataclass(frozen=True)
class Output:
    """Where a shot goes and how big its PNG is."""

    directory: Path
    width: int
    svg_only: bool


def demo_catalog() -> cat.Catalog:
    """A full catalog of invented names, one per slot.

    The demo device offers the same names for the User bank; taking them for
    every bank keeps the browser readable without borrowing anything from a
    manual. Program 127 is the hardwired silence the unit actually has, and
    the demo calls it by the name the unit reports.
    """
    entries = []
    for bank in banks.banks():
        for number in range(banks.PROGRAMS_PER_BANK):
            name = (
                "Off"
                if (bank.id, number) == banks.SILENT_PROGRAM
                else demo_name(bank.id, number)
            )
            entries.append(cat.Entry(bank.id, number, name))
    return cat.Catalog(entries, source="demo (invented names)")


def fix_svg(svg: str) -> str:
    """Terminal font, no remote fonts, no window chrome."""
    svg = svg.replace(
        "font-family: Fira Code, monospace",
        'font-family: "DejaVu Sans Mono", monospace',
    )
    svg = re.sub(r"@font-face\s*\{[^}]+\}", "", svg)
    svg = re.sub(r"<circle[^>]*/>", "", svg)
    svg = re.sub(r"<circle[^>]*>.*?</circle>", "", svg)
    svg = re.sub(r'<text[^>]*class="[^"]*-title"[^>]*>.*?</text>', "", svg)
    return svg


def screen_text(svg: str) -> str:
    """The visible text of a shot, for the marker check and the transcript."""
    text = re.sub(r"<style.*?</style>", "", svg, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Table cells are padded with non-breaking spaces in the export; a marker
    # written with plain spaces would never match them.
    text = text.replace("\xa0", " ")
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    return "\n".join(lines)


def make_app(tmp: Path, catalog: cat.Catalog) -> NanosynedApp:
    """One fresh browser over the demo, with disk state inside ``tmp``."""
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "fav").mkdir(parents=True, exist_ok=True)
    return NanosynedApp(
        DemoDevice(),
        catalog=catalog,
        favorites=Favorites(str(tmp / "fav" / "favorites.db")),
        config_path=str(tmp / "config" / "config.toml"),
        # A sidecar beside this shot's own path: the checkout's real
        # live-names file must never make an empty browser look full.
        catalog_path=str(tmp / "catalog.json"),
    )


async def wait_for_text(
    app: NanosynedApp, pilot: Any, marker: str, tries: int = 200
) -> None:
    """Poll the visible text until it contains ``marker``."""
    for _ in range(tries):
        if marker.lower() in screen_text(app.export_screenshot()).lower():
            return
        await pilot.pause()
    raise AssertionError(f"never saw {marker!r} on screen")


async def wait_for_screen(
    app: NanosynedApp, pilot: Any, cls: type, tries: int = 200
) -> None:
    """Poll until the top screen is an instance of ``cls``."""
    for _ in range(tries):
        if isinstance(app.screen, cls):
            return
        await pilot.pause()
    raise AssertionError(
        f"top screen is {type(app.screen).__name__}, not {cls.__name__}"
    )


async def wait_for_idle(app: NanosynedApp, pilot: Any, tries: int = 200) -> None:
    """Wait until no MIDI exchange is pending or in flight."""
    for _ in range(tries):
        if not app._busy:
            return
        await pilot.pause()
    raise AssertionError("wire stayed busy")


async def capture(
    app: NanosynedApp,
    pilot: Any,
    name: str,
    output: Output,
) -> str:
    """Pin hint heights, export, fix, write SVG and (if possible) PNG."""
    await pilot.pause()
    for hint in app.query(KeyHints):
        rendered = hint.render()
        if rendered:
            hint.styles.height = str(str(rendered).count("\n") + 1)
    await pilot.pause()

    svg = fix_svg(app.export_screenshot())
    out_svg = output.directory / f"{name}.svg"
    out_svg.write_text(svg, encoding="utf-8")
    if output.svg_only or svg2png is None:
        print(f"  {name}.svg ({out_svg.stat().st_size // 1024} KB)")
    else:
        out_png = output.directory / f"{name}.png"
        svg2png(
            bytestring=svg.encode(),
            write_to=str(out_png),
            output_width=output.width,
        )
        print(f"  {name}.png ({out_png.stat().st_size // 1024} KB)")
    return svg


def check(name: str, svg: str, markers: list[str]) -> None:
    """Every marker must be present; a missing one means the shot is stale."""
    text = screen_text(svg).lower()
    missing = [marker for marker in markers if marker.lower() not in text]
    if missing:
        raise AssertionError(
            f"{name}: marker(s) {missing} not in shot text:\n{text[:900]}"
        )
    print(f"  markers ok: {markers}")


# --- shots ---------------------------------------------------------------


async def shot_browser(app: NanosynedApp, pilot: Any) -> None:
    """Both panes: the five banks on the left, the slots on the right."""
    await wait_for_idle(app, pilot)
    await wait_for_text(app, pilot, "General MIDI")
    await wait_for_text(app, pilot, "Linen Bell")


async def shot_detail(app: NanosynedApp, pilot: Any) -> None:
    """The detail line, on the one slot the manual warns about."""
    await wait_for_idle(app, pilot)
    app._fill("USER")
    await pilot.pause()
    table = app.query_one("#slot-table", DataTable)
    table.focus()
    table.move_cursor(row=banks.SILENT_PROGRAM[1])
    app._detail(banks.SILENT_PROGRAM[1])
    await pilot.pause()
    await wait_for_text(app, pilot, "hardwired silent program")


async def shot_mixes(app: NanosynedApp, pilot: Any) -> None:
    """The Mixes row, its 100 slots, and a mix's detail line."""
    await wait_for_idle(app, pilot)
    app._fill(MIXES_BANK)
    await wait_for_idle(app, pilot)
    await wait_for_text(app, pilot, "Mixes")
    await wait_for_text(app, pilot, "Mix mode")


async def shot_favourites(app: NanosynedApp, pilot: Any) -> None:
    """The favourites view, with a few invented slots marked."""
    await wait_for_idle(app, pilot)
    app.query_one("#slot-table").focus()
    for _ in range(3):
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
    await pilot.press("F")
    await pilot.pause()
    await wait_for_text(app, pilot, "favourites in this bank")


async def shot_help(app: NanosynedApp, pilot: Any) -> None:
    await pilot.press("?")
    await wait_for_screen(app, pilot, ReportScreen)
    await wait_for_text(app, pilot, "The five banks")


async def shot_search(app: NanosynedApp, pilot: Any) -> None:
    await pilot.press("/")
    await wait_for_screen(app, pilot, SearchScreen)
    await wait_for_text(app, pilot, "Search")


async def shot_scan_offer(app: NanosynedApp, pilot: Any) -> None:
    """The offer an empty catalog gets, over a browser with no names."""
    app._maybe_offer_scan()
    await wait_for_screen(app, pilot, ScanOfferScreen)
    await wait_for_text(app, pilot, "no name catalog yet")


async def shot_device(app: NanosynedApp, pilot: Any) -> None:
    await wait_for_idle(app, pilot)
    await pilot.press("i")
    await wait_for_screen(app, pilot, ReportScreen)
    await wait_for_text(app, pilot, "manufacturer")


def editor_screen() -> type | None:
    """The editor's screen class, when this checkout has an editor at all.

    The editor is landing concurrently with this tool, so nothing here may
    assume its module, class or key. It may live in ``nanosyned.editor`` or
    be re-exported by ``nanosyned.screens``; both are searched. A missing
    module or class is a skip; an editor that exists but cannot be reached
    is reported by the caller.
    """
    for module_name in ("nanosyned.editor", "nanosyned.screens"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in dir(module):
            candidate = getattr(module, name)
            if isinstance(candidate, type) and name.endswith("EditorScreen"):
                return candidate
    return None


def editor_key() -> str | None:
    """The binding whose action opens the editor, if one is declared."""
    for binding in NanosynedApp.BINDINGS:
        action = str(getattr(binding, "action", ""))
        if action in {"edit_program", "open_editor", "editor"}:
            return str(getattr(binding, "key", "")) or None
    return None


async def shot_editor(app: NanosynedApp, pilot: Any) -> None:
    """The program editor, when the concurrent change has landed.

    Getting in is deliberately allowed to fail softly: the screen can exist
    before the app method that opens it does, since the two are separate
    pieces of work. What must never happen is one missing shot taking the
    other seven with it.
    """
    screen_cls = editor_screen()
    if screen_cls is None:
        raise SkipShot("no EditorScreen is in this checkout yet")
    if not hasattr(app, "action_edit_program"):
        raise SkipShot("an EditorScreen exists but the app cannot open it yet")
    key = editor_key()
    if key is None:
        raise SkipShot("an EditorScreen exists but no editor key is bound")
    try:
        await wait_for_idle(app, pilot)
        app._fill("USER")
        await pilot.pause()
        table = app.query_one("#slot-table", DataTable)
        table.focus()
        await pilot.pause()
        if hasattr(app, "action_toggle_write_gate"):
            # The editor only opens while the write gate is armed.
            await pilot.press("w")
            await pilot.pause()
        await pilot.press(key)
        await wait_for_screen(app, pilot, screen_cls)
        await wait_for_text(app, pilot, "Edit ")
    except Exception as exc:  # the editor is still landing; report, do not fail
        raise SkipShot(f"the editor could not be opened: {exc}") from exc


async def shot_restore(app: NanosynedApp, pilot: Any) -> None:
    """The full-restore confirmation, with a real demo backup file."""
    shot_dir = Path(tempfile.gettempdir()) / "nanosyned-demo"
    shot_dir.mkdir(parents=True, exist_ok=True)
    path = shot_dir / "nanosyned-backup-demo.syx"
    fullbackup.backup_device(DemoDevice(), str(path), overwrite=True)
    app._restore_file_chosen(str(path))
    await wait_for_screen(app, pilot, FullRestoreScreen)
    await pilot.press("w")
    await pilot.pause()
    await wait_for_text(app, pilot, "ARMED")


SHOTS: list[tuple[str, Any, tuple[int, int], bool, list[str]]] = [
    (
        "browser",
        shot_browser,
        BROWSER_SIZE,
        True,
        ["General MIDI", "Linen Bell"],
    ),
    (
        "detail",
        shot_detail,
        BROWSER_SIZE,
        True,
        ["hardwired silent program"],
    ),
    (
        "mixes",
        shot_mixes,
        BROWSER_SIZE,
        True,
        ["Mixes", "Mix mode"],
    ),
    (
        "favourites",
        shot_favourites,
        BROWSER_SIZE,
        True,
        ["favourites in this bank"],
    ),
    ("help", shot_help, MODAL_SIZE, True, ["The five banks"]),
    ("search", shot_search, MODAL_SIZE, True, ["Search"]),
    (
        "scan-offer",
        shot_scan_offer,
        SCAN_SIZE,
        False,
        ["no name catalog yet"],
    ),
    ("device", shot_device, MODAL_SIZE, True, ["manufacturer"]),
    ("editor", shot_editor, BROWSER_SIZE, True, ["edit user", "arm the store"]),
    (
        "restore",
        shot_restore,
        MODAL_SIZE,
        True,
        ["Restore full backup", "127 user program"],
    ),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "drives the demo device only: no MIDI port is opened. PNG "
            "output needs cairosvg; install it with "
            "`.venv/bin/pip install -e '.[tools]'`, or pass --svg-only"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUT),
        metavar="DIR",
        help=f"where the shots go (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--svg-only",
        action="store_true",
        help="write the SVGs and skip the PNG conversion",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=SCREEN_W,
        metavar="PX",
        help=f"PNG width in pixels (default: {SCREEN_W})",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = Output(out_dir, args.width, args.svg_only)
    skipped: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for name, fn, size, full_catalog, markers in SHOTS:
            sub = tmp / name
            sub.mkdir(exist_ok=True)
            app = make_app(sub, demo_catalog() if full_catalog else cat.empty())
            print(f"--- {name} ---")
            try:
                async with app.run_test(size=size) as pilot:
                    await fn(app, pilot)
                    svg = await capture(app, pilot, name, output)
            except SkipShot as exc:
                print(f"  skipped: {exc}")
                skipped.append(name)
                continue
            check(name, svg, markers)
            print(screen_text(svg)[:900])
            print()

    print(f"Done. Screenshots in {out_dir}")
    if skipped:
        print(f"Skipped (not an error): {', '.join(skipped)}")
    if svg2png is None and not args.svg_only:
        print(
            "error: PNG conversion needs cairosvg, which is not installed. "
            "The SVGs above are complete.\n"
            "       .venv/bin/pip install -e '.[tools]'   (or pass --svg-only)",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.width < 1:
        raise SystemExit("error: --width must be at least 1")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
