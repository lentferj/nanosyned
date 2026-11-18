# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

import pytest

from nano import backup as bk
from nano import dumps, params
from nano import messages as m
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    """Backups go beside the settings directory, not into the checkout."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    return tmp_path / "config-home" / "nanosyned" / "backups"


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class PersistentDemo(DemoDevice):
    """A demo the CLI may close between calls without losing its store."""

    def close(self) -> None:
        pass


def use_device(monkeypatch, device):
    """Make ``--demo`` hand every invocation the same device."""

    def factory(**kwargs):
        if "channel" in kwargs:
            device.channel = kwargs["channel"]
        return device

    monkeypatch.setattr("nanosyned.demo.DemoDevice", factory)
    return device


def dump_program(capsys, config_path, tmp_path, number: int = 3) -> tuple[str, str]:
    path = str(tmp_path / f"program-{number}.syx")
    code, out, _err = run(
        capsys,
        "--demo",
        "--config",
        config_path,
        "dump",
        "program",
        str(number),
        "--file",
        path,
    )
    assert code == 0
    return path, out


class TestDump:
    def test_a_program_dump_is_a_valid_syx(self, config_path, tmp_path, capsys):
        path, _out = dump_program(capsys, config_path, tmp_path)
        library = dumps.read_syx_file(path)
        assert sorted(library.programs) == [3]
        assert len(library.programs[3]) >= rec.PROGRAM_BYTES
        assert library.globals_ is None

    def test_a_dump_names_its_bytes_and_its_slot(self, config_path, tmp_path, capsys):
        path, out = dump_program(capsys, config_path, tmp_path)
        assert "408 bytes" in out
        assert "350-byte user program" in out
        assert "user program 003" in out
        assert path in out

    def test_a_global_dump_is_twenty_bytes_of_data(self, config_path, tmp_path, capsys):
        path = str(tmp_path / "global.syx")
        code, out, _ = run(
            capsys, "--demo", "--config", config_path, "dump", "global", "--file", path
        )
        assert code == 0
        library = dumps.read_syx_file(path)
        assert library.globals_ is not None
        assert len(library.globals_) >= rec.GLOBAL_BYTES
        assert "20-byte global settings" in out

    def test_a_dump_outside_the_slot_range_is_refused(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        with pytest.raises(SystemExit, match="outside 0-99"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "dump",
                "mix",
                "100",
                "--file",
                str(tmp_path / "mix.syx"),
            )
        assert device.midi_edits == []

    def test_effects_use_the_request_the_bridge_offers(
        self, config_path, tmp_path, capsys
    ):
        payload = bytes(rec.EFFECTS_BYTES)

        class Packet:
            def data(self):
                return payload

        class Device:
            channel = 0

            def __init__(self):
                self.requests = []

            def request(self, message, function, *, number=None):
                self.requests.append((message, function, number))
                return Packet()

        device = Device()
        path = str(tmp_path / "effects.syx")
        args = type(
            "Args", (), {"dump_command": "effects", "number": 4, "file": path}
        )()
        cli._cmd_dump(device, args)
        assert device.requests == [
            (m.effects_dump_request(4), m.Function.USER_EFFECTS_DUMP, 4)
        ]
        assert dumps.read_syx_file(path).effects[4][: rec.EFFECTS_BYTES] == payload


class TestSendGate:
    def test_send_without_the_flags_opens_nothing(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            "nanosyned.demo.DemoDevice",
            lambda **_kw: pytest.fail("a gated send opened a device"),
        )
        path = str(tmp_path / "one.syx")
        with pytest.raises(SystemExit) as caught:
            run(capsys, "--demo", "--config", config_path, "send", path)
        message = str(caught.value)
        assert "--allow-write" in message
        assert "--yes" in message

    def test_send_needs_both_halves(self, config_path, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "nanosyned.demo.DemoDevice",
            lambda **_kw: pytest.fail("a gated send opened a device"),
        )
        path = str(tmp_path / "one.syx")
        with pytest.raises(SystemExit, match="--yes"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "send",
                path,
                "--allow-write",
            )

    def test_set_without_the_flags_opens_nothing(
        self, config_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            "nanosyned.demo.DemoDevice",
            lambda **_kw: pytest.fail("a gated set opened a device"),
        )
        with pytest.raises(SystemExit, match="--allow-write"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "set",
                "program",
                "0",
                "0",
                "0",
                "5",
            )

    def test_backup_restore_without_the_flags_opens_nothing(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            "nanosyned.demo.DemoDevice",
            lambda **_kw: pytest.fail("a gated restore opened a device"),
        )
        with pytest.raises(SystemExit, match="--allow-write"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "backup",
                "restore",
                str(tmp_path / "missing.json"),
            )

    def test_send_skips_the_hardwired_silent_program_in_a_bank(
        self, config_path, tmp_path, capsys
    ):
        path = str(tmp_path / "bank.syx")
        with open(path, "wb") as handle:
            handle.write(m.program_dump(3, bytes(rec.PROGRAM_BYTES)))
            handle.write(m.program_dump(127, bytes(rec.PROGRAM_BYTES)))
        code, out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "--allow-write",
            "--yes",
            "send",
            path,
        )
        assert code == 0
        assert "1 record(s) to write" in out
        assert "user program 127 is hardwired silent; skipped" in err

    def test_send_refuses_naming_the_hardwired_silent_program(
        self, config_path, tmp_path, capsys
    ):
        path = str(tmp_path / "one.syx")
        with open(path, "wb") as handle:
            handle.write(m.program_dump(3, bytes(rec.PROGRAM_BYTES)))
        with pytest.raises(SystemExit, match="hardwired silent"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "--allow-write",
                "--yes",
                "send",
                path,
                "--program",
                "127",
            )


class TestSend:
    def test_dump_then_send_is_byte_exact_on_one_device(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path, _out = dump_program(capsys, config_path, tmp_path, number=3)
        before = bytes(device.read_program(3))

        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "1 record(s) to write" in out
        assert "wrote    408 bytes to user program 003" in out
        assert "read back byte-for-byte" in out
        read_back = device.read_program(3)[: rec.PROGRAM_BYTES]
        assert read_back == before[: rec.PROGRAM_BYTES]

    def test_send_skips_the_mix_edit_buffer(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        before = bytes(device.read_mix(0))[: rec.MIX_BYTES]
        path = str(tmp_path / "bank.syx")
        with open(path, "wb") as handle:
            handle.write(m.program_dump(3, bytes(rec.PROGRAM_BYTES)))
            handle.write(m.mix_dump(100, bytes(rec.MIX_BYTES)))

        code, out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "1 record(s) to write" in out
        assert "mix 100 is the edit buffer" in err
        assert bytes(device.read_mix(0))[: rec.MIX_BYTES] == before

    def test_send_backs_up_the_destination_before_writing(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        old = bytes(device.read_program(5))
        path, _out = dump_program(capsys, config_path, tmp_path, number=3)

        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--program",
            "5",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "user program 005" in out
        backups = bk.list_backups()
        assert len(backups) == 1
        assert backups[0].slot == "PROGRAM:005"
        assert backups[0].blocks["program"] == old[: rec.PROGRAM_BYTES]
        assert "backup " in out

    def test_program_override_moves_only_the_named_slot(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        untouched = bytes(device.read_program(3))
        path, _out = dump_program(capsys, config_path, tmp_path, number=3)
        source = bytes(device.read_program(3))

        code, _out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--program",
            "5",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        read_back = device.read_program(5)[: rec.PROGRAM_BYTES]
        assert read_back == source[: rec.PROGRAM_BYTES]
        assert device.read_program(3) == untouched

    def test_a_write_that_did_not_land_is_a_mismatch_and_an_error(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        device.write_program = lambda number, record, **_kw: None
        path, _out = dump_program(capsys, config_path, tmp_path, number=3)

        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--program",
            "5",
            "--allow-write",
            "--yes",
        )
        assert code == 1
        assert "MISMATCH" in out
        assert "byte(s) differ" in out
        assert "the backup is" in out

    def test_a_multi_record_file_writes_every_record(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = str(tmp_path / "two.syx")
        with open(path, "wb") as handle:
            handle.write(m.program_dump(1, bytes(device.read_program(1))))
            handle.write(m.mix_dump(2, bytes(device.read_mix(2))))

        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "send",
            path,
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "2 record(s) to write" in out
        assert [number for number, _ in device.program_writes] == [1]
        assert [number for number, _ in device.mix_writes] == [2]
        assert len(bk.list_backups()) == 2


class TestBackupList:
    def test_list_needs_no_unit_and_no_checkout(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            "nano.bridge.NanoBridge.connect",
            classmethod(lambda *_a, **_kw: pytest.fail("backup list opened a port")),
        )
        path = bk.save(
            "PROGRAM:005",
            kind="program",
            name="Tin Coil",
            blocks={"program": bytes(rec.PROGRAM_BYTES)},
            source="test",
        )
        code, out, _ = run(capsys, "--config", config_path, "backup", "list")
        assert code == 0
        assert "PROGRAM:005" in out
        assert "Tin Coil" in out
        assert "program" in out
        assert str(bk.backup_dir()) in out
        assert path

    def test_list_says_so_when_there_is_nothing(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "backup", "list")
        assert code == 0
        assert "(no backups)" in out


class TestBackupRestore:
    def test_restore_writes_the_backup_back(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        old = bytes(device.read_program(9))
        path = bk.save(
            "PROGRAM:009",
            kind="program",
            name="Old Nine",
            blocks={"program": old},
            source="test",
        )
        device.write_program(9, bytes(rec.PROGRAM_BYTES))

        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "restore",
            path,
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "user program 009" in out
        assert "read back byte-for-byte" in out
        assert "backup " in out
        assert device.read_program(9)[: rec.PROGRAM_BYTES] == old[: rec.PROGRAM_BYTES]
        # The restore point this restore wrote holds what was there before it.
        backups = bk.list_backups()
        assert len(backups) == 2
        restore_points = [b for b in backups if b.source == "nanocli (before write)"]
        assert len(restore_points) == 1
        assert restore_points[0].slot == "PROGRAM:009"
        assert restore_points[0].blocks["program"] == bytes(rec.PROGRAM_BYTES)

    def test_restore_refuses_the_hardwired_silent_program(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        path = bk.save(
            "PROGRAM:127",
            kind="program",
            name="Off",
            blocks={"program": bytes(rec.PROGRAM_BYTES)},
            source="test",
        )
        with pytest.raises(SystemExit, match="hardwired silent"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "backup",
                "restore",
                path,
                "--allow-write",
                "--yes",
            )

    def test_restore_needs_a_slot_when_the_backup_has_none(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        path = bk.save(
            "anonymous",
            kind="program",
            name="Nameless",
            blocks={"program": bytes(rec.PROGRAM_BYTES)},
            source="test",
        )
        with pytest.raises(SystemExit, match="give --number"):
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "backup",
                "restore",
                path,
                "--allow-write",
                "--yes",
            )


class EditingDemo(PersistentDemo):
    """A demo whose MIDI Edit really moves the edit buffer.

    ``DemoDevice.midi_edit`` records the message and changes nothing, which
    is honest for a device with no edit buffer -- and would make a read-back
    test pass only by never checking anything.
    """

    def __init__(self) -> None:
        super().__init__()
        self.buffer = bytearray(rec.PROGRAM_BYTES)
        self.global_buffer = bytearray(rec.GLOBAL_BYTES)
        self.mix_buffer = bytearray(rec.MIX_BYTES)
        self.channel_buffers = {}
        self.mode_selects = []
        self.logs = []

    def read_edit_program(self, *, edit=0, timeout: float | None = None) -> bytes:
        self.logs.append(("read_edit_program", edit))
        if edit == 0:
            return bytes(self.buffer)
        if edit not in self.channel_buffers:
            self.channel_buffers[edit] = bytearray(rec.PROGRAM_BYTES)
        return bytes(self.channel_buffers[edit])

    def read_global(self, *, timeout: float | None = None) -> bytes:
        self.logs.append(("read_global",))
        return bytes(self.global_buffer)

    def read_mix(self, number, *, timeout: float | None = None) -> bytes:
        assert number == 100
        self.logs.append(("read_mix", number))
        return bytes(self.mix_buffer)

    def read_edit_program_buffer(self, edit=0):
        if edit == 0:
            return self.buffer
        if edit not in self.channel_buffers:
            self.channel_buffers[edit] = bytearray(rec.PROGRAM_BYTES)
        return self.channel_buffers[edit]

    def mode_select(self, mix_mode: bool) -> None:
        self.mode_selects.append(mix_mode)
        self.logs.append(("mode_select", mix_mode))

    def midi_edit(  # noqa: PLR0913 -- the protocol's seven fields
        self,
        mode,
        function,
        page,
        pot,
        value,
        *,
        sound=0,
        channel=0,
        timeout=None,
    ) -> None:
        m.midi_edit(mode, function, page, pot, value, sound=sound, channel=channel)
        self.midi_edits.append((mode, function, page, pot, value, sound, channel))
        if mode == 0:  # global
            param = params.at("global", function, page, pot)
            if param is not None:
                # global fields stored directly as bits in global buffer
                rec.encode_bit_field(
                    self.global_buffer, param, value & ((1 << param.bits) - 1)
                )
            return
        if mode == 1:  # mix
            param = params.at("mix", function, page, pot, channel=channel)
            if param is not None:
                rec.encode_bit_field(
                    self.mix_buffer, param, params.stored_for(param, param.clamp(value))
                )
            return
        if mode == 2:  # program
            param = params.at(
                "program", function, page, pot, sound=sound, channel=channel
            )
            if param is not None:
                target = self.read_edit_program_buffer(edit=channel + 1)
                rec.encode_bit_field(
                    target, param, params.stored_for(param, param.clamp(value))
                )
            return
        if mode == 3:  # effects
            return


class TestSet:
    def test_set_prints_the_frame_and_reads_it_back(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "program",
            "0",
            "0",
            "0",
            "5",
            "--allow-write",
            "--yes",
            "--force-unverified",
        )
        assert code == 0
        assert "frame    F0 00 00 0E 0E 10 40 00 00 05 F7  (11 bytes)" in out
        assert "Sample group" in out
        assert "read-back  Sample group = 5" in out
        assert device.midi_edits == [(2, 0, 0, 0, 5, 0, 0)]
        assert True in device.mode_selects  # program rows go through mix mode

    def test_verified_global_row(self, config_path, monkeypatch, capsys):
        device = use_device(monkeypatch, EditingDemo())
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "global",
            "0",
            "0",
            "2",
            "0",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert ("mode_select", False) in device.logs
        assert ("read_global",) in device.logs
        assert "read-back" in out

    def test_verified_mix_row(self, config_path, monkeypatch, capsys):
        device = use_device(monkeypatch, EditingDemo())
        # Channel 1 enable is verified in mix, raw law
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "mix",
            "0",
            "0",
            "3",
            "1",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert ("mode_select", True) in device.logs
        assert ("read_mix", 100) in device.logs
        assert "Channel 1 enable = 1" in out

    def test_verified_program_row_uses_channel_plus_one(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        code, _out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "program",
            "1",
            "0",
            "0",
            "10",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert ("mode_select", True) in device.logs
        assert any(
            call[0] == "read_edit_program" and call[1] == 1 for call in device.logs
        )

    def test_effects_has_no_read_back(self, config_path, monkeypatch, capsys):
        use_device(monkeypatch, EditingDemo())
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "effects",
            "0",
            "0",
            "0",
            "1",
            "--allow-write",
            "--yes",
            "--force-unverified",
        )
        assert code == 0
        assert "ignores an effects 10" in out
        assert "nothing was verified" in out

    def test_mismatch_returns_1_and_names_buffer(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())

        def bad_read_mix(self, number, *, timeout=None):
            # return buffer with different value
            buf = bytearray(rec.MIX_BYTES)
            return bytes(buf)

        device.read_mix = bad_read_mix.__get__(device, EditingDemo)
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "mix",
            "0",
            "0",
            "3",
            "1",
            "--allow-write",
            "--yes",
        )
        assert code == 1
        assert "the mix edit buffer (100)" in out

    def test_channel_after_the_subcommand_is_the_send_channel(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "program",
            "0",
            "0",
            "0",
            "5",
            "--channel",
            "5",
            "--allow-write",
            "--yes",
            "--force-unverified",
        )
        assert code == 0
        assert "channel  5, sound 0, value 5" in out
        assert device.channel == 4
        assert device.midi_edits[-1][-1] == 4

    def test_set_names_an_address_it_does_not_know(
        self, config_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, EditingDemo())
        with pytest.raises(SystemExit) as caught:
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "set",
                "program",
                "16",
                "23",
                "3",
                "1",
                "--allow-write",
                "--yes",
            )
        assert "no parameter at mode program" in str(caught.value)

    def test_set_on_unverified_row_refused_without_force(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        with pytest.raises(SystemExit) as caught:
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "set",
                "program",
                "0",
                "0",
                "0",
                "5",
                "--allow-write",
                "--yes",
            )
        assert "is a transcription" in str(caught.value)
        assert device.midi_edits == []

    def test_set_on_unverified_row_with_force_unverified_sends(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "program",
            "0",
            "0",
            "0",
            "5",
            "--allow-write",
            "--yes",
            "--force-unverified",
        )
        assert code == 0
        assert len(device.midi_edits) > 0
        assert "unverified" in err

    def test_set_on_verified_row_sends_without_force(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        # Pitch transpose* is verified (global)
        code, _out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "set",
            "global",
            "0",
            "0",
            "2",
            "0",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert len(device.midi_edits) > 0

    def test_set_at_unknown_address_refused_nothing_sent(
        self, config_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, EditingDemo())
        with pytest.raises(SystemExit) as caught:
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "set",
                "program",
                "99",
                "99",
                "99",
                "1",
                "--allow-write",
                "--yes",
            )
        assert "no parameter at mode" in str(caught.value)
        assert device.midi_edits == []
