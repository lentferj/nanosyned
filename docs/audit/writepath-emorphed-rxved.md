# Write path + family-integration architecture: emorphed & rxved

Quote-backed survey for the port into `nanosyned`. Everything below is verbatim
from the two checkouts (file:line). Nothing was modified.

Both projects sit on a shared family library, installed as
`vinsynlib` (see `rxved/.venv/lib/python3.11/site-packages/vinsynlib/`),
which owns the pieces every sibling shares:

- `vinsynlib/ui/work.py:24-30` — `QUIET_BRIDGE_ERRORS: frozenset(...) = {ConnectionError, TimeoutError, OSError}` — "Family-wide quiet error set. Programming errors (TypeError, ValueError, etc.) are never silenced by this set".
- `vinsynlib/ui/work.py:33-103` — `class BusyGate`: "Gate that refuses on the main thread before any worker starts." `refuse(reason)` (main thread only, line 60), `check()` (line 69), `is_busy()` (line 74), `__enter__` raises `RuntimeError(reason)` if a refusal is pending and otherwise bumps `_active` (85-92), `__exit__` clears refusal and decrements (94-103).
- `vinsynlib/ui/work.py:106-137` — `close_when_idle(bridge, *, gate, grace=0.25)`: "This never closes mid-exchange. It waits for the gate to be neither refused (`check()`) nor in progress (`is_busy()`) for `grace` seconds, then calls the bridge's `close()`."
- `vinsynlib/backup.py` — device-agnostic envelope: `FORMAT = 1` (:16), base64 blocks (:34), `save(...)`: :51, version check in `load`: :100-101 (`raise ValueError(f"wrong version: expected {FORMAT}")`).
- `vinsynlib/cli.py:107-…` — `add_common_arguments(..., yes: bool = False, allow_write: bool = False)`; flags are emitted in `spec.CANONICAL_FLAGS` order so "`--help` reads the same in every tool" (:126-…).
- `vinsynlib/config.py:561-690` — `load_ui_state(key, path=None, *, default=UNSET)`, `load_ui_int` (:605), `load_ui_bool` (:625), `save_ui_state(key, value, path=None)` (:676).

---

## 1. emorphed `emu/backup.py` and its use

**Positioning.** `emu/backup.py:11-20` opens:

> ``restore`` is not offered because there is no restore command; the one
> write path (midimap parameters + store) keeps its own backup and
> read-back (see ``CLAUDE.md``, "Writing is fenced"). What this module does
> is the honest half of a backup that a read-only browser can do: capture a
> preset's own bytes from the unit, write them into the family's JSON
> envelope, and read them back.

and :38-41: "**Nothing here talks to MIDI.** It serialises a preset it is handed and reads one back; the bridge and the CLI do the round trips. That keeps a backup testable with no hardware, and keeps the rule that workers do MIDI and nothing else does."

The library owns the on-disk shape (:22-27): "a JSON object whose blocks are base64, a format byte a future emorphed reads and checks, a filename that never overwrites, and a `list_backups` that reports a file it cannot read rather than dropping it." emorphed adds only (i) the app name (`APP_NAME = favorites.APP_NAME`, :77 — the data dir is "emorphed's per-platform data directory and **not** the checkout a `git clean` empties") and (ii) the block: "one preset's own data bytes... The bytes come from the unit, never from a re-description of the preset" (:33-36).

**Constants** (:82-90):
```python
KIND = "preset"
BLOCK = "preset"
KIND_MIDIMAP = "midimap"
BLOCK_MIDIMAP = "midimap"
```

**Record.** `Backup(_backup.Backup)` (`:93-107`) subclasses the library header, adding `id: str = ""` — "its fields are the JSON header, and a directory of those cannot name one to `load`. ``id`` is that name (the file's basename), and it is the handle the CLI's ``backup list`` prints."

**Bytes class.** `PresetBytes(bytes)` (:110-125) — "A preset's stored bytes, that also compare as its words. `.words` is the form `emu.messages.decode_name` and every other consumer of a preset wants" (`words` property = `m.from_words(self)`, :124-125). `MidimapBytes(PresetBytes)` (:128-129).

**Where.** `default_dir()` (:149-158): `os.path.join(favorites.data_dir(), "backups")` — "The name is ``backups``, beside ``favorites.db``".

**Save.** `save_preset(words, *, device_id, slot=None, name=None, source="emorphed", ...)` (:189-247):
- name is read *from the words* (`m.decode_name(words[:NAME_CHARS]).rstrip()`, :219-220) unless given;
- slot falls back `index` → `number` (+region offset) → `0` (:227-236);
- `_to_bytes` (:132-146) accepts bytes / str / word lists (already-byte-shaped lists of 0x7F values of the exact `PRESET_DATA_BYTES` length pass through, else `m.to_words(values)`);
- delegates: `path = _backup.save(directory or default_dir(), kind=KIND, slot=str(slot), name=name, device_id=str(device_id), source=source, blocks={BLOCK: data})` (:238-246) and returns `_record(_backup.load(path), os.path.basename(path))` (:247).

`save_midimap(...)` (:250-291) is the same with `kind=KIND_MIDIMAP`, `blocks={BLOCK_MIDIMAP: data}`, default `source="emorphed (midimap edit)"` (:256).

**List.** `list_backups()` (:294-332): "Every backup in a directory, newest first. A file that cannot be read is listed with its ``error`` rather than dropped -- a restore point you cannot read is exactly the thing to be told about." Corrupt files become a record with `error=str(exc), saved=0.0` (:318-330); `out.sort(key=lambda backup: backup.saved, reverse=True)` (:331).

**Load.** `_load_for(...)` (:335-353) refuses the wrong kind (`raise ValueError(f"{ident} holds {record.kind!r}, not a {kind} backup")`, :340) and the missing block; `load()` (:356-381) accepts a bare id against a directory or a full path (`_resolve`, :176-186: "a backup copied to a USB stick can be loaded by naming it directly"), and without a `kind` accepts either family kind, mapping block names between the two (:345-349). `load_midimap()` (:384-389).

**How the app uses it — the midimap-edit backup.** `EmorphedApp._backup_before_write()` (`emorphed/app.py:1033-1057`):
```python
def _backup_before_write(self) -> None:
    if self._midimap_backed_up:
        return
    ...
    words = self.device.read_midimap(index)
    record = bkmod.save_midimap(
        words,
        device_id=self.device.device_id,
        slot=index,
        directory=self._backup_dir(),
        source="emorphed (midimap edit)",
    )
```
Gesture-level: one backup per session, on the *first* write of any kind (parameter/name/channel-preset workers all call `self._backup_before_write()` inside `with self._busy_gate:` — :713, :844, :935). A failed backup "is announced and the parameter write still proceeds -- only the STORE refuses without a successful backup this session" (`CLAUDE.md:108-112`). The store refuses: `_store_midimap()` :1100-1110:
```python
if not self._midimap_backed_up:
    sentence = "store refused: no midimap backup this session"
    self.notify_status(sentence, refused=True)
```
On success the status line names the file: `self.call_from_thread(self.notify_status, f"backed up the midimap as {record.id}")` (:1055-1057).

The CLI's `backup save` uses `save_preset` for a whole RAM region (`emorphed/cli.py:395-433`, below). `Backup` records surface in `backup list` (table or `--json`, `cli.py:342-384`).

---

## 2. `emorphed/app.py` write wiring

### The three-signal busy test

State built in `__init__` (:341-352):
```python
self._busy_gate = BusyGate()
# One exchange at a time, claimed on the main thread. ...
self._exchange = threading.Lock()
```
> "The gate alone cannot carry this: entering the gate *clears* a refusal, so between reserving one and entering it for real a second action would find neither ``check()`` nor ``is_busy()`` set and start a second worker. ``_busy`` reads this claim as a third signal." (:345-352)

`_busy` (:441-447):
```python
return (
    self._busy_gate.check() is not None
    or self._busy_gate.is_busy()
    or self._exchange.locked()
)
```
`_undo_gate` reports it for z: `return "busy" if self._busy else None` (:438-439).

### The write gate (`EditGate`) and `w`

`_gate` is a lazy `edmod.EditGate(armed=self._allow_write)` (:426-430); `_editor` is the shared `MidimapEditor(gate=self._gate)` (:432-436). Toggled by `w`:
- `app.py:278` — `Binding("w", "toggle_write_gate", "Write gate")`;
- `action_toggle_write_gate` (:449-451): `self._gate.toggle(); self.notify_status(self._gate.describe())`.

`--allow-write` ("allow_write: bool = False" ctor arg :298; stored :324; CLI header added via `add_common_arguments(..., allow_write=True)` :2509; passed `allow_write=args.allow_write` :2621) arms only the *start* state (`CLAUDE.md:106-108`: "`w` arms it; `--allow-write` arms only the *start* state, not every write").

The editor's own screen re-uses the same gate object: `MidimapEditScreen.action_toggle_write_gate` (`midimapui.py:689-694`) toggles `self.gate` ("`return getattr(self._editor, "gate", self._editor)`, :159-160).

`EditGate.refuse()` (`edit.py:71-75`): "The refusal, or ``None`` when the gate is armed" → `"the write gate is locked; press w to arm it"`. The refusal surfaces red: `notify_status(message, *, refused=False)` (:1926-1935) — "the widget carries a ``refused`` class rather than a text prefix, so a locked write gate is a red bar the eye cannot miss" (`#status.refused { background: $error; ... }` :250-254).

### The claim pattern (every exchange)

Every main-thread action repeats, e.g. `action_midimap_edit` (:453-461):
```python
if self._busy:
    self.notify_status("busy", refused=True)
    return
if not self._exchange.acquire(blocking=False):
    ...
    return
self._read_midimap_worker()  # @work(thread=True)
```
Inside each worker: `with self._busy_gate:` around **MIDI only**, `except _BRIDGE_ERRORS` → status line, `finally: self._exchange.release()`, then `self.call_from_thread(...)` for any UI update (:463-486 shows the template verbatim).

`_BRIDGE_ERRORS` (:119-126):
```python
_BRIDGE_ERRORS: tuple[type[BaseException], ...] = (
    *QUIET_BRIDGE_ERRORS,  # ConnectionError, TimeoutError, OSError
    ValueError,
    LookupError,
    RuntimeError,
    SystemError,
)
```

### Closing without wedging

`main()` (:2623-2628):
```python
finally:
    store.close()
    with close_when_idle(device, gate=app._busy_gate):
        pass
```

### `_say_sweep` (`swept` / `probe_seconds`)

`app.py:2456-2468`:
```python
def _say_sweep(bridge: Any) -> None:
    """One line when the unit was found by a sweep, and silence otherwise.
    ...
    if not getattr(bridge, "swept", False):
        return
    print(f"swept for {bridge.probe_seconds:.1f} s; found "
          f"{bridge.port} (device {bridge.device_id})", file=sys.stderr)
```
Called in `main` after `MorpheusBridge.connect(...)` (:2570-2578). The bridge exposes `swept: bool` and `probe_seconds: float`; the CLI duplicates the same print at `cli.py:614-618`.

### ui-state save/restore

`_save_ui_state(*, bank_index=UNSET, slot_cursor=UNSET, view_mode=UNSET, kind_view=UNSET)` (:1575-1611) — "`:data:`UNSET` forwards nothing, so saving the view leaves the bank position alone: the four keys are saved individually... Only :class:`OSError` is swallowed -- ... A programming error (a list where an int belongs) raises and is heard." Loop body: `for key, value in (...): if value is UNSET: continue; _cfg.save_ui_state(key, value, self._config_path)`.

Restore happens in `__init__` (:373-409) "not in `on_mount`, because the first `_fill` down there builds its rows out of ``view_mode`` and ``_current_bank``; restoring anything later would mean filling twice": `_cfg.load_ui_state("view_mode", self._config_path)` (:385; values validated against `VIEW_CYCLE` / `banks.Kind.ALL`, :386-397), `_cfg.load_ui_int("bank_index", self._config_path)` (:398), `_cfg.load_ui_int("slot_cursor", ...)` (:403). Everything is "Injected path only -- ``None`` means a test that asked for silence and gets it" (:379-380). The rating filter uses `load_ui_int/load_ui_bool` (:356-371) and re-saves with `_save_rating_filter()` (:1553-1573, saves `None` to clear). The bank-row handler saves idempotently: `self._save_ui_state(bank_index=row)` (:1956), slot cursor saved only "when the slot table is focused" (:1959-1964), `on_mount` clamps the saved cursor and clears it (:1451-1458).

### Key handling: `z` / `Z`, `w`, `v`

- `app.py:276-278`: `Binding("z", "undo", "Undo")`, `Binding("Z", "undo_all", "Undo all")`, `Binding("w", "toggle_write_gate", "Write gate")`.
- `z` → `action_undo` → `_undo_master_edits(1)` (:1263-1264); `Z` passes `None` (:1266-1267). `_undo_master_edits` (:1269-…) refuses whole batches that contain device writes while the gate is locked (:1269-1284: "P2: refuse before consuming when the write gate is locked and the batch contains a ParamChange or NameChange"), replays `ParamChange`/`NameChange`/`ChannelPresetChange` through the write path with `record=False` (:1313-1334), pushes unapplied records back "oldest-first" (:1335-1337), and reports counts (:1340-1371).
- `v` cycles the favourites view: `Binding("v", "cycle_favorites", "Favourites view")` (:271) — "`v`, not the family's `F`: `f` writes the favourites database and `F` does not, so the family's shift-pair left a write one slip away from a read. `v` has no such twin. rxved and p2ked made the same swap; the rename is declared in tests/test_conformance.py." (:267-270). `action_cycle_favorites` (:1818-1846) — "Always exactly three steps, even when a view is empty" — persists with `self._save_ui_state(view_mode=self.view_mode)` (:1830).

---

## 3. emorphed edit → screen → device round trip

### `emorphed/edit.py` — pure rules

Module docstring (:6-23): "PURE rules only -- no Textual, no I/O... Two write routes, one gate. A parameter write (``write_parameter``, 0x03) edits the **scratch** midimap... The **store** (``send_midimap``, 0x47) writes a whole midimap to a location and erases what was there (manual p.36); only that makes an edit stick."

- `EditGate` (:58-75) — `armed`, `toggle()`, `describe()` → `"write gate armed"/"write gate locked"`, `refuse()` → `None` or `"the write gate is locked; press w to arm it"`.
- `EditLog` (:78-128) — ordered edits + `take(n)` "The last ``n`` edits, newest first, and drop them" (:116-125).
- `MidimapEditor.allow(offset, value)` (:142-161): gate check first, then `mm.param_at(offset)` — every failure returns a sentence, never invents a parameter: `f"no midimap parameter at offset {offset}"`; range: `f"{param.label} must be {param.low}-{param.high}, and {value} is not"`; choices: `f"{param.label} must be one of {', '.join(param.choices)}, and {value} is not"`.
- `MidimapEditor.finish(offset, value, read_back, *, old=None)` (:163-197) — **verification is here**: `if read_back != value: return False, (f"{label} did not take {value}: the unit still reports {read_back!r}")`; only agreement is logged (`self.log.push(Edit(...))`, :188-196) and reported as `f"{label}: {old} -> {value}"` (:197).
- `undo_plan` / `undo_report` (:199-209).

Parameter IDs are never invented: "`emu/midimap.py:13` — "A ``Midimap`` (command ``0x47``) carries 360 fourteen-bit words: a twelve-character name followed by twenty settings for each of sixteen channels""; `PARAM_BASE = 2048` (:611), `param_at(offset)` → `_BY_OFFSET` dict, errors with `raise ValueError(f"no midimap parameter at offset {offset}")` (:616-621); `spell(param, value)` (:649). The app wire-up: `_editor` is called for every allow/finish; nothing else knows the table.

### The screen: `emorphed/midimapui.py`

Docstring (:6-22): "A screen owns no worker and sends nothing on its own -- every change goes out through a callback: ``on_edit`` for a single word, ``on_name`` for the twelve-character name, ``on_channel`` for a channel's preset pair, and ``on_pick`` to ask for a preset picker." `set_unstored` is "the screen's own scratch/stored marker: the app calls it after a write (``True``) and after a store (``False``), and the screen only displays the tag -- it sends nothing" (:19-22); the title shows the tag (`"`[b]Midimap edit[/b] -- scratch, unstored"` :572-575) and the status line names `s` (:502-507: `" · unstored -- s store to a location (survives a power cycle)"`).

**Staging (`_pre_edit`) and read-back (`result`).** Every edit path (`_nudge`, the prompt's `apply`, the choice picker's `picked`, digit-typing commit) does:
```python
self._pre_edit.setdefault(off, self._values.get(off, value))
self._values[off] = value
self._on_edit(off, value)
```
(e.g. :781-784, :859-862, :892-895, :1115-1117) — the optimistic value is painted immediately. `result(ok, message, parameter_id=..., value=..., ...)` (:577-678) resolves it: on success it hashes the assignment in (`self._values[off] = value`, :590) and clears `_pre_edit` (:672-673); on refusal "the optimistic value is rolled back": `elif off is not None and off in self._pre_edit: self._values[off] = self._pre_edit.pop(off); self._refresh_table()` (:674-677). Single-cell row updates keep the cursor in place (:602-660); `update_params(params)` (:1161-1177) re-binds whole tables "The cursor follows the row it was on, in its column".

**`+/-` nudge.** Bindings :92-94: `Binding("plus", "nudge_up", ...)`, `Binding("equals", "nudge_up", ...)`, `Binding("minus", "nudge_down", ...)`. `_nudge(by)` (:702-789):
- pickable ranges clamp (`value = min(high, max(low, current + by))`, :763-765); choice parameters step the list in screen order (:748-761);
- gate and allow are checked **locally first** — a refusal is said and *nothing is sent* (:768-780);
- then the optimistic paint + `on_edit` (:781-784). There is no merging of rapid nudges into one message; instead the destination (app `_apply_parameter`) serialises them — a second `+` arriving while a write is in flight is refused `"busy"` in the app, and because the screen painted optimistically, the refusal callback `result(False, "busy", parameter_id=off, value=...)` rolls that pending nudge back to `_pre_edit` (`app.py:811-828` + `midimapui.py:674-677`). Channel rows nudge the *pair* bank+program with `mm.step_channel_preset(bank, number, by)` ("rolling across bank boundaries", `CLAUDE.md:135-136`) through `on_channel` (:714-733).

**Digit typing** (`on_key`, :1054-1149): digits accumulate into `self._typing` for the current cell, Enter commits → allow-check → `on_edit`, escape/backspace edit the buffer. Typing resets on cursor moves (:1151-1159).

**Refusal surfacing:** `say(message, *, refused=False)` (:545-551) writes the screen's `.status` line with the same `refused` red class the app uses.

### The app side of a parameter edit

`_apply_parameter(offset, value, *, record=True)` (`app.py:791-830`), main thread:
1. `refusal = self._editor.allow(offset, value)`; if refused: `notify_status(refusal, refused=True)`, `top.say(refusal, refused=True)`, **and** `top.result(False, refusal, parameter_id=offset, value=value)` so the optimistic paint is rolled back (:794-810).
2. busy/exchange checks with the same refusal shape (:811-828).
3. spawn `_apply_parameter_worker` (:832-859): "**MIDI only**: write, then read back":
```python
with self._busy_gate:
    param_id = mm.PARAM_BASE + offset
    old = self.device.read_parameter(param_id)
    self._backup_before_write()
    self.device.write_parameter(param_id, value)
    read_back = self.device.read_parameter(param_id)
```
4. `_parameter_edited` (:1063-1098) on the main thread: bridge error → `f"offset {offset}: {failure}"`; silence → `f"offset {offset}: the unit stayed silent (no read-back)"`; otherwise `ok, sentence = self._editor.finish(offset, value, rb, old=old_val)`, and `if ok and record: self._push_change(ParamChange(offset, old_val, value))`; on ok also `self._current_midimap_words[offset] = value` and `self._mark_midimap_unstored(True)` — scratch vs stored never conflates (:1095-1098).

Name writes are twelve parameter writes with twelve read-backs in one worker (`_write_midimap_name_worker`, :702-760; "gate every character first... Refuse the whole write on the first refusal; nothing is sent in that case" :654-677; "twelve writes, twelve reads, report agreement"; result `f"name written: {shown_name!r}; read-back agreed (12/12)"` / `"read-back disagreed (…)"` :778-785). Channel presets gate both offsets before anything is sent (:861-910), write bank then program each with read-back (:912-955).

### Store (arm then confirm then fire)

`_store_midimap` (:1100-1155): refuses without this session's backup (:1101-1110), then `PromptScreen("Store to midimap location (0-31):", str(index))`; validates `0 <= loc <= 31` (:1133-1142), then `ConfirmScreen(f"STORE to location {loc}: erases what is there")` (:1143-1150). `_store_confirmed` (:1157-1185) re-checks busy/claim, then `_store_midimap_worker` (:1187-1213): `self.device.send_midimap(loc, final_words)` then **verify by reading the destination back**: `stored = list(self.device.read_midimap(loc))`. `_finish_store` (:1215-1261) counts agreeing words: `f"stored to M{loc:02d} -- survives a power cycle (read back {agreed}/{total} words)"` on full agreement (and clears unstored), else `f"store to M{loc:02d}: read-back disagreed ({agreed}/{total} words agree); did not take it"`. A close over unstored edits gets a `ConfirmScreen` guard wrapping `action_close` (:596-634: "Closing now discards the scratch edits made this session; they are not stored and will be lost on a power cycle").

---

## 4. `emu/device.py` — the `Device` Protocol (verbatim, 81 lines)

`emu/device.py:20-26`: "The interface both devices answer to. ``DemoDevice`` and ``MorpheusBridge`` both satisfy this structurally. The commands and the browser are written against it, so a command that needs a real unit can be told so by the caller passing one, and the offline commands are passed ``None`` and never touch it."

`emu/device.py:37-81` — the whole Protocol:

```python
class Device(Protocol):
    """What emorphed asks of a device, real or invented."""

    description: str
    device_id: int
    # None until a midimap is explicitly made current this session; a
    # stored-map read (0x46/0x47) does not count.
    current_midimap: int | None
    channel: int
    port: str | None
    recv_port: str | None

    def close(self) -> None: ...

    def version(self) -> list[int]: ...

    def configuration(self) -> list[int]: ...

    def names(self, kind: str) -> list[str]: ...

    def select(self, target: banks.Slot) -> None: ...

    def select_midimap(self, number: int) -> None: ...

    def read_midimap(
        self, index: int, *, timeout: float | None = None
    ) -> list[int]: ...

    def write_parameter(
        self, param: int, value: int, *, timeout: float | None = None
    ) -> None: ...

    def send_midimap(
        self, index: int, words: Any, *, timeout: float | None = None
    ) -> None: ...

    def read_parameter(self, param: int) -> int | None:
        # Live scratch-map value via Parameter Request (0x02); NOT the
        # stored midimap dump. See emu.bridge.MorpheusBridge.read_parameter.
        ...

    def read_scratch_params(self) -> list[int | None]:
        # Every midimap parameter (2048-2407) via Parameter Request.
        # See emu.bridge.MorpheusBridge.read_scratch_params.
        ...
```

The write-path contracts live on the bridge with the semantics a port must reproduce:

- `bridge.read_midimap` — "One midimap, as 360 fourteen-bit words. Silent. STORED map (command 0x46/0x47), not the live scratch map." A short body "raises with that wording rather than returning a short list" (:324-358).
- `bridge.write_parameter` — "Send one Parameter Data frame. Fire-and-forget, no reply." Range-checked to midimap params 2048-2407 and fourteen-bit values (:360-385).
- `bridge.send_midimap` — "**This is the STORE.**... 'A backup must have been taken first; that is the caller's job, and nothing here does it.'" (:387-401).
- `bridge.read_parameter` — "Live value via a Parameter Request (0x02)... Returns ``None`` when the unit stays silent... It does **not** raise for a legitimately absent card midimap; silence means 'no'" (:403-421). It discriminates a late reply by the echoed parameter number (:441-449).
- `bridge.read_scratch_params` — "That is **360 round trips on the wire**... Returns one entry per parameter... ``None`` where the unit stayed silent" (:451-503).
- `bridge.select_midimap` — selection via two SysEx frames; "no read-back after it and no reply to wait for" (:518-539); sets `current_midimap` (:536).

---

## 5. rxved: `xv/bridge.py` write methods, `xv/backup.py`, and the store screen

### `xv/backup.py` (209 lines, standalone — no vinsynlib dependency)

Docstring (:16-31): "Performance backups: the undo for the only destructive thing rxved does... The format is JSON with the blocks hex-encoded... **Nothing here talks to MIDI.**" Key pieces:

- `FORMAT = 1` (:57) — "Bumped only if the on-disk shape changes incompatibly. Read back and checked".
- `decode()` (:105-127) refuses: wrong kind (`f"backup holds {payload.get('kind')!r}, not a performance"` :110), wrong version (`f"backup is format {version!r}, and this rxved reads only {FORMAT}. Refusing to guess..."` :113-117), no blocks, bad hex.
- `_stamp(name, slot)` (:133-137): `f"{where}-{when}-{tidy}.json"` with `where = f"slot{slot:02d}" if slot else "temp"`.
- `save()` (:140-161): "**Never overwrites**: the filename carries a timestamp, and a collision within one second gets a suffix" (`while os.path.exists(path): ... path = f"{root}-{counter}{ext}"`).
- `list_backups()` (:193-209): "Unreadable files are listed with an ``error`` rather than dropped", newest first by the ISO `saved` string.
- Per-block contents are the *previous* contents of the destination (see below); `performance_name(blocks)` reads the name out of Common offsets (:71-82).

(Compare with all three above: emorphed instead binds `vinsynlib.backup` as the envelope; rxved vendored the same ideas into `xv/backup.py` at family-forming time.)

### `xv/bridge.py` write methods (class `XvBridge`)

- `read_performance_blocks(base, *, on_progress=None, timeout=None) -> Dict[str, bytes]` (:1638-1668): "Every block of one performance. 36 round trips, no sound." A short block "is an error rather than something to pad: a partial read that later gets written back would write the wrong thing to the wrong offsets" (`raise DeviceError(f"block {name} at ... returned {len(data)} bytes, expected {size}")` :1660-1664).
- `write_performance_blocks(base, blocks, *, on_progress=None, verify=True, timeout=None) -> List[str]` (:1670-1718): "Write a whole performance. Returns the names of blocks that did **not** read back identical. **This is the one operation in rxved that can destroy something.** ... Callers are expected to have taken a backup; :meth:`store_temporary_to_slot` does." Refuses partial input upfront: `raise ValueError(f"refusing to write a partial performance; missing {', '.join(missing)}")` (:1695-1697), and wrong sizes (:1705-1708). Per block: `self._send(m.dt1(...)); time.sleep(SEND_GAP)` then `if verify: back = self.request(address, size, ...); if bytes(back) != payload: mismatched.append(name)` (:1710-1717) — "Verification is per block and by comparison, not by trusting the send: DT1 is unacknowledged".
- `store_temporary_to_slot(slot, *, ...) -> Tuple[Dict[str, bytes], List[str]]` (:1720-1743) — **the shape to port**:
```python
base = user_performance_base(slot)
backup = self.read_performance_blocks(base, timeout=timeout)      # destination, FIRST
blocks = self.read_performance_blocks(TEMPORARY_PERFORMANCE, ...) # the edit buffer
mismatched = self.write_performance_blocks(base, blocks, on_progress=..., ...)
return backup, mismatched
```
  "Returns ``(backup, mismatched)`` -- the destination's **previous** contents, read before anything is written so the slot can be put back... The backup is taken first and unconditionally. If reading the destination fails, nothing is written: a store that cannot be undone is not one this program performs." (:1727-1736)
- `write_part_param(part, offset, value, *, verify=True, timeout=None) -> int` (:1783-1835): "This is the only write in rxved [to params], and what makes it acceptable is where it goes: ``10 00 <20+part-1> <offset>`` is Temporary Performance -- the edit buffer the module is playing from right now, not a stored performance... rxved does not perform the Write (store) operation and has no code that could [outside this]. Returns the value **read back from the device**, not the value sent. A DT1 is fire-and-forget... Reporting the sent value as fact would be a guess dressed as a confirmation". Address allowlists (`WRITABLE_PART_OFFSETS` with `(label, low, high)`, range check `raise ValueError(f"{label} takes {low}-{high}, got {value}")` :1817-1819); silence on read-back raises `DeviceError(f"wrote {label} on part {part} but read back nothing")` (:1834).
- `write_channel_param` (:1745-1781, same contract, channel 0-15, `WRITABLE_CHANNEL_OFFSETS`), `write_performance_common` (:1837-1869, `WRITABLE_COMMON_OFFSETS`), `write_performance_name` (:1871-1890, 12 bytes, "Returns the name read back, not the one sent"), `write_performance_effect` (:1892-1938, `"mfx"/"chorus"/"reverb"` blocks, int4x4 nibble widths for per-algorithm params). All share: allowlist → range check → `dt1` send → `SEND_GAP` → read-back → returned value is what the synth reports.
- `write_sound_mode` (:2022-…) is the one *global-state* write (Setup block; PATCH/PERFORM only, GM refused in the bridge — see `tests/test_hardware.py:255-261`).

### `rxved/app.py`

Wiring baseline (:128-134) — identical family tuple:
```python
_BRIDGE_ERRORS = (
    *QUIET_BRIDGE_ERRORS,
    ValueError,
    LookupError,
    RuntimeError,
    SystemError,
)
```
Instead of emorphed's gate+claim pair, rxved serialises with `_bridge_lock` + `_busy`:
- `app.py:335-351`: 
```python
#: Every bridge call is taken under this, and shutdown waits on it --
#: see :func:`_close_when_idle`. A worker mid-request that has its
#: port closed underneath it leaves the synth composing a reply for
#: nobody, which is how the sibling projects wedged their hardware.
self._bridge_lock = threading.RLock()
...
self._busy = False
self._closing = False
```
- Every worker body: `with self._bridge_lock: <midi> ... except _BRIDGE_ERRORS ... finally: self._busy = False`.
- The claim is set **on the main thread** before spawning, with the same reasoning emorphed gives (three repeats, e.g. `_write_part_param` :2493-2504):
```python
if self._busy:
    self.notify_status("busy", refused=True)
    return
# Set on the main thread, not in the worker. A @work(thread=True)
# method returns at once and would set the flag on its own thread,
# so two quick presses both passed the check above before either
# worker ran -- two of whatever the worker does, from one intent.
self._busy = True
```

**Store screen (arm-then-fire).** `open_store_screen(source_name)` (:2516-2529): "Show the arm-then-fire write screen. Main thread; sends nothing." Destination names shown are "whatever has already been read... an unread slot is labelled as unread rather than blank, so nothing is misrepresented as empty." The callback chain: `push_screen(StoreScreen(source_name, names, on_store=self._store_to_slot))`.

`_store_to_slot(slot)` (:2531-2541): busy-check + main-thread `_busy = True`, then `_store_worker(slot)`.

`_store_worker(slot)` (:2543-2590) — **backup-before-write, on the worker thread, named destination**:
```python
with self._bridge_lock:
    previous, mismatched = self.bridge.store_temporary_to_slot(slot, on_progress=progress)
path = bk.save(previous, self.backup_dir(), slot=slot,
               device_id=self.bridge.device_id,
               source=f"{self.bridge.description} (before store)")
...
if mismatched:
    ... f"slot {slot}: {len(mismatched)} block(s) did NOT read back "
        f"as written ({', '.join(mismatched[:3])}...). Previous "
        f"contents are in {path}", refused=True,
else:
    ... f"stored into user performance {slot}; what was there is in {path}",
```
"The backup is written from this thread deliberately: it is a plain file, not the favourites SQLite connection, and holding 1.3 KB of somebody's performance in a variable while hopping threads is a chance to lose it that buys nothing." (:2545-2550) Reads use a live progress callback ("writing block {done}/{total}").

`backup_dir()` (:2506-2514) — injected `self._backup_dir` ("Injectable for the same reason... a test that exercises the destructive store cannot write into the real data directory. They did, once, and left files in it." :328-332) else `bk.default_dir(data_dir())`.

Other write tributaries, same shape:
- `_write_channel_param` (:2592-2633) and `_write_part_param`/`_write_part_worker` (:2635-…): write then **re-read the whole block** ("The whole part, not the byte written: the XV-2020 is free to adjust the next byte"); on disagreement, `f"ch {channel + 1}: wrote {value}, synth reports {landed}"` refused.
- `_write_common_worker` (:2461-2484): "Re-reads the whole block rather than the byte written".
- Sound mode `M`: `_mode_picked` (:940-954) pushes `ConfirmScreen` only for the initialising modes (GM/GS); `_write_sound_mode` (:956-963) is busy-gated; `_set_mode_worker` (:965-992) — "A mode change makes every part parameter mean something different, so the cached state is wrong the moment the byte lands" → write + `read_state(with_parts=True)`, then `f"asked for {SOUND_MODES[mode]}, synth reports {...}"` refused / `f"sound mode set to {SOUND_MODES[landed]}"`.

**StoreScreen** (`rxved/screens.py:540-663`) — the arm-then-fire UI to port:
```python
1. Pick a destination. Its **current** name is read from the synth and
   shown, because "slot 12" means nothing and the name it is about to
   replace means everything.
2. **Arm.** Nothing has been sent yet.
3. **Fire**, a different key, only while armed.
```
(:549-553) Bindings (:573-581): `a` → `action_arm` (:641-646), `w` → `action_fire` (:648-660) — "Deliberately not Enter, and deliberately not next to 'a' on the keyboard". Fire without arm is refused: `"not armed — press a on the destination slot first"` (:649-652). Cursor movement disarms (:633-639: "an arm that survives a cursor move is an arm aimed somewhere the user is no longer looking"). The armed status names what will be overwritten: `f"[b]ARMED[/b] — pressing [b]w[/b] overwrites slot {self._armed:02d}, which holds {holds}. ... Its current contents are saved to a backup file first."` (:622-631). It is opened from the Multi screen's `W` binding (`screens.py:1631` `Binding("W", "store", "Write to a slot")`, comment :1626-1628: "Opens the arm-then-fire screen. Opening it writes nothing; the destructive step is two further keys inside it, on purpose."; the pairing convention is declared in `rxved/app.py:271-273`).

Keys in rxved: `v` favours-view cycle (:254), `z`/`Z` undo (:259-260), `a`/`w` only *inside* StoreScreen. There is no global write gate in rxved (CLAUDE.md not present in this repo, but the analogous rules are inside each screen and the CLI's `--yes`).

**ui-state save/restore** mirrors emorphed: `_save_ui_state(*, bank_index=UNSET, slot_cursor=UNSET, view_mode=UNSET, categories=UNSET, rating_stars=UNSET, rating_at_least=UNSET, scan_offer_dismissed=UNSET)` (:2108-2140 — ":data:`UNSET` forwards nothing... ``None`` on a rating key is not that: it removes the key"; only `OSError` swallowed), loaded in `__init__` (:384-408: bank_index range-checked, slot_cursor, view_mode ∈ VIEW_CYCLE, categories, rating filter, scan_offer_dismissed).

**close_when_idle (rxved's older form).** `app.py:2999-3030`:
```python
SHUTDOWN_GRACE = 8.0


def _close_when_idle(app, bridge, grace: float = SHUTDOWN_GRACE) -> None:
    """Close the bridge, but not while a worker is mid-exchange. ..."""
    lock = getattr(app, "_bridge_lock", None)
    app._closing = True
    acquired = False
    if lock is not None:
        acquired = lock.acquire(timeout=grace)
    try:
        bridge.close()
    finally:
        if acquired:
            lock.release()
```
"closing the port tidily is not enough... leaving the instrument composing a reply for a listener that has gone. In the sibling project that state wedged an S3000XL until it was power cycled." — `_closing` "only makes it quick" (:347-351). emorphed replaced this with the `BusyGate`-based `vinsynlib.ui.work.close_when_idle` (a bounded 0.25 s quiescence wait rather than acquiring the lock).

---

## 6. The CLI write surface

### emorphed (`emorphed/cli.py`, program name `morphcli`, "read-only except `select`")

Shared header built with `vinsynlib.cli.add_common_arguments(..., yes=True, favorites=True)` (:466-478); app-side parser instead requests `allow_write=True` and gets `yes` via the screen (`app.py:2499-2510`). Offline commands (`OFFLINE = {"regions", "list", "read", "fav", "tags", "ports"}` :457, plus `backup list` :447-454) are passed `device=None` and "never touch" MIDI (`device.py:24-25`).

- `select` (:111-136): "Select a preset. **This makes the unit play.**" — refuses without confirmation unless `--yes`: `if not args.yes: ... if input("proceed? [y/N] ")... != ("y", "yes"): print("nothing sent"); return 1`; after sending it explains "that program number reaches this preset only while the default Program Map is in force" (:132-135).
- `backup list [--dir DIR] [--json]` (:342-384, parser :535-537): offline; a corrupt file prints as an error row rather than vanishing.
- `backup save REGION [--dir DIR] [--yes]` (:395-433, parser :538-541): the read-only "dump" of RAM presets to the backup envelope. "reading a whole RAM region needs --yes (128 requests)" (:400-403); only preset regions are allowed (`f"{entry.id} is not a preset region; preset backups only"` :405-407); walks slots with `device_any.read_preset(slot.index)` spaced by `PRESET_GAP` (:414-416), one `bk.save_preset` per preset with `source="emorphed (backup save)"`, progress via `render.progress` (:417-431).
- `read FILE [KIND]` (:139-155) — the offline dump reader; `names` (:90-95) and `status` (:98-108) are silent reads.
- Error policy (:634-644): command errors become `SystemExit(f"error: {exc}")` — "a missing one deserves the same sentence".
- Sweep line duplicated at :614-618 (`swept for ... s; found ...`).

There is no `send`/`set` verb in emorphed: writes are app-only (parameter editor), exactly per `CLAUDE.md:101-140` ("Preset writes remain **not offered**... there is still no ``restore`` command").

### rxved (`rxved/cli.py`, `rxvcli`)

Docstring (:24-28): "``select``, ``scan`` and ``scan-catalog`` change what the instrument is set to play, and the two scans -- which send a program change per slot -- refuse to run without ``--yes``."

- `mode [--yes]` (:1234-1242 parser): read, or "Re-run with --yes to do it" writing the sound mode (:378-389: "settings are not stored (OM p. 96). Re-run with --yes to do it").
- `perf-list [--dir]` (:953-971): offline table of backups.
- `perf-backup [{--slot N} | temporary]` (:1250-1257, cmd :974-995): quiet read → `bk.save(blocks, _backup_dir(args), slot=slot, device_id=..., source=bridge.description)`; defaults to `TEMPORARY_PERFORMANCE` with `slot=None`.
- `perf-verify SLOT --yes` (:998-1038): "Prove a user slot can be written, without changing it... it is still a write to stored memory. Re-run with --yes." (:1010-1015). Writes the slot's **identical** bytes back, reads again, compares; prints `MISMATCH: ...` + "Do not use `perf store`." if either round trip disagrees (:1024-1034).
- `perf-store SLOT --yes` (:1041-1073): the CLI mirror of the app's store: `backup_blocks, mismatched = bridge.store_temporary_to_slot(...)` then `bk.save(backup_blocks, ..., source=f"{bridge.description} (before store)")`; "previous contents of slot N ('name') saved to {path}"; on mismatch prints the **restore command**: `f"Restore with: rxvcli perf-restore {path} --slot {args.slot} --yes"` (:1071).
- `perf-restore FILE --slot N --yes` (:1076-1099): "**Destructive.**" — `bk.load(args.file)` refused wrong kind/format, then `write_performance_blocks(user_performance_base(args.slot), blocks)`; mismatch → `WARNING:` summary, success → `f"restored {bk.performance_name(blocks)!r} into user performance {args.slot}"`.
- `scan`/`probe-srx`/`scan-catalog` all stop with "Re-run with --yes" (:636-664, :687-692, :818-835).

`_backup_dir` (:938-943) = `args.dir or bk.default_dir(data_dir())`.

---

## 7. The tests that pin it

Neither repo has a literal `tests/test_no_sound.py`; the "never sends anything" property is pinned inside `tests/test_app.py` in both (emorphed asserts `device.selected_log == []` at ~13 sites, `tests/test_app.py:218,229,239,249,281,304,323,337`; rxved at `tests/test_app.py:198,1048,1056,1448,1467,1502,1525,1539,1548,1668,1798` with the explicit comment `assert app.bridge.selected_log == [], "sent program changes anyway"` :1502). The fake devices that make this assertable:

- **emorphed `DemoDevice`** (`emorphed/demo.py:160-…`): "Answers the subset of the protocol emorphed speaks." It logs exactly the things the rules care about (so tests can prove silence): `self.selected_log: list[tuple[banks.Slot, int]]`, `self.selected_midimaps`, `self.parameter_reads`, `self.parameter_writes`, `self.midimap_stores`, and `self.midimap_reads: list[int]` with the comment "A parameter round trip never touches this, so a test can prove 'no stored dump happened' by checking it stayed empty" (:193-196). It models the scratch/stored split: `self._midimap` (scratch — what `read_parameter` answers) and `self._stored_midimap` (what `read_midimap`/0x46 answers; "A parameter write does NOT touch this" :198-208). `write_parameter` writes the scratch and logs; `send_midimap` stores to *both* when the location is current (:342-360). Card regions raise `TimeoutError("...ignored outright when no card is fitted")` unless `card=True` (:176-179, :250-263). `_tick()` on a closed device raises `RuntimeError("this demo device is closed; ...")` (:216-223).
- **rxved `DemoBridge`** (`rxved/demo.py:94-119`): "Answers the subset of :class:`xv.bridge.XvBridge`... Not a subclass: xv.bridge imports rtmidi at module scope, and the point of this class is to work where that import fails." Logs `self.selected`, `self.selected_log`, `self.channel_log`, `self.raw_log` ("Raw (msb, lsb, pc) triples, which is how a restore goes out").

`tests/test_backup.py`:
- **emorphed** (`tests/test_backup.py:8` "Preset backups: the read-only half of a restore point"): `TestTheEnvelope` — a real preset round-trips through demo bytes (`assert loaded == m.to_words(words)`, :42-43); "test_the_envelope_never_overwrites" (`first.id != second.id`, :60); default dir is under the data dir and not the checkout (`assert "emorphed" in bk.default_dir()`, :72); a corrupt file is *listed with its error* (`broken[0].id == "corrupt.json"`, :88); refusals: preset asked as midimap (`"not a midimap backup"` :226), empty block (`"no preset block"` :154/upgrading), non-preset kind. `TestTheCliBackupCommands` monkeypatches `MorpheusBridge.open/connect` **and** `DemoDevice` to explode so "backup list tried to open a port" is an assertion failure (:258-267) — the offline command is truly offline. Fake device: `DemoDevice().read_preset(INDEX)`.
- **rxved** (`tests/test_backup.py:16-19` "Names here are invented"): `TestBlockMap` pins the address-map constants (36 blocks, manual sizes, `user_performance_base(1) == (0x20, 0)`, out-of-range slots refused :38-60) — the map is asserted *against a fake byte generator* (`_blocks`, :29-35, XOR-shift bytes with the name spliced into `common`); `TestRoundTrip` (lossless encode/decode, save/load, no-overwrite, listing keeps unreadable files); `TestRefusals` — future format, wrong kind, bad hex, empty ("A backup that would be misread must not be restored into user memory", :92-93); `TestPartialWritesAreRefused` uses `DemoBridge().write_performance_blocks(...)` so a missing `part9` raises `ValueError` (:121-127), plus "the demo stores and reads back" — `store_temporary_to_slot(5)` returns `mismatched == []`, stored == temporary, `previous != stored` (:129-138).

`tests/test_hardware.py` (both opt-in; `tests/conftest.py` defines `--hardware` and a session `synth`/`unit` fixture whose connect-failure is a **skip**, never a failure — rxved `conftest.py:16-20` "Nothing here runs unless you ask for it... A skip is a skip, not a pass"; emorphed the same for `EMORPHED_HARDWARE`):
- **rxved** (:16-44 doc): "Read-only, structural" block sizes against the machine (`test_every_block_comes_back_at_the_size_the_map_declares` :72-82); writes are "Temporary Performance first" and restored regardless of outcome (`TestHardwareTemporaryWrite` :164-187 — `PARKED_PART_LEVEL = 100`: "Not 0, which silences the part and looks exactly like a failed write" :55-56); "a part offset write lands in the offset it names" (:189-217: comparing the *whole block* to catch writes that land elsewhere — "a Roland map does not fail on a wrong address, it writes something else"); `TestHardwareSoundMode` is "the one place the hardware suite changes what the machine *is*... whichever of the two it started in is put back, in a ``finally``" (:220-248), GM modes refused by the bridge itself (:255-261).
- **emorphed** (:11-49 doc): "print-and-record" observations for TODO items, structural name-list asserts with **no names asserted** ("E-mu's ROM contents are not this project's to redistribute" :30-33), frame-shape/checksum asserts for preset reads (:274-293), bank-request capture to `EMORPHED_BANK_CAPTURE` (:360-366, "The default directory is outside the checkout on purpose"). No select, no program change, no store.

`tests/test_markup_crash.py` (emorphed only — 145 lines): the bracket-in-name regression. `MarkupDemo(DemoDevice)` serves names like `[g <`-^^`, `[b]x[/b]`, `[/dim]` (:19-36); the property is *no crash while rendering device-controlled strings*: `test_literal_escapes_bracket_names` (device names can never inject markup: `assert "[" not in escaped.replace("\\[", "")` :54-60), highlight/favourite/search do not crash (`64-96`), and the midimap editor shows a markup name *literally* in its name row / status (`128-145`). Fake device: subclass of `DemoDevice` returning the hostile names from `names()`.

`tests/test_cli_favorites.py` (both, near-identical): "``fav``, end to end... assert on the database and on stdout rather than on internals" (rxved :16-27). The pattern is "build the args, call the command" — parse with `cli.build_parser().parse_args(["--favorites", str(tmp_path / "favorites.db"), *argv])` then call `cli._cmd_fav/cli._cmd_favorites(None, args)` with `device=None` (offline by insertion into `OFFLINE`). Properties: `--rate` refuses a non-favourite rather than creating one (rxved :77-87), out-of-range rating is `SystemExit` not a traceback, `--add` is an upsert that *carries* existing rating/tags/note ("TestAddIsNotAWipe" :101-115), mutually-exclusive filter flags are the parser's error (:199-213), and the printed column is value-and-scale stars (:215-221). Fake device: none — the command must never open one.

---

## 8. The shape a port would follow (condensed)

1. **A pure envelope.** `backup.py` speaks JSON + named blocks, no MIDI, version-checked, never-overwriting filenames, lenient newest-first listing that reports unreadable files. Base the device files' naming on **where it converts** (destination-kind named in the header: "midimap"/"performance"; error strings name the slot and the held name).
2. **Workers-only MIDI.** The app/screen layer makes zero MIDI calls; every device interaction runs in a `@work(thread=True)` body communicating back with `call_from_thread`.
3. **One-at-a-time exchange.** Two signals (a BusyGate for "in flight", one for "pending refusal") plus a third for the claim race (`_exchange.locked()` / `_busy` set on the main thread before spawning). All bridge-touching except blocks wrapped in `except <family bridge errors>` with the family tuple `{ConnectionError, TimeoutError, OSError} ∪ {ValueError, LookupError, RuntimeError, SystemError}`.
4. **Gate the write.** A session-scoped `EditGate` (`armed` default from `--allow-write`), `w` toggles it, refusals are sentences, not swallowed; render refusals via a `.refused` class, never a text prefix.
5. **Back up before the first write of the session**, from the device's own bytes; announce the resulting filename; refuse the destructive operation (`store`) if no backup succeeded.
6. **Every write verified by read-back; count agreement and say it.** The returned/verified value is the one the device reports; only agreed writes enter the undo log; failed/silent reads roll the optimistic UI value back (`_pre_edit` + `result(False, ...)`).
7. **Destructive store = arm-then-fire**: pick destination (name it), arm (`a`), fire (`w`, different key); confirm modal; on the backing bridge read the destination first, then write, then read the destination back; the error path names the backup file and prints the restore command.
8. **CLI mirrors the app**: offline list commands, `--yes` on anything destructive or multi-message, `--allow-write` arms only the start state, error → one `SystemExit(f"error: ...")` line.
9. **Fake devices that log intents**, not effects: `selected_log`, `parameter_writes`, `stores`, `reads` — so "no sound / no stored dump" is `assert log == []`, and hardware tests are opt-in skips with restore-in-`finally` discipline.
