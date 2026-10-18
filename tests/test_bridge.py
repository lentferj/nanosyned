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

"""The MIDI bridge's process-level bits. No port is opened, no hardware."""

import signal

import pytest

from nano import bridge, verify
from nano import messages as m
from nano import records as rec
from nanosyned.demo import DemoDevice, demo_name

_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@pytest.fixture
def _restored_signals():
    """Put the process's handlers back however the test ends.

    Underscored so vulture, which does not know a pytest fixture is used by
    being named, does not report it as a dead function.
    """
    before = {sig: signal.getsignal(sig) for sig in _SIGNALS}
    try:
        yield
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


class TestCleanExit:
    """main() calls install_clean_exit() on the real-hardware path. It has
    to exist -- it did not, and the AttributeError was invisible because
    every test runs the demo path -- and it has to turn a termination
    signal into an unwinding SystemExit, or the port stays open."""

    def test_it_replaces_the_termination_handlers(self, _restored_signals):
        before = {sig: signal.getsignal(sig) for sig in _SIGNALS}
        bridge.install_clean_exit()
        for sig in _SIGNALS:
            assert callable(signal.getsignal(sig))
            assert signal.getsignal(sig) is not before[sig]

    def test_the_handler_raises_system_exit(self, _restored_signals):
        bridge.install_clean_exit()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)


# --- the write side ---------------------------------------------------------


class _FakePort:
    """One object standing in for both halves of an open port."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.inbox: list[tuple[list[int], float]] = []

    def send_message(self, data):
        self.sent.append(bytes(data))

    def get_message(self):
        return self.inbox.pop(0) if self.inbox else None

    def ignore_types(self, **_types):
        pass


def _program_record() -> bytes:
    """A 350-byte record that is not all zeros, so a lost byte shows."""
    return bytes((index * 7 + 3) & 0xFF for index in range(rec.PROGRAM_BYTES))


class TestWriteMethods:
    """Each sends exactly the store message and returns. Nothing is verified
    here: the gate, the backup, the log and the read-back are the caller's."""

    def test_write_program_sends_the_store(self):
        port = _FakePort()
        live = bridge.NanoBridge(port, port)
        record = _program_record()

        live.write_program(5, record)

        assert port.sent == [m.program_dump(5, record)]

    def test_write_program_refuses_the_silent_program(self):
        port = _FakePort()
        live = bridge.NanoBridge(port, port)

        with pytest.raises(m.ProtocolError, match="hardwired silent"):
            live.write_program(127, _program_record())

        assert port.sent == [], "the unit was sent a store it cannot honour"

    @pytest.mark.parametrize("number", [-1, 128])
    def test_write_program_refuses_a_number_outside_the_bank(self, number):
        port = _FakePort()
        live = bridge.NanoBridge(port, port)

        with pytest.raises(m.ProtocolError):
            live.write_program(number, _program_record())

        assert port.sent == []

    def test_the_other_stores_send_their_messages(self):
        port = _FakePort()
        live = bridge.NanoBridge(port, port)
        effects = bytes(rec.EFFECTS_BYTES)
        mix = bytes(rec.MIX_BYTES)
        glob = bytes(rec.GLOBAL_BYTES)

        live.write_effects(7, effects)
        live.write_edit_effects(effects)
        live.write_mix(100, mix)
        live.write_global(glob)
        live.midi_edit(m.MIDI_EDIT_PROGRAM, 2, 3, 1, -4, sound=1, channel=9)
        live.mode_select(True)

        assert port.sent == [
            m.effects_dump(7, effects),
            m.edit_effects_dump(effects),
            m.mix_dump(100, mix),
            m.global_dump(glob),
            m.midi_edit(m.MIDI_EDIT_PROGRAM, 2, 3, 1, -4, sound=1, channel=9),
            m.mode_select(True),
        ]

    def test_a_store_is_not_waited_on(self):
        """The unit answers a store with silence whether it worked or not,
        so a write must not sit through a timeout waiting for a reply."""
        port = _FakePort()
        live = bridge.NanoBridge(port, port, timeout=0.001)

        live.write_program(1, _program_record())

        assert port.get_message() is None


class TestVerify:
    def test_agreement_is_no_offsets(self):
        record = _program_record()
        assert verify.mismatches(record, record) == []

    def test_a_changed_byte_is_named_by_offset(self):
        sent = bytearray(_program_record())
        read_back = bytearray(sent)
        read_back[12] ^= 0x01

        assert verify.mismatches(bytes(sent), bytes(read_back)) == [12]

    def test_a_short_read_is_not_agreement(self):
        """Bytes past the shorter buffer are reported: a truncated record is
        a failed store, not a clean one."""
        assert verify.mismatches(b"\x01\x02\x03\x04", b"\x01\x02") == [2, 3]

    def test_describe_names_the_first_offsets(self):
        sent = bytes(range(64))
        read_back = bytearray(sent)
        for offset in (12, 40, 41):
            read_back[offset] ^= 0x80

        assert (
            verify.describe(sent, bytes(read_back))
            == "the unit did not take the record: 3 byte(s) differ (12, 40, 41)"
        )

    def test_describe_says_so_when_it_agrees(self):
        assert verify.describe(b"abc", b"abc") == "record read back byte-for-byte"

    def test_describe_uses_the_name_it_is_given(self):
        assert verify.describe(b"a", b"b", what="program").startswith(
            "the unit did not take the program:"
        )


class TestDemoWrites:
    """The demo models the unit closely enough to prove a round trip.

    `read back == written` is the whole test the bench performs against the
    hardware; proving the same comparison against the demo is what makes
    `nothing was written` -- `program_writes == []` -- checkable at all.
    """

    def test_a_written_program_reads_back(self):
        demo = DemoDevice()
        record = _program_record()

        demo.write_program(5, record)

        assert demo.read_program(5) == record
        assert verify.describe(record, demo.read_program(5)) == (
            "record read back byte-for-byte"
        )
        assert demo.program_writes == [(5, record)]

    def test_untouched_programs_keep_their_invented_names(self):
        demo = DemoDevice()
        assert rec.program_name(demo.read_program(3)) == (
            f"{demo_name('USER', 3):<{m.NAME_CHARS}}"
        )

    def test_the_silent_program_is_refused_and_not_written(self):
        demo = DemoDevice()

        with pytest.raises(m.ProtocolError, match="hardwired silent"):
            demo.write_program(127, _program_record())

        assert demo.program_writes == []

    def test_a_mix_round_trips(self):
        demo = DemoDevice()
        record = bytes((index * 3) & 0x7F for index in range(rec.MIX_BYTES))

        demo.write_mix(9, record)

        assert demo.read_mix(9) == record
        assert demo.mix_writes == [(9, record)]

    def test_the_global_round_trips(self):
        demo = DemoDevice()
        record = bytes(range(rec.GLOBAL_BYTES))

        demo.write_global(record)

        assert demo.read_global() == record
        assert demo.global_writes == [record]

    def test_edits_and_mode_changes_are_logged(self):
        demo = DemoDevice()

        demo.write_effects(4, bytes(rec.EFFECTS_BYTES))
        demo.write_edit_effects(bytes(rec.EFFECTS_BYTES))
        demo.midi_edit(m.MIDI_EDIT_MIX, 1, 2, 3, 4)
        demo.mode_select(False)

        assert demo.effect_writes == [(4, bytes(rec.EFFECTS_BYTES))]
        assert demo.edit_effect_writes == [bytes(rec.EFFECTS_BYTES)]
        assert demo.midi_edits == [(m.MIDI_EDIT_MIX, 1, 2, 3, 4, 0, 0)]
        assert demo.mode_selects == [False]

    def test_the_demo_has_the_launch_fields_too(self):
        """Structural parity with the bridge, so the app can report how a
        launch connected without asking which device it has."""
        demo = DemoDevice()
        assert demo.swept is False
        assert demo.probe_seconds == 0.0


class TestSweptReporting:
    def test_a_bridge_from_open_has_not_swept(self):
        port = _FakePort()
        live = bridge.NanoBridge(port, port)
        assert live.swept is False
        assert live.probe_seconds == 0.0

    def test_autodetect_says_it_swept_and_how_long(self, monkeypatch):
        made = []

        class _Answered:
            def __init__(self):
                self.timeout = bridge.PROBE_TIMEOUT

            def request(self, *_args, **_kwargs):
                return object()

            def close(self):
                self.closed = True

        def fake_open(cls, /, port, **rest):
            made.append(port)
            return _Answered()

        monkeypatch.setattr(bridge, "likely_ports", lambda: [])
        monkeypatch.setattr(bridge, "list_ports", lambda: ([], ["Fake Port 1"]))
        monkeypatch.setattr(bridge.NanoBridge, "open", classmethod(fake_open))

        got = bridge.NanoBridge.autodetect()

        assert made == ["Fake Port 1"]
        assert got.swept is True
        assert got.probe_seconds >= 0.0
        assert got.timeout == bridge.DEFAULT_TIMEOUT

    def test_the_remembered_path_does_not_claim_a_sweep(self, monkeypatch, tmp_path):
        class _Answered:
            def __init__(self):
                self.timeout = bridge.PROBE_TIMEOUT
                self.swept = False
                self.probe_seconds = 0.0

            def request(self, *_args, **_kwargs):
                return object()

            def close(self):
                pass

        monkeypatch.setattr(
            bridge.NanoBridge,
            "open",
            classmethod(lambda cls, /, port, **rest: _Answered()),
        )

        got = bridge.NanoBridge.connect(
            config_path=str(tmp_path / "config.toml"),
            remembered=("Fake Port 1", "Fake Port 1"),
        )

        assert got.swept is False
        assert got.probe_seconds == 0.0
