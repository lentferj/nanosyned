# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The transport is ported from the sibling x5ded, kwsed, p2ked, s3ked and
# k2kremote projects. The protocol it carries is Alesis's.
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

"""Talking to the NanoSynth.

**Every request this bridge sends comes back.** The unit this was written
against sits behind another synth acting as a MIDI interface, and that
chain has a soft thru in it: send a Program Dump Request and the first
thing that arrives is the Program Dump Request. A reply is therefore never
identified by "an Alesis message arrived" but by its opcode, and
:data:`messages.Function.REPLY_TO` is the table that says which opcode
answers which. This is the same shape of trap as a Thru loop being taken
for an Identity Reply, and the same answer: match on what only a reply can
carry.

The second thing that chain does is deliver replies late. A request that
has already timed out can be answered while the *next* request is waiting,
so a read that accepts any dump of the right kind will file one object's
data under another's number. Every read here checks the number too.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from nano import banks
from nano import messages as m
from nano import records as rec

__all__ = [
    "NanoBridge", "DeviceError", "list_ports", "likely_ports",
    "DEFAULT_TIMEOUT", "PROBE_TIMEOUT", "SEND_GAP", "SELECT_GAP",
]


class DeviceError(RuntimeError):
    """Something about the connection, not about the music."""


#: What a request is worth waiting for once the port is known good.
DEFAULT_TIMEOUT = 2.0

#: What one port is worth while sweeping for the instrument. Short on
#: purpose: ports that are not it should not cost seconds each.
PROBE_TIMEOUT = 0.5

#: Between messages in a run. A **guess**, unlike the sibling s3ked's
#: measured equivalents, and labelled as one at the point of use. The
#: NanoSynth's manual documents no inter-message timing because it
#: documents no System Exclusive at all. Measuring it is a TODO item.
SEND_GAP = 0.010

#: After a Bank Select, before the Program Change. Also a guess.
SELECT_GAP = 0.005


def _rtmidi():
    try:
        import rtmidi
    except ImportError as exc:                      # pragma: no cover
        raise DeviceError(
            "python-rtmidi is not installed, so no MIDI port can be "
            "opened. nanosyned still runs with --demo, which opens none."
        ) from exc
    return rtmidi


def list_ports() -> Tuple[List[str], List[str]]:
    """``(inputs, outputs)`` as rtmidi names them."""
    rtmidi = _rtmidi()
    midi_in, midi_out = rtmidi.MidiIn(), rtmidi.MidiOut()
    try:
        return list(midi_in.get_ports()), list(midi_out.get_ports())
    finally:
        midi_in.delete()
        midi_out.delete()


def likely_ports() -> List[str]:
    """Ports whose name suggests the instrument. Only an ordering.

    A name hint cannot decide anything here and is not allowed to. This
    NanoSynth has no USB of its own: it hangs off a DIN cable behind
    whatever interface the user happens to have, and on the bench that was
    a *different manufacturer's synth* acting as the interface. No hint
    would ever have matched it. The Identity Reply decides; this only
    changes the order ports are tried in.
    """
    _, outs = list_ports()
    wanted = ("nano", "alesis", "qs")
    return [p for p in outs if any(w in p.lower() for w in wanted)]


class NanoBridge:
    """One open pair of ports, and the requests this program makes."""

    def __init__(self, midi_in, midi_out, *, channel: int = 0,
                 description: str = "", timeout: float = DEFAULT_TIMEOUT
                 ) -> None:
        self._in = midi_in
        self._out = midi_out
        self.channel = channel
        self.description = description
        self.timeout = timeout
        #: The port names as opened, kept apart from `description`, which
        #: is "out -> in" for display and is not something open() accepts
        #: back. The sibling p2ked saved the description as a port name and
        #: produced a config that never matched.
        self.port: Optional[str] = None
        self.recv_port: Optional[str] = None
        try:
            self._in.ignore_types(sysex=False, timing=True,
                                  active_sense=True)
        except AttributeError:                      # a test double
            pass

    # --- lifecycle ----------------------------------------------------------

    @classmethod
    def open(cls, port: str, *, recv_port: Optional[str] = None,
             channel: int = 0, timeout: float = DEFAULT_TIMEOUT
             ) -> "NanoBridge":
        rtmidi = _rtmidi()
        ins, outs = list_ports()
        listen = recv_port or port
        if port not in outs:
            raise DeviceError(f"no output port named {port!r}; have {outs}")
        if listen not in ins:
            raise DeviceError(f"no input port named {listen!r}; have {ins}")
        midi_out, midi_in = rtmidi.MidiOut(), rtmidi.MidiIn()
        try:
            # If the second open_port raises -- the port vanished between
            # the listing and here, or another program took it -- the
            # first client is already open and nothing would close it.
            midi_out.open_port(outs.index(port))
            midi_in.open_port(ins.index(listen))
        except Exception:
            for client in (midi_in, midi_out):
                try:
                    client.close_port()
                    client.delete()
                except Exception:
                    pass
            raise
        bridge = cls(midi_in, midi_out, channel=channel,
                     description=f"{port} -> {listen}", timeout=timeout)
        bridge.port = port
        bridge.recv_port = listen
        return bridge

    def close(self) -> None:
        for client in (self._in, self._out):
            try:
                client.close_port()
                client.delete()
            except Exception:
                pass

    def __enter__(self) -> "NanoBridge":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # --- the wire -----------------------------------------------------------

    def _drain(self) -> None:
        while self._in.get_message() is not None:
            pass

    def _send(self, data: bytes) -> None:
        self._out.send_message(list(data))

    def request(self, outgoing: bytes, wanted: int, *,
                number: Optional[int] = None,
                timeout: Optional[float] = None) -> m.Packet:
        """Send a request and wait for the dump that answers it.

        ``wanted`` is the opcode of the **reply**, never of the request.
        Our own request arrives first on a chain with a thru in it, and it
        is a perfectly well-formed Alesis message; only the opcode tells
        the two apart.

        ``number`` matters for the same reason it matters in the siblings:
        a reply to a request that already timed out arrives during the
        next one, and a read that does not check the number files it under
        whatever was asked for next.
        """
        self._drain()
        self._send(outgoing)
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        while time.time() < deadline:
            message = self._in.get_message()
            if message is None:
                time.sleep(0.002)
                continue
            packet = m.parse(message[0])
            if packet is None:
                continue
            if packet.function != wanted:
                continue
            if number is not None and packet.number != number:
                continue
            return packet
        raise TimeoutError(self._silence_means(wanted, number))

    def _silence_means(self, wanted: int, number: Optional[int]) -> str:
        """Why nothing came back. Never picks one reason.

        The instrument answers a request it cannot serve with silence, and
        so does an unplugged cable. Naming one cause would be a guess
        dressed as a diagnosis.
        """
        what = m.Function.name(wanted)
        if number is not None:
            what += f" {number}"
        return (
            f"no {what} came back. The unit did not refuse it either, so "
            f"this means one of: powered off, the wrong port, System "
            f"Exclusive reception disabled, a MIDI chain that does not "
            f"carry the reply back to this computer -- which is easy to "
            f"get wrong when the unit hangs off another device's thru -- "
            f"or a request this unit does not serve."
        )

    # --- reading, all of it silent -----------------------------------------

    def identify(self, *, timeout: Optional[float] = None) -> Optional[dict]:
        """Ask who is there. Two small messages, and **makes no sound**.

        **This unit does not answer an Identity Request when it gets one.**
        It builds the reply and holds it, and transmits it only when it
        next answers some other System Exclusive message -- at which point
        every reply it has been holding comes out at once. Measured: send
        three Identity Requests and nothing comes back however long you
        wait; send one Global Dump Request afterwards and three Identity
        Replies arrive ahead of the dump.

        That is consistent with what its manual's implementation chart
        says about what it transmits, which is essentially nothing: the
        MIDI output seems only to run when there is a dump to send. So
        this sends the Identity Request and then a Global Dump Request to
        prompt the flush. The Global Dump is read-only and silent, and
        this is the only way to get an answer.
        """
        self._drain()
        self._send(m.identity_request())
        time.sleep(SEND_GAP)
        self._send(m.global_dump_request())
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        answered_dump = False
        while time.time() < deadline:
            message = self._in.get_message()
            if message is None:
                time.sleep(0.002)
                continue
            fields = m.identity_reply_fields(message[0])
            if fields is not None and fields.get("is_alesis"):
                return fields
            packet = m.parse(message[0])
            if (packet is not None
                    and packet.function == m.Function.GLOBAL_DUMP):
                # The dump answered but no Identity Reply was waiting --
                # it is a QS-family unit and that is as much as can be
                # said without one.
                answered_dump = True
        if answered_dump:
            return {"channel": self.channel, "is_alesis": True,
                    "is_qs_family": True, "is_nanosynth": True,
                    "family": (m.QS_FAMILY, 0), "member": None,
                    "version": "", "manufacturer": m.ALESIS_ID,
                    "inferred": True}
        return None

    def read_program(self, number: int, *,
                     timeout: Optional[float] = None) -> bytes:
        """One user program's 350 bytes. **Makes no sound.**

        Only the user bank. The other four banks are ROM and the protocol
        has no request for them.
        """
        packet = self.request(
            m.program_dump_request(number),
            m.Function.USER_PROGRAM_DUMP, number=number, timeout=timeout)
        data = packet.data()
        rec.check_size(data, rec.PROGRAM_BYTES, "a program")
        return data[:rec.PROGRAM_BYTES]

    def read_program_names(
            self, *, timeout: Optional[float] = None,
            on_progress: Optional[Callable[[int, int], None]] = None
    ) -> Dict[int, str]:
        """Every user program name, one request at a time. **Silent.**

        128 round trips. There is no bulk request that returns only the
        user bank -- the All Dump returns everything, 79 kB of it, and
        most of that is data this program does not use. One at a time is
        slower and asks the instrument for exactly what is wanted.
        """
        out: Dict[int, str] = {}
        for number in range(banks.PROGRAMS_PER_BANK):
            try:
                record = self.read_program(number, timeout=timeout)
            except TimeoutError:
                continue
            out[number] = rec.program_name(record)
            if on_progress is not None:
                on_progress(number + 1, banks.PROGRAMS_PER_BANK)
            time.sleep(SEND_GAP)        # a guess; see SEND_GAP
        return out

    def read_edit_program(self, *,
                          timeout: Optional[float] = None) -> bytes:
        """The edit buffer: whatever the unit is playing. **Silent.**"""
        packet = self.request(m.edit_program_dump_request(),
                              m.Function.EDIT_PROGRAM_DUMP, timeout=timeout)
        data = packet.data()
        rec.check_size(data, rec.PROGRAM_BYTES, "a program")
        return data[:rec.PROGRAM_BYTES]

    def read_mix(self, number: int, *,
                 timeout: Optional[float] = None) -> bytes:
        """One of the 100 mixes. **Silent.**

        The manual does not mention mixes. The unit answers for them.
        """
        packet = self.request(
            m.mix_dump_request(number), m.Function.MIX_DUMP,
            number=number, timeout=timeout)
        data = packet.data()
        rec.check_size(data, rec.MIX_BYTES, "a mix")
        return data[:rec.MIX_BYTES]

    def read_mix_names(
            self, *, timeout: Optional[float] = None,
            on_progress: Optional[Callable[[int, int], None]] = None
    ) -> Dict[int, str]:
        out: Dict[int, str] = {}
        for number in range(banks.MIXES):
            try:
                record = self.read_mix(number, timeout=timeout)
            except TimeoutError:
                continue
            out[number] = rec.mix_name(record)
            if on_progress is not None:
                on_progress(number + 1, banks.MIXES)
            time.sleep(SEND_GAP)
        return out

    def read_global(self, *, timeout: Optional[float] = None) -> bytes:
        packet = self.request(m.global_dump_request(),
                              m.Function.GLOBAL_DUMP, number=0,
                              timeout=timeout)
        return packet.data()

    # --- the one thing that makes a sound ----------------------------------

    def select(self, target: banks.Slot) -> None:
        """Select a program. **This changes what the unit is playing.**

        Bank Select then Program Change, always both. The manual's own
        advice, and for its stated reason: send a Program Change alone and
        you get that number in whatever bank the unit was last put into,
        which may have been the front panel's doing while you were not
        looking.
        """
        for message in m.bank_select(target.bank.select, self.channel):
            self._send(message)
        time.sleep(SELECT_GAP)          # a guess; see SELECT_GAP
        self._send(m.program_change(target.program_change, self.channel))

    # --- discovery ----------------------------------------------------------

    @classmethod
    def autodetect(cls, *, timeout: float = PROBE_TIMEOUT,
                   on_try: Optional[Callable[[str], None]] = None
                   ) -> "NanoBridge":
        """Find the NanoSynth by asking every port who is there.

        Name hints only order the sweep. This instrument has no USB port of
        its own and answers through whatever it is cabled behind, so its
        port is named after something else entirely.
        """
        hinted = likely_ports()
        _, outs = list_ports()
        candidates = hinted + [p for p in outs if p not in hinted]
        for port in candidates:
            if "Midi Through" in port:
                continue
            if on_try is not None:
                on_try(port)
            try:
                bridge = cls.open(port, timeout=timeout)
            except Exception:
                continue
            try:
                # The probe is a Global Dump Request, not an Identity
                # Request: this unit never answers the latter on its own
                # (see identify). The Global Dump is Alesis-and-QS
                # specific, so no other manufacturer's box on the chain
                # can answer it by accident -- which an Identity Request
                # very much can, and on the bench always did.
                bridge.request(m.global_dump_request(),
                               m.Function.GLOBAL_DUMP, number=0,
                               timeout=timeout)
                found = True
            except Exception:
                found = False
            if found:
                # The discovery timeout must not become the session's:
                # every later request that does not name its own would run
                # at the probe's value rather than the working one.
                bridge.timeout = DEFAULT_TIMEOUT
                return bridge
            bridge.close()
        raise DeviceError(
            "no NanoSynth answered an Identity Request on any port. Check "
            "the cable, that the unit is on, and -- if it is behind "
            "another device -- that the chain carries its replies back to "
            "this computer as well as carrying requests out."
        )
