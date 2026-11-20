from __future__ import annotations

import pytest
from textual.widgets import DataTable, Static

from nano import catalog as cat
from nano import importing, importplan
from nanosyned.app import NanosynedApp
from nanosyned.appendbank import MANUAL, AppendBankScreen
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditGate
from vinsynlib.ui.confirm import ConfirmScreen


def _record(name):
    import nano.messages as m
    import nano.records as rec

    data = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(data, name, m.NAME_BIT_OFFSET)
    return bytes(data)


def _bank(*items):
    bank = importing.SourceBank(index=0, label="bank 0")
    for index, (slot, name) in enumerate(items):
        bank.programs[slot] = importing.SourceProgram(
            index=index, slot=slot, name=name, record=_record(name)
        )
    return bank


async def _until(pilot, ready, attempts=200):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("condition never met")


async def _open(pilot, screen, seen):
    app = pilot.app
    app.push_screen(screen, seen.append)
    await _until(pilot, lambda: isinstance(app.screen, AppendBankScreen))
    await _until(pilot, lambda: len(app.screen.query("#append-table")) == 1)


def make(tmp_path):
    return NanosynedApp(
        DemoDevice(), catalog=cat.empty(), config_path=str(tmp_path / "config.toml")
    )


@pytest.mark.asyncio
async def test_fits(tmp_path):
    bank = _bank((0, "A"), (1, "B"))
    plan = importplan.plan_append(bank, [0, 1])
    screen = AppendBankScreen(bank, plan, start=0, gate=EditGate(armed=True))
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        table = screen.query_one("#append-table", DataTable)
        assert table.row_count == 2
        assert str(table.get_row_at(0)[2]) == "[b]000[/b]"
        assert str(table.get_row_at(0)[3]) == "free (Init)"
        assert "0 cut" in str(screen.query_one("#append-plan", Static).content)


@pytest.mark.asyncio
async def test_overflow_cut_list(tmp_path):
    bank = _bank((0, "A"), (1, "B"), (2, "C"))
    plan = importplan.plan_append(bank, [0])
    screen = AppendBankScreen(bank, plan, start=0, gate=EditGate())
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        table = screen.query_one("#append-table", DataTable)
        assert table.row_count == 3
        cuts = [str(table.get_row_at(i)[3]) for i in range(table.row_count)]
        assert "cut" in cuts
        warn = str(screen.query_one("#append-warning", Static).content)
        assert "cut" in warn


@pytest.mark.asyncio
async def test_ctrl_s_returns_plan(tmp_path):
    bank = _bank((0, "A"), (1, "B"))
    plan = importplan.plan_append(bank, [0, 1])
    gate = EditGate(armed=True)
    screen = AppendBankScreen(bank, plan, start=0, gate=gate)
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        await pilot.press("ctrl+s")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        assert "Append 2 programs?" in app.screen.prompt_text
        await pilot.press("y")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await _until(pilot, lambda: bool(seen))
        assert seen == [plan]


@pytest.mark.asyncio
async def test_s_returns_manual(tmp_path):
    bank = _bank((0, "A"))
    plan = importplan.plan_append(bank, [0])
    screen = AppendBankScreen(bank, plan, start=0, gate=EditGate())
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        await pilot.press("s")
        await _until(pilot, lambda: bool(seen))
        assert seen == [MANUAL]


@pytest.mark.asyncio
async def test_free_zero_refuses_ctrl_s_but_s_works(tmp_path):
    bank = _bank((0, "A"))
    plan = importplan.plan_append(bank, [])
    screen = AppendBankScreen(bank, plan, start=127, gate=EditGate(armed=True))
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, AppendBankScreen)
        assert not seen
        status = str(screen.query_one("#append-status", Static).content)
        assert "no free slots" in status
        await pilot.press("s")
        await _until(pilot, lambda: bool(seen))
        assert seen == [MANUAL]


@pytest.mark.asyncio
async def test_locked_gate_refuses(tmp_path):
    bank = _bank((0, "A"))
    plan = importplan.plan_append(bank, [0])
    screen = AppendBankScreen(bank, plan, start=0, gate=EditGate())
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, AppendBankScreen)
        assert not seen
        status = str(screen.query_one("#append-status", Static).content)
        assert "locked" in status


@pytest.mark.asyncio
async def test_cancel_returns_none(tmp_path):
    bank = _bank((0, "A"))
    plan = importplan.plan_append(bank, [0])
    screen = AppendBankScreen(bank, plan, start=0, gate=EditGate(armed=True))
    app = make(tmp_path)
    seen = []
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _open(pilot, screen, seen)
        await pilot.press("escape")
        await _until(pilot, lambda: len(seen) > 0)
        assert seen == [None]
