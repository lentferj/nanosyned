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

"""That the read path cannot make the instrument sound.

**This project has no audio path.** Nothing here can hear whether a read
made a noise, so a bare claim of silence would be unfalsifiable. What is
tested instead is the *mechanism*: a MIDI synthesizer makes sound by
receiving **Channel Voice** messages -- Note On/Off, Control Change,
Program Change, Pitch Bend, Channel and Poly aftertouch, status bytes
0x80-0xEF. System Exclusive that merely asks a question cannot make one
sound.

Two things are therefore established, and they are the strongest form of
the claim available without ears:

1. **Every read operation sends nothing but System Exclusive.** Exercised
   against a port that records everything and never answers, so every read
   times out -- which does not matter, because the send happens before the
   wait and is what is being inspected.
2. **``select()`` is the only code in the project that emits Channel Voice
   at all**, so the audible operation is reachable from exactly one place,
   and :class:`NanosynedApp` reaches it only through Enter (or the CLI's
   ``select`` command).

The second is checked by looking at the recorded bytes of a real selection,
so this file cannot pass by simply never exercising the case. The rule from
``CLAUDE.md`` and ``docs/PROMPT-PARITY.md`` section 4 is the same one the
sibling p2ked pins: moving the cursor never sends anything, and only
``select()`` makes a sound.
"""

import ast
import os
from contextlib import suppress

import pytest

from nano import banks, bridge
from nano import catalog as cat
from nano import favorites as fav
from nano import messages as m
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_SOURCE = os.path.join(_ROOT, "nano", "bridge.py")
APP_SOURCE = os.path.join(_ROOT, "nanosyned", "app.py")


class _RecordingOut:
    """A MIDI output that records instead of transmitting."""

    def __init__(self):
        self.sent = []

    def send_message(self, message):
        self.sent.append(list(message))

    def close_port(self):
        pass

    def delete(self):
        pass

    def ignore_types(self, **_kwargs):
        pass


class _SilentIn:
    """A MIDI input that never answers, so every read times out."""

    def get_message(self):
        return None

    def close_port(self):
        pass

    def delete(self):
        pass

    def ignore_types(self, **_kwargs):
        pass


def _voice_status(message):
    """The Channel Voice status byte, or ``None`` for anything else."""
    if message[0] == 0xF0:
        return None
    status = message[0] & 0xF0
    return status if 0x80 <= status <= 0xE0 else None


@pytest.fixture
def recording(monkeypatch):
    """A bridge onto a port that records sends and never replies.

    ``timeout`` is tiny because every read will time out, and there is no
    reply to wait for -- what is under test is what went *out*. The pacing
    between the 128 requests is a protocol question of its own (see
    ``bridge.SEND_GAP`` and ``TODO.md``), not this file's: zeroing it only
    keeps the suite quick.
    """
    monkeypatch.setattr(bridge, "SEND_GAP", 0.0)
    out = _RecordingOut()
    return bridge.NanoBridge(_SilentIn(), out, channel=0, timeout=0.001), out


def _run_ignoring_timeouts(call):
    """Run a read, which is expected to time out on a silent port."""
    with suppress(TimeoutError):
        call()


class TestReadsEmitNothingButSysEx:
    """Every read operation, one by one."""

    def _assert_only_sysex(self, out):
        assert out.sent, "nothing was sent -- the check would be vacuous"
        for message in out.sent:
            assert _voice_status(message) is None, (
                f"a read sent a Channel Voice message: {message!r}"
            )
            assert message[0] == 0xF0, f"not System Exclusive: {message!r}"
            assert message[-1] == 0xF7, f"truncated System Exclusive: {message!r}"

    def test_the_identity_request(self, recording):
        """Not an Alesis message at all, and still not Channel Voice.

        The global dump request behind it is the flush: this unit holds an
        Identity Reply until it next answers something else.
        """
        dev, out = recording
        _run_ignoring_timeouts(dev.identify)
        self._assert_only_sysex(out)
        assert out.sent == [
            list(m.identity_request()),
            list(m.global_dump_request()),
        ]

    def test_a_program_read(self, recording):
        dev, out = recording
        _run_ignoring_timeouts(lambda: dev.read_program(5))
        self._assert_only_sysex(out)
        assert out.sent == [list(m.program_dump_request(5))]

    def test_every_program_name(self, recording):
        """One request per user program, and 128 of them."""
        dev, out = recording
        dev.read_program_names()
        self._assert_only_sysex(out)
        assert out.sent == [
            list(m.program_dump_request(number))
            for number in range(banks.PROGRAMS_PER_BANK)
        ]

    def test_the_edit_buffer_read(self, recording):
        """Whatever the unit is playing, asked for and not changed."""
        dev, out = recording
        _run_ignoring_timeouts(dev.read_edit_program)
        self._assert_only_sysex(out)
        assert out.sent == [list(m.edit_program_dump_request())]

    def test_a_mix_read(self, recording):
        dev, out = recording
        _run_ignoring_timeouts(lambda: dev.read_mix(9))
        self._assert_only_sysex(out)
        assert out.sent == [list(m.mix_dump_request(9))]

    def test_every_mix_name(self, recording):
        dev, out = recording
        dev.read_mix_names()
        self._assert_only_sysex(out)
        assert out.sent == [
            list(m.mix_dump_request(number)) for number in range(banks.MIXES)
        ]

    def test_the_global_read(self, recording):
        dev, out = recording
        _run_ignoring_timeouts(dev.read_global)
        self._assert_only_sysex(out)
        assert out.sent == [list(m.global_dump_request())]

    def test_the_whole_read_path_together(self, recording):
        """One run over every read, as the browser and the CLI use them."""
        dev, out = recording
        for call in (
            dev.identify,
            lambda: dev.read_program(0),
            dev.read_program_names,
            dev.read_edit_program,
            lambda: dev.read_mix(0),
            dev.read_mix_names,
            dev.read_global,
        ):
            _run_ignoring_timeouts(call)
        self._assert_only_sysex(out)


class TestSelectIsTheOnlyAudibleOperation:
    """And the check above can actually detect one.

    Without this, every test above would also pass on a build in which
    ``select`` had been changed to send nothing at all -- which is the
    failure mode of a check that only ever proves a negative.
    """

    def test_a_selection_sends_bank_select_and_a_program_change(self, recording):
        dev, out = recording
        dev.select(banks.slot("USER", 5))
        assert [message for message in out.sent if _voice_status(message)], (
            "a selection emitted no Channel Voice; the read tests would "
            "pass for the wrong reason"
        )
        # Controller 0 (Bank Select MSB) and then Program Change, in that
        # order -- the order the protocol requires. Controller 32 is never
        # sent: the manual says this unit ignores it.
        assert out.sent == [
            [0xB0, 0x00, banks.bank("USER").select],
            [0xC0, 5],
        ]

    def test_the_channel_lands_in_the_status_byte(self, recording):
        dev, out = recording
        dev.channel = 9
        dev.select(banks.slot("USER", 5))
        assert out.sent[0][0] == 0xB9, "Bank Select status"
        assert out.sent[1][0] == 0xC9, "Program Change status"
        assert len(out.sent) == 2, "Bank Select 32 must not be sent either"

    def test_a_bad_channel_is_refused_before_anything_is_sent(self, recording):
        """The one operation that can sound still refuses a bad address."""
        dev, out = recording
        dev.channel = 16
        with pytest.raises(ValueError):
            dev.select(banks.slot("USER", 5))
        assert out.sent == [], "a refused selection still put bytes on the wire"


# --- the structural half -----------------------------------------------------

#: Builders whose bytes are Channel Voice rather than System Exclusive.
_CHANNEL_VOICE_BUILDERS = frozenset({"bank_select", "program_change"})

#: Functions allowed to send something the AST cannot read as a SysEx
#: builder. ``_send`` is the transport itself; ``request`` passes a
#: computed frame that its callers built with ``messages.*``. Both are
#: tunnels for System Exclusive, and neither can make a sound on its own.
#: ``_send_record`` is a funnel like ``_send``: it takes a frame the caller
#: already built, adds the record gap, and is called only from the dump
#: writes. ``request`` is here because it sends the request it was handed.
_FUNNELS = frozenset({"_send", "_send_record", "request"})


def _parsed(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _functions(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


def _send_sites(node):
    """Every ``self._send(...)``/``send_message(...)`` call under ``node``."""
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        if not isinstance(inner.func, ast.Attribute):
            continue
        if inner.func.attr in ("_send", "send_message"):
            yield inner


def _builds_sysex(call):
    """Whether a send's argument is an ``messages`` SysEx builder call.

    A computed argument is deliberately *not* treated as SysEx here, so a
    new sender has to be either one of the funnels or this function's
    business. ``bank_select`` and ``program_change`` are the two builders
    that produce Channel Voice.
    """
    if not call.args:
        return False
    argument = call.args[0]
    if not isinstance(argument, ast.Call):
        return False
    if not isinstance(argument.func, ast.Attribute):
        return False
    value = argument.func.value
    if not (isinstance(value, ast.Name) and value.id == "m"):
        return False
    return argument.func.attr not in _CHANNEL_VOICE_BUILDERS


def _non_sysex_senders(tree):
    """``(function, lineno)`` for every send that may be Channel Voice.

    ``select`` is included on purpose: the caller asserts it is the *only*
    name in the result, which is the rule, and a build in which it had been
    removed would fail the same test rather than passing vacuously.
    """
    offenders = []
    for node in _functions(tree):
        if node.name in _FUNNELS:
            continue
        for site in _send_sites(node):
            if not _builds_sysex(site):
                offenders.append((node.name, site.lineno))
    return offenders


def _device_calls(tree):
    """``(function, method)`` for every ``self.device.<method>()`` call."""
    calls = []
    for node in _functions(tree):
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            if not isinstance(inner.func, ast.Attribute):
                continue
            value = inner.func.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "device"
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                calls.append((node.name, inner.func.attr))
    return calls


#: The methods :class:`nano.device.Device` declares today. The write path is
#: still arriving in that Protocol, so the demo's public methods are allowed
#: as well -- both real implementations answer them, and a raw
#: ``device.send`` is in neither set.
_PROTOCOL_METHODS = frozenset(
    {
        "close",
        "identify",
        "read_program",
        "read_program_names",
        "read_edit_program",
        "read_mix",
        "read_mix_names",
        "read_global",
        "read_effects",
        "select",
    }
)


class TestTheProjectHasNoOtherSender:
    """A structural check, so a new sender cannot be added quietly.

    The behavioural tests above cover the read path as it exists. This one
    covers the *rule*: anywhere in ``nano/bridge.py`` that sends to the
    port, it is either building System Exclusive or is inside ``select``,
    and ``nanosyned/app.py`` reaches ``select`` from exactly one worker.
    """

    def test_select_is_the_only_non_sysex_send_site(self):
        offenders = _non_sysex_senders(_parsed(BRIDGE_SOURCE))
        assert {name for name, _ in offenders} == {"select", "select_mix"}, (
            f"Channel Voice sent outside select(): {offenders}"
        )

    def test_the_send_wrapper_is_the_only_outlet(self):
        """Every send goes through ``_send``, which takes bytes."""
        functions = _functions(_parsed(BRIDGE_SOURCE))
        outlets = {
            node.name
            for node in functions
            for inner in ast.walk(node)
            if isinstance(inner, ast.Attribute) and inner.attr == "send_message"
        }
        assert outlets == {"_send"}, f"something else calls the port: {outlets}"

    def test_the_app_reaches_select_only_from_the_worker(self):
        calls = _device_calls(_parsed(APP_SOURCE))
        selects = [call for call in calls if call[1] == "select"]
        assert selects == [("_select_worker", "select")], (
            f"select() is reachable from {selects}; it must be the worker only"
        )
        # Every call is one of the Protocol's promises or one the demo also
        # answers. A raw `device.send(...)` is in neither, so a new sender
        # cannot slip through this half of the rule either.
        known = _PROTOCOL_METHODS | {
            name for name in dir(DemoDevice) if not name.startswith("_")
        }
        unknown = {method for _, method in calls} - known
        assert not unknown, f"the app calls non-protocol device methods: {unknown}"

    def test_the_app_never_touches_the_port_itself(self):
        tree = _parsed(APP_SOURCE)
        offenders = [
            inner.lineno
            for inner in ast.walk(tree)
            if isinstance(inner, ast.Attribute) and inner.attr == "send_message"
        ]
        assert not offenders, f"app.py calls send_message at lines {offenders}"

    def test_the_check_can_fail(self):
        """A read that emits Program Change must be caught.

        The same shape as p2ked's negative control: a guard that passes
        because it matched nothing is worse than no guard, and the edit
        that would make this one vacuous is exactly the one a future
        feature is tempted into.
        """
        synthetic = ast.parse(
            "class Fake:\n"
            "    def read_names(self):\n"
            "        self._send(m.program_change(1))\n"
            "    def read_safe(self):\n"
            "        self._send(m.program_dump_request(0))\n"
            "    def select(self, target):\n"
            "        self._send(m.bank_select(1))\n"
        )
        offenders = _non_sysex_senders(synthetic)
        assert {name for name, _ in offenders} == {"read_names", "select"}, (
            "the structural check does not catch a read sending Channel "
            "Voice; it would pass on the tree it exists to guard"
        )


# --- the browser-level half --------------------------------------------------


def _assert_silent(device):
    """Nothing that changes, stores or plays anything went out."""
    assert device.selected_log == [], "the browser selected something"
    assert device.program_writes == []
    assert device.effect_writes == []
    assert device.edit_effect_writes == []
    assert device.mix_writes == []
    assert device.global_writes == []
    assert device.midi_edits == []
    assert device.mode_selects == []


class TestTheBrowserIsSilentUntilEnter:
    """Moving, searching and annotating send nothing.

    The byte-level proof is above, against the raw bridge. This is the
    app-level version that complements :class:`tests.test_app.TestCursorIsSilent`:
    one browser run over every silent gesture, plus a positive control so
    the assertions cannot pass because Enter was never wired up either.
    """

    async def test_navigation_annotation_and_search_send_nothing(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        catalog = cat.Catalog([cat.Entry("GM", 0, "Invented Name")])
        device = DemoDevice()
        app = NanosynedApp(device, catalog=catalog, favorites=store)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()

                # The cursor, in both panes.
                app.query_one("#slot-table").focus()
                for _ in range(12):
                    await pilot.press("down")
                await pilot.press("end")
                for _ in range(6):
                    await pilot.press("up")
                app.query_one("#bank-table").focus()
                for _ in range(len(banks.BANKS) + 2):
                    await pilot.press("down")

                # Channel and view changes.
                app.query_one("#slot-table").focus()
                await pilot.press("]")
                await pilot.press("[")
                for _ in range(3):
                    await pilot.press("v")

                # Annotating the slot under the cursor.
                await pilot.press("f")
                for _ in range(4):
                    await pilot.pause()
                app.action_edit_rating()
                await pilot.pause()
                app.screen.dismiss(3)
                for _ in range(4):
                    await pilot.pause()

                # A search, which reads the catalog and the store only.
                app.action_search()
                await pilot.pause()
                app.screen.dismiss(
                    ("Invented", {"names": True, "tags": True, "notes": True})
                )
                for _ in range(4):
                    await pilot.pause()

                _assert_silent(device)
        finally:
            store.close()

    async def test_enter_is_the_one_thing_that_sends(self, tmp_path):
        """The positive control: the silence above is not a dead keyboard."""
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        device = DemoDevice()
        app = NanosynedApp(device, catalog=cat.empty(), favorites=store)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#slot-table").focus()
                await pilot.press("enter")
                for _ in range(20):
                    await pilot.pause()
                assert len(device.selected_log) == 1, (
                    "Enter did not reach select(); the silent tests above "
                    "would pass for the wrong reason"
                )
                assert device.program_writes == []
        finally:
            store.close()
