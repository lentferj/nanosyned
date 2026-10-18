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

"""The scan offer and the scan itself: three answers, one bank.

What a scan can honestly mean on this instrument is the whole subject of
:mod:`nanosyned.scan`: only the User bank has a dump request, so a scan
reads 128 names and leaves the General MIDI and preset banks to the
printed catalog. The tests below pin the three things that follow from
that:

* the offer has three answers, and only ``never`` is remembered -- a key
  pressed to make a dialog go away must not quietly change a preference;
* a cancelled scan adopts nothing and leaves no sidecar;
* a finished scan adopts the User names, writes the live-names sidecar,
  and touches no other bank.

Every device here is :class:`nanosyned.demo.DemoDevice`; no port is
opened and no name is real.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time

from textual.app import App
from textual.widgets import Button

from nano import banks, config, livenames
from nano import catalog as cat
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice, demo_name
from nanosyned.scan import SCAN_OFFER, ScanOfferScreen, ScanScreen


class _Harness(App[None]):
    """The least an app can be and still push a screen and keep its answer."""

    def __init__(self, screen, sink) -> None:
        super().__init__()
        self._screen = screen
        self._sink = sink

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._sink)


async def _answer(key: str) -> list[str]:
    """Push the offer, send one key, and collect what it dismissed with."""
    seen: list[str] = []
    app = _Harness(ScanOfferScreen(), seen.append)
    async with app.run_test() as pilot:
        await pilot.press(key)
    return seen


class SlowDemo(DemoDevice):
    """A demo that pauses per program, so a scan can be caught mid-flight."""

    def __init__(self, delay: float = 0.01, **kwargs) -> None:
        super().__init__(**kwargs)
        self.delay = delay

    def read_program(self, number: int, *, timeout=None) -> bytes:
        time.sleep(self.delay)
        return super().read_program(number, timeout=timeout)


class CountingDemo(DemoDevice):
    """A demo that counts the bulk reads, to prove there is exactly one."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name_reads = 0

    def read_program_names(self, **kwargs) -> dict[int, str]:
        self.name_reads += 1
        return super().read_program_names(**kwargs)


def make(tmp_path, *, device=None, catalog=None):
    """An app with every path injected, and the demo (or a demo subclass)."""
    return NanosynedApp(
        device if device is not None else DemoDevice(),
        catalog=catalog if catalog is not None else cat.empty(),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
    )


async def _until(pilot, ready, attempts: int = 400) -> bool:
    """Wait until ``ready()``, yielding real time to the scan's thread.

    ``pilot.pause`` alone does not advance the clock the worker sleeps
    on, so this tiny sleep is doing work: the scan runs on its own
    thread and 128 demo requests, however fast, still need scheduling.
    """
    for _ in range(attempts):
        if ready():
            return True
        await asyncio.sleep(0.01)
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestTheOfferAnswers:
    """Three answers, because "later" and "never" are different questions."""

    async def test_y_means_scan(self):
        assert await _answer("y") == ["scan"]

    async def test_n_means_later(self):
        assert await _answer("n") == ["later"]

    async def test_d_means_never(self):
        assert await _answer("d") == ["never"]

    async def test_escape_defers_rather_than_refusing(self):
        """The nearest key to hand must be the reversible answer."""
        assert await _answer("escape") == ["later"]

    async def test_the_buttons_give_the_same_three_answers(self):
        for button_id, expected in (
            ("scan", "scan"),
            ("later", "later"),
            ("never", "never"),
        ):
            seen: list[str] = []
            app = _Harness(ScanOfferScreen(), seen.append)
            async with app.run_test() as pilot:
                assert app.screen.query_one(f"#{button_id}", Button)
                await pilot.click(f"#{button_id}")
            assert seen == [expected], button_id

    def test_the_offer_names_the_one_bank_and_calls_the_rest_rom(self):
        """The sentence a user reads has to be true about this hardware."""
        assert "User bank" in SCAN_OFFER
        assert "General MIDI" in SCAN_OFFER
        assert "ROM" in SCAN_OFFER
        assert "no request" in SCAN_OFFER


class TestTheOfferIsRemembered:
    """``never`` is a preference; ``later`` and escape are not."""

    async def test_never_is_persisted_and_the_offer_stays_away(
        self, tmp_path, monkeypatch
    ):
        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        monkeypatch.chdir(scratch)

        app = make(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            assert await _until(pilot, lambda: isinstance(app.screen, ScanOfferScreen))

            await pilot.press("d")
            assert await _until(
                pilot, lambda: not isinstance(app.screen, ScanOfferScreen)
            )
            assert (
                config.load_ui_bool(
                    "scan_offer_dismissed", str(tmp_path / "config.toml")
                )
                is True
            )

            # A check re-armed after the answer must find the dismissal
            # settled rather than push the modal a second time.
            app._maybe_offer_scan()
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

        second = make(tmp_path)
        async with second.run_test() as pilot:
            await pilot.pause()
            second._maybe_offer_scan()
            await pilot.pause()
            assert not isinstance(second.screen, ScanOfferScreen)

        # The dismissal landed in the injected file, not in the CWD.
        assert list(scratch.iterdir()) == []

    async def test_later_is_not_persisted(self, tmp_path):
        app = make(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            assert await _until(pilot, lambda: isinstance(app.screen, ScanOfferScreen))
            await pilot.press("n")
            assert await _until(
                pilot, lambda: not isinstance(app.screen, ScanOfferScreen)
            )
        assert (
            config.load_ui_bool("scan_offer_dismissed", str(tmp_path / "config.toml"))
            is None
        )

        second = make(tmp_path)
        async with second.run_test() as pilot:
            await pilot.pause()
            second._maybe_offer_scan()
            assert await _until(
                pilot, lambda: isinstance(second.screen, ScanOfferScreen)
            )


class TestAWholeScan:
    """The read, its cancel, and the sidecar it leaves behind."""

    async def test_a_completed_scan_adopts_the_names_and_saves_the_sidecar(
        self, tmp_path
    ):
        device = CountingDemo()
        app = make(tmp_path, device=device, catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            assert await _until(
                pilot, lambda: app.catalog.live_name("USER", 0) is not None
            )
            await _until(pilot, lambda: not app._busy)

            assert device.name_reads == 1
            assert app.catalog.live_name("USER", 0) == demo_name("USER", 0)
            assert app.device.selected_log == [], "a scan selected something"

            sidecar = livenames.path_for(str(tmp_path / "catalog.json"))
            stored = livenames.load(sidecar)
            assert len(stored) == banks.PROGRAMS_PER_BANK
            assert stored[livenames.key("USER", 0)] == demo_name("USER", 0)
            assert "128 names from USER" in str(app.query_one("#status").content)

        assert os.path.isfile(sidecar)

    async def test_the_scan_covers_the_user_bank_only(self, tmp_path):
        """Four fifths of what the browser shows is ROM; the unit is not asked."""
        app = make(tmp_path, catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            assert await _until(
                pilot, lambda: app.catalog.live_name("USER", 0) is not None
            )
            for bank_id in ("GM", "P1", "P2", "P3"):
                assert app.catalog.live_name(bank_id, 0) is None, bank_id
            status = str(app.query_one("#status").content)
            assert "USER" in status
            assert "read 128 names" in status

    async def test_a_cancelled_scan_returns_none_and_adopts_nothing(self, tmp_path):
        app = make(tmp_path, device=SlowDemo(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            assert await _until(pilot, lambda: isinstance(app.screen, ScanScreen))

            await pilot.press("escape")
            assert await _until(
                pilot,
                lambda: not app._busy and not isinstance(app.screen, ScanScreen),
            )

            assert app.catalog.live_name("USER", 0) is None
            assert not os.path.exists(
                livenames.path_for(str(tmp_path / "catalog.json"))
            )
            assert "cancelled" in str(app.query_one("#status").content)
            assert app.device.selected_log == []

    async def test_the_scan_screen_hands_back_none_when_cancelled(self):
        started = threading.Event()

        def read(on_progress, cancel):
            on_progress(1, 2)
            started.set()
            while not cancel.wait(0.01):
                pass
            return {0: "never adopted"}

        seen: list[dict[int, str] | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ScanScreen(read, total=2), seen.append)
            await pilot.pause()
            assert started.wait(1)
            await pilot.press("escape")
            assert await _until(pilot, lambda: bool(seen))
            assert seen == [None]
