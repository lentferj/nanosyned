# The p2ked WRITE PATH — a quote-backed description, for porting the shape

Repository: `/home/lentferj/git-repos/p2ked` (branch `ui-state-parity`, HEAD `2f0bb14`).
Library: `/home/lentferj/git-repos/vinsynlib/src/vinsynlib` (`backup.py`, `undo.py`).

Everything below is read from source; nothing was modified.

## 0. Two premise corrections before anything else

The task brief names some symbols that **do not exist in this repository**. Stated once,
here, rather than repeated:

- **There is no CLI write surface named `send`, `set`, or `dump`, and no CLI
  `--allow-write`.** `p2ked/cli.py`'s command table is exactly
  `banks/roms, list, find, resolve, ports, status, hardware/config, channels, names,
  scan, select, backup` (`cli.py:614-634`, subparsers `cli.py:727-802`). The only CLI
  write is `backup restore` (destructive, behind `--yes`), and the only other `--yes`
  is `scan --rebuild`. `--allow-write` exists **only** on the TUI (`app.py:3684`,
  via `vinsynlib.cli.add_common_arguments`). A whole-repo grep for `_cmd_send`,
  `_cmd_set`, `_cmd_dump` in all history returns nothing.
- **There is no `_BRIDGE_ERRORS`, no `close_when_idle`, and no "exchange claim" object.**
  The single-writer discipline is the boolean `P2kedApp._busy` plus one
  `threading.RLock` (`self._lock`, `app.py:1795`), with `_channel_inflight` /
  `_channel_target` as the per-cell coalescing slot (`app.py:629-630`). Any port target
  that names those three things is describing a shape this code does not have.

The rest of the report describes what is actually there.

---

## 1. `p2ked/masteredit.py` — tables, gate, logs, editor

### 1.1 `MasterParameter` and the parameter tables

`MasterParameter` is a frozen dataclass; the docstring is explicit that `low`/`high` are
**inclusive and signed** and that `base` is the value the first `choices` name is
numbered by (`masteredit.py:95-123`):

```python
@dataclass(frozen=True)
class MasterParameter:
    parameter_id: int
    label: str
    low: int
    high: int
    choices: Tuple[str, ...] = ()
    note: str = ""
    base: int = 0
```

`_p(...)` is the 7-positional-arg constructor helper (`masteredit.py:126-138`).

- `MASTER_PARAMETERS: Tuple[MasterParameter, ...]` — 11 general rows, order = edit-screen
  order (`masteredit.py:151-236`). Ranges are signed where the wire is signed
  (`MASTER_TRANSPOSE` −24..24, `MASTER_TUNE` −63..63).
- `FX_A_ALGORITHMS` (44 names) and `FX_B_ALGORITHMS` (32 names) (`masteredit.py:248-338`).
- `FX_PARAMETERS` — the 16-effect block, **in the dump's own order** 513..528. The two
  algorithm rows carry `base=1` (`masteredit.py:374-508`, esp. 383 and 441).
- `MASTER_BY_ID: Dict[int, MasterParameter]` — the **one lookup the app's edit path
  checks**, built by merging both tables (`masteredit.py:520-523`):

```python
MASTER_BY_ID: Dict[int, MasterParameter] = {
    **{parameter.parameter_id: parameter for parameter in MASTER_PARAMETERS},
    **{parameter.parameter_id: parameter for parameter in FX_PARAMETERS},
}
```

`CHANNEL_EDIT_HINT` is a long prose sentence shown on the FX-adjacent channel screens
(`masteredit.py:546-557`); `SOUND_FIELD = "sound"` (`masteredit.py:573`).

### 1.2 `CHANNEL_FIELDS`, `ChannelField`, `fields_of`, `mutate_channel`

`CHANNEL_FIELDS: Dict[str, ChannelField]` is built by iterating the wire's own
`params.CHANNEL_PARAMETERS`, so it cannot drift from the dump (`masteredit.py:583-606`):

```python
for _name, _low, _high in params.CHANNEL_PARAMETERS:
    CHANNEL_FIELDS[_name] = ChannelField(_name, _low, _high)
```

`ChannelField.holds(value)` is the signed inclusive test (`masteredit.py:599-601`).

`fields_of(field)` maps the synthetic `"sound"` to the three dump fields **in dump
order** (`masteredit.py:609-623`):

```python
if field == SOUND_FIELD:
    return ("preset", "bank_map", "rom_id")
return (field,)
```

`channel_label(channel, field)` is the 1-based display name (`masteredit.py:626-633`).
`channel_values(dump, channel, names)` returns `None` (not zeros) for an absent channel
(`masteredit.py:636-648`).

`mutate_channel(dump, channel, values) -> SetupDump` is **pure** — it rebuilds one
`ChannelState` from the original's own fields and splices a new `SetupDump`, raising
`ProtocolError` for an absent channel or a field that is not one of the nine
(`masteredit.py:651-716`):

```python
replaced = params.ChannelState(entry.channel)
for name, _low, _high in params.CHANNEL_PARAMETERS:
    setattr(replaced, name,
            values[name] if name in values else getattr(entry, name))
channels = tuple(replaced if entry.channel == other.channel else other
                 for other in dump.channels)
return params.SetupDump(dump.name, channels, channel_count=..., ...)
```

Range is deliberately **not** checked here; that is the editor's job (see 1.4).

### 1.3 `ChannelChange` and `ChannelLog`

`ChannelChange` is a frozen record that **carries its own data** (unlike `EditChange`,
`app.py:257-270`): `channel`, `field`, `before | Tuple`, `after | Tuple`
(`masteredit.py:719-777`). Derived properties: `fields` (= `fields_of`), `restore_values`,
`sent_values`, `restore` (`dict(zip(self.fields, self.restore_values, strict=True))`),
`label` (`channel 6 volume`, 1-based), `spelled` (words for a report).

`ChannelLog` is a plain append/take list for the whole-dump route, separate from `EditLog`
because the two answer different plan shapes (`masteredit.py:780-813`): `record`,
`pending`, `take(count)` (last N **newest first, and drop**), `clear`.

`CHANNEL_EDIT_IDS: Optional[Dict[str, int]] = None` — the per-channel ID route is
deliberately not guessed (`masteredit.py:826`).

### 1.4 `EditGate` semantics: arm / lock / check / refuse

`EditGate` is *just* the boolean and its sentences; there is no lock object and no
`check()` method. Locked by default (`masteredit.py:829-853`):

```python
def __init__(self, *, armed: bool = False) -> None:
    self.armed = armed


def toggle(self) -> bool:
    self.armed = not self.armed
    return self.armed


def describe(self) -> str:
    return "write gate ARMED" if self.armed else "write gate locked"


def refuse(self, what: str) -> str:
    return (
        f"{what} not sent: the write gate is locked. Press w to arm it, "
        f"or start with --allow-write."
    )
```

The **check** lives on `MasterEditor` and always asks the gate **before** the range, so an
armed gate cannot turn a silent refusal into a sent edit (`masteredit.py:920-934`):

```python
def allow(self, parameter, value) -> Optional[str]:
    if not self.gate.armed:
        return self.gate.refuse(f"{parameter.label}")
    if not parameter.low <= value <= parameter.high:
        return (
            f"{parameter.label} must be {parameter.low}-{parameter.high}, "
            f"and {value} is not"
        )
    return None
```

### 1.5 `EditLog` and the `MasterEditor` read/write/verify flow

`EditLog.changes: List[Tuple[int, int, int]]` = `(parameter_id, old, new)`; `record`,
`pending`, `take(count)` newest-first-and-drop, `clear` (`masteredit.py:856-883`). The
docstring states the ordering rule: the **old** value is recorded before the new one goes
out, because a failed write has nothing to read back.

`MasterEditor` is pure — no I/O (`masteredit.py:886-918`): holds `gate`, `log`,
`channel_log`.

`finish(parameter, value, *, before, after) -> (bool, str)` is the verify step
(`masteredit.py:936-968`):

```python
if after is None:
    return False, (
        f"{parameter.label} = {value} was sent, but the read-back "
        f"failed; nothing is logged, so undo cannot restore it"
    )
if after != value:
    return False, (
        f"{parameter.label} did not take {value}: the unit still reports {after!r}. ..."
    )
self.log.record(parameter.parameter_id, value if before is None else before, value)
return True, f"{parameter.label} = {value}"
```

Note the `before is None` fallback: an unreadable prior value is recorded as the value
sent, never invented as 0.

`undo_plan(count)` returns `[(pid, old) ...]` newest-first, taken off the log
(`masteredit.py:970-981`); `undo_report(results)` is the one-sentence summary
(`masteredit.py:983-994`).

### 1.6 The per-channel half of the editor

- `allow_channel_field(channel, field, value)` — gate first, then field membership in
  `CHANNEL_FIELDS`, then `holds` (`masteredit.py:998-1027`).
- `allow_channel_sound(channel, *, rom_id, preset, bank_map)` — ranges the three in dump
  order, first out-of-range wins (`masteredit.py:1029-1053`).
- `decline_channel(dump, channel, values)` — the checks that need a dump in hand: channel
  exists, and `dump.undecoded` is empty, else refuse rather than write back zeros
  (`masteredit.py:1055-1086`). No gate check here (already asked on the main thread).
- `finish_channel(change, read_back)` — logs **only** when the read-back tuple equals the
  sent tuple; `None` read-back and disagreement are distinct sentences
  (`masteredit.py:1088-1125`).
- `channel_undo_plan(count)` / `channel_undo_report(results)` / `channel_pending`
  (`masteredit.py:1127-1161`).

### 1.7 `probe_channel_ids`

Read-only sweep over a parameter-ID range, returning `{"low","high","answered"}`
(`masteredit.py:1164-1192`). It never writes — pinned by tests (see §8).

---

## 2. `p2ked/multi.py` — the screens

### 2.1 `MultiScreen` (modal, `modal_type=None`)

Shows 32 channels + master summary; **silent** to read; editable **cell by cell**
(`multi.py:267-298`). The table is built from `CELLS: Tuple[_Cell, ...]`
(`multi.py:195-217`), where each cell declares `key/label/kind/field/names/base` and
`kind ∈ {"read","number","named","switch","sound"}` (`multi.py:155-182`). The three
sound fields (`preset`, `bank_map`, `rom_id`) deliberately get **no cell** — they are one
gesture `s` (`multi.py:185-194`).

Bindings (`multi.py:312-368`): `escape/q` close, `r` re-read, `e` master edit,
`w` write gate, `x` FX, `z`/`Z` undo, `space` toggle, `+`/`=`/`-` bump, `s` pick sound,
and digits `0-9` type in place. Every editing gesture funnels into one method
(`multi.py:872-885`):

```python
def _edit_channel(self, channel, field, value) -> None:
    on_edit = self._on_edit_channel
    if on_edit is None:
        _say(self.app, "this screen has no per-channel edit path", refused=True)
        return
    on_edit(channel, field, value)
```

The screen **owns no device and starts no worker** — it calls the app's
`action_edit_channel` / `action_channel_sound` (docstring `multi.py:285-289`).

`action_toggle_write_gate` toggles the app-provided gate object in place and redraws the
note (`multi.py:668-683`). `action_edit`, `action_edit_fx`, `action_undo`,
`action_undo_all` are thin calls to callbacks the app passed in (`multi.py:664-712`).

**Staging / drawing seams** (the app calls these back):

- `channel_target(channel, values)` — draw the optimistic target the moment a key is
  accepted (`multi.py:1186-1204`).
- `channel_reported(channel, values)` — put back what the unit reports
  (`multi.py:1206-1214`).
- `channel_result(ok, message, change)` — on success adopt `change.sent_values`
  (`multi.py:1154-1173`).
- `channel_undone(changes)` — for each `(change, ok)` with ok, adopt
  `change.restore_values` (`multi.py:1175-1184`).
- `_put_values` is the single writer of the screen's dump copy; `_draw_row` uses
  `DataTable.update_cell` (not `refresh()`) (`multi.py:1216-1260`).
- It also implements the *master-edit* seams `say`, `result`, `undone` so the app can
  report through it while it is the live screen (`multi.py:1098-1152`).

`action_bump` clamps then hands the value on; a step that cannot move is said, not sent
(`multi.py:933-969`). `_pick_sound` carries `bank_map` over rather than inventing it
(`multi.py:1012-1042`).

### 2.2 `SoundPickerScreen`

A modal `ModalScreen[Optional[roms.Preset]]` with a bank pane and a slot pane, filter
input, favourites view; returns a `roms.Preset` or `None` on cancel
(`multi.py:1277-1596`). It holds no device and writes nothing.

### 2.3 `MasterEditScreen`

The table editor over one parameter table — parameterised rather than duplicated
(`multi.py:1599-1624`). Constructor takes `(dump, values, editor, *, parameters=
MASTER_PARAMETERS, title, note=CHANNEL_EDIT_HINT, on_edit_fx, on_apply, on_undo)`
(`multi.py:1688-1721`).

- `_report()` shows the gate state, the undo count from `self._editor.log.pending`, and
  the note (`multi.py:1753-1766`).
- `compose()` yields a `DataTable`, a `.note` Static, and a `.status` Static
  (`multi.py:1770-1783`); `on_mount` adds columns `param/now/range` and one row per
  parameter keyed by `str(parameter_id)` (`multi.py:1785-1799`).
- `on_data_table_row_selected` → `_offer(parameter)`; a `choices` parameter opens
  `ValuePickerScreen`, otherwise `PromptScreen` (`multi.py:1801-1852`). The answer goes
  to `on_apply(parameter_id, value)` — the **same door** either way.
- `action_nudge_up/down` → `_nudge(by)`, which clamps to `parameter.low/high` and calls
  `on_apply` (`multi.py:1896-1943`).
- `action_toggle_write_gate` toggles the shared gate and redraws the note
  (`multi.py:1882-1894`).
- `result(ok, message, parameter_id, value)` — on success update `_values[pid]` and
  `_draw(pid)`, then `_say` the sentence (`multi.py:1977-1997`).
- `undone(plan, results)` — zip plan/results, redraw each applied parameter
  (`multi.py:1999-2017`).
- `say(message, *, refused)` writes `[b]refused[/b] · ` prefix onto `.status`
  (`multi.py:1959-1975`).
- `_draw` updates one `now` cell and the note, guarded by try/except for a closed screen
  (`multi.py:2019-2042`).

### 2.4 `FXEditScreen(MasterEditScreen)`

Fixes `parameters=FX_PARAMETERS`, `title="Multi — master FX"`, `note=FX_EDIT_HINT`, and
its own `TABLE_ID="fx-table"`; drops the `x` binding because there is nothing further to
open (`multi.py:2045-2117`).

### 2.5 `ValuePickerScreen`

`ModalScreen[Optional[int]]` over a `choices` list. The key arithmetic is the `base`
handling (`multi.py:2120-2237`): `_value_of(row) = base + row`, `_row_of(value) = value -
base`. `enter` dismisses with `_value_of(cursor_row)`; `escape/q` dismiss with `None`.
This is what makes an FX algorithm pick (`Room 3`) answer the value `3` and not row index
`2`.

### 2.6 `ChannelDetailScreen`

Read-only `ModalScreen[None]`; spells the nine fields and the silence reasons, and says
where the editing actually is (the multi table) plus prints `CHANNEL_EDIT_HINT`
(`multi.py:2240-2358`).

### 2.7 How edits are staged, applied, verified, undone (UI view)

The screens only **stage** (callbacks + optimistic redraw). The app **applies** on a
worker, **verifies** by reading the parameter or the dump field back, and **undoes** from
the shared timeline. The screens then get `result`/`undone`/`channel_result`/
`channel_undone` callbacks to redraw from verified values.

---

## 3. `p2k/backup.py` and `vinsynlib.backup`

### 3.1 What `p2k/backup.py` adds

It is a thin binding of the family's library (`backup.py:16-46`). Constants:
`APP_NAME = favorites.APP_NAME`, `KIND = "setup"`, `BLOCK = "setup"`
(`backup.py:71-84`). `Backup(_backup.Backup)` adds the one field the library lacks — the
filename-as-handle `id: str = ""` (`backup.py:87-101`).

`default_dir()` = `<data_dir>/backups` (`backup.py:104-113`).

`save_setup(dump, *, device_id, slot, source="p2ked", directory=None)` (`backup.py:144-183`):
encodes `m.encode_setup_dump(dump, device=device_id)` (the parser's exact inverse) as the
single `"setup"` block and writes it through `_backup.save`; returns p2ked's `Backup`.

`list_backups(directory=None)` — newest-first, and a corrupt-unreadable file is **listed
with its `error`** rather than dropped (`backup.py:186-224`).

`load(id, *, directory=None) -> SetupDump` (`backup.py:227-250`): refuses a non-setup
kind, refuses a missing block, then `m.parse(frame)` → `m.parse_setup_dump(packet)`,
ready for `send_setup_dump`.

### 3.2 The library envelope (`vinsynlib/backup.py`)

`FORMAT = 1`; `Backup(kind, slot, name, saved, device_id, source, blocks: dict[str,
bytes], error)` (`backup.py:16-30`). Blocks are base64-attached/detached
(`_encode_blocks`/`_decode_blocks`, lines 33-38). `save(...)` makes a filename from
sanitised `kind_slot_name_saved` and **appends `_count` until it does not exist** — never
overwrites (`backup.py:51-92`). `load` type-checks `format == FORMAT` and `kind`
(`backup.py:95-127`). `list_backups` returns partial records with `error` on a parse
failure (`backup.py:130-182`).

### 3.3 When a backup is taken (pre-write) and how restore works

The **only** automatic backup is in `P2kedApp._backup_before_write`
(`app.py:1132-1175`), called from the channel-edit worker **before** the `send`, once per
session:

```python
if self._setup_backed_up:
    return
try:
    record = bk.save_setup(
        dump,
        device_id=self.device.device_id,
        slot="live",
        source="p2ked (before edit)",
        directory=self.backup_dir(),
    )
except Exception as exc:
    self.call_from_thread(
        self._say_edit, f"could not back up the setup: {exc}", refused=True
    )
    return
self._setup_backed_up = True
self.call_from_thread(self._say_edit, f"backed up the setup as {record.id}")
```

What is saved is the **live dump the worker just read, before it is mutated**. A failed
backup does not stop the write (it is announced as a refusal). The flag lives on the app,
so a burst costs one file.

Restore is CLI-only (`cli.py:571-601`): `bk.load` → `device.send_setup_dump(dump)` →
read the setup back and compare `encode_setup_dump(after)` with
`encode_setup_dump(dump)`, warning on mismatch.

---

## 4. `vinsynlib.undo` usage in `app.py` — the plan/settle seam

### 4.1 The library

`Record(label, payload)` is frozen inspectable data, never a closure
(`undo.py:15-20`). `UndoLog` has **two doors** (`undo.py:23-50`):

- `undo`/`undo_all` — pop-only-after-success (re-send a value; a failure stays on the log).
- `plan(count)`/`settle(results)` — **consume-on-take**, for a tool whose work runs on its
  own thread. A gate refusal returns `[]` and is recorded on `last_refusal`
  (`undo.py:124-148`).

`push`, `clear`, `__iter__`, `__len__`, `__bool__`, `last_error`, `last_refusal`
(`undo.py:69-89`). The app uses the **plan/settle** door.

### 4.2 `_Change` records in the app

The timeline element types are `EditChange` (a *position* marker carrying no data,
`app.py:257-270`), `FavouriteChange` (`app.py:273-288`), `RatingChange`
(`app.py:291-309`), and `ChannelChange` (from masteredit). `Change = EditChange |
FavouriteChange | RatingChange | ChannelChange` (`app.py:332`). `_change_label` maps each
to one word (`app.py:335-351`).

`_ChangesView(List[Change])` is a window over the library log; its `append` writes
through with `self._log.push(Record(_change_label(change), change))` (`app.py:354-371`).
`_changes` property rebuilds the list from `[r.payload for r in self._undo_log]`;
the setter clears and re-pushes (`app.py:1434-1448`). `_push_change` is the one push site
(`app.py:1450-1458`).

### 4.3 `z`/`Z` wiring and the plan/settle seam

Keys: app bindings `z → action_undo`, `Z → action_undo_all` (`app.py:607-608`); the same
two are re-bound on `MultiScreen` and `MasterEditScreen` because a modal cuts the app's
binding chain (`multi.py:343-344`, `multi.py:1684-1685`). `action_undo` calls
`_undo_master_edits(1)`; `action_undo_all` calls `_undo_master_edits(None)`
(`app.py:695-713`).

`_undo_gate()` is the gate_hook handed to the log at construction
(`app.py:1734`): it returns `"busy"` while a write is in flight, else `None`
(`app.py:1460-1470`).

`_undo_master_edits` (`app.py:1472-1551`): takes the plan from the library

```python
taken = self._undo_log.plan(len(self._changes) if count is None else count)
if not taken:
    refusal = self._undo_log.last_refusal
    if refusal is not None:
        self._say_edit(refusal, refused=True)  # the refusal under a locked/busy gate
    elif not self._changes:
        self._say_edit("nothing to undo")
    return
changes = [record.payload for record in taken]
```

Local kinds (`FavouriteChange`, `RatingChange`) are undone first on the main thread with
no wire (`app.py:1522-1527`, `_undo_favourite` 1553-1568, `_undo_rating` 1570-1589). The
wired kinds are split: `channels` are handed to the worker as `ChannelChange` records,
and `edits` have their counts fed back to `self._editor.undo_plan(edits)` (the editor's
own log loses the same count, so the two cannot drift) (`app.py:1531-1544`). The worker
`_undo_worker(plan, channels, favourites, ratings)` sends each master `(pid, value)` and
each channel restore under `self._lock` (`app.py:1591-1624`); `_edit_undone` reports on
the main thread and calls `screen.undone(plan, results)` and
`screen.channel_undone(undone)` (`app.py:1649-1667`); `_undo_sentence` assembles the
four-kind sentence (`app.py:1669-1705`).

`_restore_channel(change)` re-reads the live dump, `mutate_channel(dump, channel,
change.restore)`, sends, reads back, and returns True only if the field matches
(`app.py:1626-1647`). Note the undo re-reads rather than reusing the edit-time dump, since
the unit may have been edited by hand meanwhile.

**Refusal under a locked gate:** the gate is consulted by the log itself
(`gate_hook=self._undo_gate`), so a `z` while `_busy` yields `"busy"` via
`last_refusal`; a locked *write* gate does **not** block undo — undo sends values back
through the same `Allow`-checked pipeline? No: undo sends via `self.device.set_parameter`
/ `send_setup_dump` directly, so **undo is not re-gated** by `EditGate` (only by
`_busy`). This is deliberate: the entry was verified when it was made.

---

## 5. `p2ked/app.py` — write gate binding, `w`, `--allow-write`, busy claim

- **`w` binding**: `Binding("w", "toggle_write_gate", "Write gate")` (`app.py:606`),
  plus the legend entry `"w write gate"` in `KEY_HINTS` (`app.py:237`).
- **`action_toggle_write_gate`**: `self._gate.toggle(); self.notify_status(
  self._gate.describe())` (`app.py:691-693`).
- **One gate per app**, created lazily; `--allow-write` is the *starting state*, not a
  second object (`app.py:657-669`):

```python
@property
def _gate(self) -> EditGate:
    if getattr(self, "_write_gate", None) is None:
        self._write_gate = EditGate(armed=self._allow_write)
    return self._write_gate
```

- **One editor per app** on that gate (`app.py:671-676`):
  `MasterEditor(self._gate, EditLog())`.
- `_allow_write` is stored in `__init__` (`app.py:1739`); `build_parser()` passes
  `allow_write=True` to the family's `add_common_arguments` (`app.py:3684`) and `main()`
  threads `allow_write=args.allow_write` (`app.py:3843`). The CLI does **not** take it
  (§0).
- `backup_dir()` returns the injected `--backup-dir` or `bk.default_dir()`
  (`app.py:678-689`); `--backup-dir` is added at `app.py:3695-3700`.
- **Busy claim**: `_busy: bool` declared at class level (`app.py:622`) and set on the
  main thread *before* a worker is spawned; cleared on the main thread in the worker's
  callback. The whole MIDI section of each worker runs under `with self._lock:`
  (`self._lock = threading.RLock()`, `app.py:1795`). There is no `close_when_idle` and no
  `_BRIDGE_ERRORS`; teardown is `store.close(); device.close()` in `main`'s `finally`
  (`app.py:3850-3852`).
- The **master edit** door `_apply_master_edit(parameter_id, value)` (`app.py:894-931`):
  look up `MASTER_BY_ID` (refuse an unknown ID), `self._editor.allow(...)` (gate then
  range), `if self._busy: self._say_edit("busy", refused=True)`, else set `_busy` and
  spawn `_apply_worker`. `_apply_worker` reads-before, `set_parameter`, reads-after, all
  under the lock; `_edit_applied` calls `self._editor.finish(...)` and only on `ok`
  `self._push_change(EditChange())` (`app.py:933-989`).
- The **per-channel** door `action_edit_channel` (`app.py:993-1042`) checks
  `allow_channel_field` on the main thread, then `_start_channel_edit`.
  `action_channel_sound` (`app.py:1044-1071`) checks `allow_channel_sound` and starts the
  `SOUND_FIELD` edit.
- **The coalescing slot**: `_start_channel_edit` (`app.py:1073-1106`) — if
  `_channel_inflight == (channel, field)`, stash `values` in `_channel_target` and redraw;
  else if `_busy`, refuse `"busy"`; else claim `_busy`, set `_channel_inflight`, redraw
  the target, spawn `_channel_edit_worker`.
- `_channel_edit_worker` (`app.py:1218-1315`) loops: read dump, `decline_channel`, then
  `_allow_channel_values` (re-checks gate/range **per write**, because `w` stays live),
  `_backup_before_write(dump)`, `mutate_channel`, `send_setup_dump`, read again; computes
  `landed`; if landed and `_channel_target` differs, loops with the new target, else
  returns. `_channel_edited` (`app.py:1317-1417`) does the main-thread bookkeeping, logs a
  `ChannelChange` only when `finish_channel` agreed, redraws, and either clears
  `_busy`/`_channel_inflight` or re-spawns for a pending target.
- `_say_edit` writes to the live screen's `.status` *and* the app's `#status`
  (`app.py:753-770`); `notify_status` prefixes `[b]refused[/b] · ` (`app.py:2727-2729`).

---

## 6. `p2k/bridge.py` — the write methods

Exact signatures:

```python
def set_parameter(self, parameter_id: int, value: int, *,
                  timeout: Optional[float] = None) -> None          # bridge.py:689
def send_setup_dump(self, dump: m.SetupDump, *,
                    timeout: Optional[float] = None) -> None        # bridge.py:710
def copy_master_setup(self, source: int, destination: int, *,
                      timeout: Optional[float] = None) -> None      # bridge.py:746
def select(self, entry: roms.Preset, *, channel: int = 0) -> None   # bridge.py:846
```

**How a write is sent.** Each drains then `_send`s one frame (`bridge.py:300-302`):

```python
def _send(self, frame: bytes) -> None:
    self._out.send_message(list(frame))
    time.sleep(SEND_GAP)
```

`_drain()` throws away anything already waiting (`bridge.py:290-298`). `set_parameter`
(`bridge.py:707-708`) does `self._drain(); self._send(m.parameter_edit(parameter_id,
value, device=self.device_id))`. `send_setup_dump` (`bridge.py:743-744`) does
`self._drain(); self._send(m.encode_setup_dump(dump, device=self.device_id))` — **one
frame, no chunking** (docstring `bridge.py:725-733`). `copy_master_setup` sends
`m.copy_master_setup(...)`. `select` sends the three Channel Voice literals
(`bridge.py:853-859`).

**How read-back verify is done.** It is **not** in the bridge. The docstrings say so
explicitly — "Sent, then not verified: the write gate, the undo log and the read-back
that follows belong to the caller" (`bridge.py:698-701`, `711-742`). The caller (app)
reads through `read_parameter(parameter_id, *, timeout=None) -> int` (`bridge.py:666-687`)
or `read_setup(*, timeout=None) -> SetupDump` (`bridge.py:771-785`). `read_parameter`
matches the reply on the **parameter ID**, so a late reply cannot be mistaken for this
one (`bridge.py:679-687`).

**Refusal / timeout.** The unit does not refuse; it is silent. `_await` raises
`TimeoutError` with the list of indistinguishable causes (`bridge.py:304-326`):

```python
raise TimeoutError(
    "no reply. A Proteus does not refuse a request it cannot serve, "
    "it ignores it -- so this means one of: powered off, wrong port, "
    "device ID mismatch (p2ked is using {self.device_id}), System "
    "Exclusive disabled on the unit, or simply busy. ..."
)
```

A write itself raises only if `send_message` raises; the app converts an exception into
the `failure` branch of the result sentence.

**The dump encoder ("build the message back from a record").** There is no
bridge-side encoder-from-record. The round trip is: a saved `Backup` block →
`p2k.backup.load` → `m.parse(frame)` + `m.parse_setup_dump(packet)` → a `SetupDump` →
`ProteusBridge.send_setup_dump` re-encodes it with `m.encode_setup_dump(dump,
device=self.device_id)`. `encode_setup_dump` is the parser's exact inverse, which is what
makes an unmodified round trip byte-exact. The app's `_restore_channel` and the CLI's
`backup restore` both use exactly this path.

---

## 7. The CLI write surface (`p2ked/cli.py`) — actual

- Command table `_COMMANDS` and `_OFFLINE` (`cli.py:614-638`). `_offline(args)` marks
  `backup list` as the one no-port member of the backup group (`cli.py:641-653`).
- `backup` group subparsers (`cli.py:781-802`): `list [--dir] [--json]`,
  `save [--dir]`, `restore id [--dir] [--yes]`.
- `_cmd_backup_save` (`cli.py:557-568`) reads the setup and `bk.save_setup(..., slot=
  "live", source="p2ked (manual)")` — **read-only on the unit**.
- `_cmd_backup_restore` (`cli.py:571-601`) is the only destructive CLI write. It refuses
  without `--yes`:

```python
if not args.yes:
    raise SystemExit(
        f"error: this overwrites the unit's whole live setup with "
        f"{dump.name!r} from {args.id}. ... Save it first with "
        f"`p2kcli backup save`, then re-run with --yes."
    )
device.send_setup_dump(dump)
after = device.read_setup()
if msg.encode_setup_dump(after, device=device.device_id) != msg.encode_setup_dump(
    dump, device=device.device_id
):
    print(f"WARNING: the unit reports a setup that differs from {args.id} ...")
    return
print(f"restored {dump.name!r} into the unit's live setup")
```

- There is **no `send`, `set`, or `dump` command**; there is **no CLI `--allow-write`,
  `EditGate`, or undo log**. The other `--yes` is `scan --rebuild` (`cli.py:765-774`),
  which guards the catalog, not the unit. Confirmation style is `SystemExit` with a
  message naming what would be overwritten and how to proceed.
- `_build_device` (`cli.py:806-848`) honours `--demo`, opens a port or connects, learns
  the device ID, and remembers the port; `main` closes the device in `finally`
  (`cli.py:869-878`).

---

## 8. The tests that pin the write behaviour

The shared fake is `p2ked.demo.DemoDevice` (§8.7). Tests drive Textual via `app.run_test()`
/ `pilot`, and use a `_wait_for(pilot, ready)` helper because every operation returns via
`call_from_thread`.

### 8.1 `tests/test_masteredit.py`

Header enumerates the five properties: gate locked by default; out-of-range refused;
logged only when read-back agreed; undo sends the previous value; an unnamed parameter ID
is never written (`test_masteredit.py:16-47`). Two levels: pure `MasterEditor` directly,
and app workers headless against `DemoDevice`.

- `TestTheGateIsLockedByDefault` — `EditGate().armed is False`, `describe()`, refusal
  sentence names `w`; `app._editor.gate is app._gate`; `w` toggles and announces.
- `TestAllowWriteArmsTheGateAtStartup` — parser default False, `--allow-write` True;
  `allow_write=True` reaches the unit with no key (`set_log == [(MASTER_TRANSPOSE, 5)]`),
  and the same run without the flag is refused with `set_log == []`
  (`test_masteredit.py:232-252`).
- `TestALockedEditIsRefused` — asserts on `app.device.set_log == []` ("a locked edit still
  reached the unit").
- `TestAnOutOfRangeEditIsRefused` — inclusive bounds both ends, sentence exactly
  `"transpose must be -24-24, and 25 is not"`.
- `TestAReadBackThatDisagreesIsNotLogged` — `finish` returns False and logs nothing on
  `after=None` / `after != value`; a `Broken(DemoDevice)` overriding `read_parameter` to
  raise, and a `Deaf(DemoDevice)` overriding `set_parameter` to *handle but not record*
  (`test_masteredit.py:391-442`).
- `TestUndoSendsThePreviousValue` — log holds `(pid, old, new)`; `undo_plan` newest-first
  and taken; app `z`/`Z` send previous values newest-first.
- `TestThePerChannelProbeWritesNothing` — `probe_channel_ids` over a `WireReading(DemoDevice)`
  that puts the request on the wire and stays silent for unknown IDs: asserts every emitted
  frame's command is `PARAMETER_REQUEST` and `set_log == []` (`test_masteredit.py:618-663`).
- `TestTheMasterEditScreen` — table columns/rows, `?` for unreadable, `unknown (9)` for an
  out-of-enumeration choice, `ValuePickerScreen` round trip, PromptScreen word refusal.
- `TestTheMasterFxBlock` — FX block is `dict(m.MASTER_BLOCKS)["master effects"]` in order
  513..528; algorithms `base=1`; FX B delay keeps no names; `MASTER_BY_ID` holds both
  tables; an FX edit is written+read back, a locked gate refuses, `undo` sends the previous
  FX value, and an enumeration pick by index.
- `TestUndoCoversBothKindsOfChange` — `f` then `z` restores; `z` after a favourite restores
  the *previous* state, not the complement; `z` after a master edit still reverses the edit.

### 8.2 `tests/test_channel_edits.py`

Header: the four properties — locked gate sends nothing; only the edited field's bytes
move; read-back is what gets logged; `z` puts the previous value back across both kinds
(`test_channel_edits.py:16-46`).

- `TestTheMutationIsTheOnlyThingThatMoves` — `mutate_channel` vs `m.encode_setup_dump`,
  comparing moved byte offsets (`_frame_offset` computed from the dump header), both bytes
  for a >127 value, other fields/channels untouched, original dump unmodified, unmodified
  round-trip byte-exact, a write lands in the fake as `device.dump_log == [written]`,
  `ProtocolError` for an unknown channel/field.
- `TestTheRangeCheck` — `CHANNEL_FIELDS` agrees with `m.CHANNEL_PARAMETERS`; both ends
  allowed; signed negatives (`mix_output -1..2`, `arp -2..1`); gate before range;
  sound ranged as one tuple; `finish_channel` agree/disagree/None; channel undo plan and
  report.
- `TestTheRecord` — `ChannelChange` properties; `channel_values` `None` for absent channel;
  `decline_channel` refuses an undecoded dump.
- `TestALockedChannelEditIsRefused` — asserts on `app.device.dump_log == []` and
  `received == []`; `--allow-write` writes one dump; out-of-range; absent channel; a
  `HalfRead(DemoDevice)` setting `dump.undecoded`; a busy-wire refusal.
- `TestAChannelEditIsWrittenAndReadBack` — one `SETUP_DUMP` frame out; read-back from the
  unit's own post-write dump; `Deaf(DemoDevice)` ignoring the dump is not logged and cannot
  be undone; `Broken(DemoDevice)` raising.
- `TestABurstOfNudgesOnOneCellIsCoalesced` — `_Counting(DemoDevice)` records
  `most_at_once`; `_Holding(_Counting)` blocks the write on a `threading.Event`. Five
  presses → 2 writes, `most_at_once == 1`, log holds sent values only; `+`/`-` net value;
  a gate locked mid-burst (via `_Holding`) refuses the next write; a nudge on another cell
  is `"busy"`.
- `TestASoundIsWrittenTogether` — three fields, one change entry, one undo.
- `TestUndoSendsThePreviousDumpBack` — the frame carries the previous value back and other
  channels unchanged (`_other_channels_unchanged`); a `Once(DemoDevice)` taking only the
  first dump is reported as rejected and leaves the timeline empty; `z` on `MultiScreen`.
- `TestOneTimelineOverBothKinds` — newest-first across kinds both orders; `Z` takes both;
  the sentence names the kind; `HalfAwake(DemoDevice)` refuses one restore and the batch
  carries on.
- `TestTheDumpFrameOnTheWire` — `ProteusBridge` with fake `_Out`/`_In` rtmidi clients;
  one `send_message` call; >500 bytes; device ID = 7; command is `SETUP_DUMP`, not edits.
- `TestTheScreenHasAWayToSayIt` — `Row(MultiScreen)` overrides `say`/`channel_result`/
  `channel_undone` to capture the seams; app's `#status` written either way.

### 8.3 `tests/test_multi_edits.py`

The UI-level twin of §8.2. Uses a `Row`-free real `MultiScreen` opened by `_open_multi`,
and `_Held(DemoDevice)` (`test_multi_edits.py:757-799`) which blocks the write on
`threading.Event` so a burst window is real, then calls the real fake so the read-back
verifies.

Classes: `TestTheTableMovesBetweenCells` (cell cursor; every column has a distinct kind
from `CELLS`); `TestEnterOnANumericCell` (PromptScreen; range/value in question; word
refusal; out-of-range; locked gate inside modal); `TestEnterOnANamedCell`
(`ValuePickerScreen` with `MIX_OUTPUT_NAMES`/`ARP_NAMES`, picked value is the one it is
numbered by); `TestTheGestures` (`+`/`=`/`-` clamped, `space` toggles, digits type in
place, locked gate refuses every gesture); `TestABurstOfNudgesOnOneCell` (row moves with
keys; 2 writes for 5 presses; `most_at_once == 1`; another cell busy;
`test_a_write_the_unit_ignores_puts_the_row_back`); `TestPickASoundForTheChannel`
(`s` and enter-on-`plays` open the picker; `rom_id` labelled; three fields one change;
`bank_map` carried over); `TestWhatTheScreenSaysAndShows` (refusal inside modal, verified
write drawn, failed write leaves row, undo tells screen, sound redraws three columns,
master answer said from this screen, no master rows to redraw); `TestWhatTheScreenDeclares`
(footer names keys, report text, legend declares the keys, screen binds them).

### 8.4 `tests/test_backup.py`

- `TestTheEnvelope` — a real dump round-trips (encode→save→load→encode equal, and the
  saved field equals the saved time not a later edit); never overwrites; default dir under
  `data_dir()`/`backups`; corrupt file listed with `error`; missing dir → `[]`; a dir entry
  skipped; full-path load; `load` refuses a non-frame block, a non-setup kind, a missing
  block (built with `vinsynlib.backup.save` directly).
- `TestTheAutomaticBackup` — first write takes exactly one restore point and says
  `backed up the setup as ...`; the saved dump holds the pre-write value (127) while the
  unit now holds 90; a second edit does not back up again; a locked/refused write takes no
  backup; a monkeypatched `bk.save_setup` raising is announced as a refusal and the write
  still goes out.
- `TestTheBackupDirectoryFlag` — parser default and `--backup-dir`; `app.backup_dir()`
  prefers the given dir.
- `TestTheCliBackupCommands` — drives `cli.main(...)`: `list` opens no port (monkeypatched
  `_build_device` explodes); `save` then `list`; corrupt file reported; `--json`; `restore`
  without `--yes` raises `SystemExit` naming `--yes`; `restore --yes` with a
  monkeypatched `_build_device` adopts the dump; a restore is one `SETUP_DUMP` frame in
  `device.received`.
- `test_the_demo_device_id_is_the_one_the_backup_records` guards the fake's ID.

### 8.5 `tests/test_no_sound.py`

Fakes the transport rather than a device: `_RecordingOut` records `send_message`;
`_SilentIn` never answers. `bridge()` builds a real `ProteusBridge(_SilentIn(),
_RecordingOut(), device_id=0, timeout=0.01)` (`test_no_sound.py:95-103`). Properties:
every read emits only `0xF0` SysEx and no Channel Voice (`_voice_status`, lines 87-92);
`select()` is the only code emitting Channel Voice, with the byte order asserted
(`[0xB0,0x00,msb], [0xB0,0x20,lsb], [0xC0,pc]`, lines 193-197) and the channel in the
status byte; a bad channel is refused before any bytes; and a structural `ast` scan of
`p2k/bridge.py` asserts no `send_message` outside `select()` sends literal Channel Voice
(lines 221-254).

### 8.6 `tests/test_audit_fixes.py`

Mostly non-write-path audit items. The write-path-relevant one is
`TestUnfavouritingKeepsWhatTheUserTyped` (lines 47-118): `f` must be a `toggle`, not a
delete+add, so a rating/tags/note/date survive — this is exactly why the undo calls
`Favorites.toggle` (`app.py:1553-1568`) and `set_rating` rather than re-running the key.
The rest cover channel keys clamping without MIDI, `enter` meaning the focused row,
catalog disagreement markers, wildcard literals, silence-as-exception in both devices,
one bad catalog row, and bool-not-a-number config loaders. Fixtures are invented;
`store` is a real `Favorites` in `tmp_path`.

### 8.7 How the tests fake the device (`p2ked/demo.py`)

`DemoDevice` is written from the specification, not from `p2k.bridge`, and builds real
frames through `p2k.messages` (docstring `demo.py:16-34`). State it exposes to tests:

- `parameters: Dict[int, int]` initialised from `MASTER_VALUES` — the read-back memory,
  so a write is observable (`demo.py:138-145`, 244-269).
- `set_log: List[Tuple[int,int]]` — every `set_parameter`.
- `copy_log: List[Tuple[int,int]]` — every `copy_master_setup`.
- `dump_log: List[m.SetupDump]` and `_dump_frame` — `send_setup_dump` **replaces** the
  frame `read_setup` answers, so a read-back after a whole-setup write is real
  (`demo.py:154-163`, 525-546).
- `received: List[bytes]` — every frame, so a test can see a dump write vs a parameter
  edit.
- `handle(frame)` funnels everything through encode/parse (`demo.py:176-211`).
- `set_parameter` records but does **not** verify (matching the bridge), and a fake that
  *refused* a locked edit would let the gate look exercised when it was not
  (`demo.py:464-491`).
- `send_setup_dump` encodes with the real `m.encode_setup_dump` and keeps the frame, "a
  fake that recorded a whole-setup write and carried on answering its own original dump
  would make every read-back agree" (`demo.py:525-546`).

Specialised fakes in the tests subclass `DemoDevice` and override one method:
`Broken` (raise), `Deaf` (handle-but-don't-record), `HalfRead`/`HalfAwake`/`Once`
(dump-write behaviour), `_Counting`/`_Holding`/`_Held` (in-flight counting + event
gating), `WireReading` (reads on the wire).

---

## 9. The shape a port follows (condensed)

1. **Two tables, one lookup.** A frozen record (`parameter_id, label, low, high,
   choices, note, base`) + a `MASTER_BY_ID`-style merged dict that is the single gate the
   send path checks. Adding/removing a row changes what is offerable and sendable with
   nothing else to edit.
2. **A pure editor object.** Gate + log(s) + range checks + report sentences, no I/O:
   `allow`, `finish(verify)`, `undo_plan`, `undo_report`, and a per-channel twin
   `allow_channel_*`, `decline_channel(dump)`, `finish_channel`, `channel_undo_plan`.
3. **A boolean gate, locked by default, armed by one key and one startup flag**, with the
   refusal sentence naming the key/flag. The check always precedes the range check.
4. **Read-write-read on one worker under one lock.** The app — not the bridge — owns the
   verify. `_busy` is the single-writer claim; a write that read back differently is
   *not* logged, so it is not undoable.
5. **Two write routes through one gate/log:** an ID+value edit and a whole-record write
   built by a pure `mutate_*` that changes exactly one field and is byte-exact elsewhere.
6. **One shared timeline** (the library's `UndoLog`) holding per-kind payloads; `z`
   consults the log's plan (gate_hook = busy), local kinds are undone with no wire, wired
   kinds go to a worker that sends the *previous* value / previous field, newest-first.
7. **One restore point per session**, taken from the pre-write dump inside the worker
   before the send; failure is announced and does not block the write.
8. **Burst coalescing**: one in-flight cell, a single target slot, a loop that sends the
   newest target after a verified write; one timeline entry per value the unit received.
9. **Tests fake the transport**, not the device: record sends, control whether a write
   lands, and assert on the absence of a write (log/dump_log/received empty) rather than
   on the sentence; `threading.Event` holds a write in flight to make the burst window
   deterministic.
