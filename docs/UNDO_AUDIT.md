# Undo audit: destructive actions and the gaps

**Status:** recorded 2026-11-22 at commit `c706467`. No fixes applied.
This is an audit and an implementation plan, not a change to behaviour.

**Scope:** actions in the TUI that replace stored unit memory, plus the
command-line writes and user data that have no browser undo. Read-only
actions, selections, live-buffer edits and file reads are in a separate
section so they are not mistaken for missing undo work.

## Short answer: the mix copy *is* logged, but it does not look undone

`C` in the Mixes pane pushes a `MixEditRecord` for the **destination**
slot. `z` does restore the destination's previous 138 bytes: the undo test
passes, and on the demo device the target bytes go back exactly.

What is missing is the visible half of the undo:

- `_undo_done()` has no branch for `MixEditRecord`, so `_mix_names[target]`
  keeps the **copied** name.
- `_rewrite()` writes the old slot bytes but does not reload buffer `100`
  when the target is the selected mix. The unit therefore keeps playing the
  copied mix, because a slot write is not a buffer load.
- `_undo_done()` refreshes only when `_current_bank == "USER"`, never the
  Mixes pane.

Result: `z` says "undid 1", the stored target is restored, but the Mixes
row still shows the copy's name and the live sound is still the copy. That
is why it reads as "not undoable" even though the bytes are safe.

The same defect applies to an ordinary **mix editor store**, not only to
`C`: it is the shared `MixEditRecord` undo path that is incomplete.

## What is recorded and what is actually restored

| Action | Stores on unit | Backup first | Undo entry | Bytes restored by `z`/`Z` | Visible state restored | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `e` → `s` program editor | User program | yes | `EditRecord` | yes | name yes; favourite mark/annotations no | partial |
| `e` → `s` mix editor | mix slot | yes | `MixEditRecord` | yes | name and live buffer no | partial |
| `C` copy mix | destination mix | yes, destination only | `MixEditRecord` | yes | name and live buffer no | partial |
| `x` → store effects | effects 000 | yes | `EffectsEditRecord` | yes | effects screen re-reads on open; no cache to refresh | bytes undoable |
| `g` → store global | global set | yes | `GlobalEditRecord` | yes | global screen re-reads on open; no cache to refresh | bytes undoable |
| `R` full restore | programs, mixes, effects, global | yes, per record | one `RestoreRecord` | yes | program names yes; mix names/live buffer no; favourite marks no | partial |
| `N` init bank | User programs 000-126 | yes, per slot | one `ImportRecord` | yes | program names yes; favourite marks/annotations no; status says so | partial |
| `I` import whole/append/single | User programs | yes, per slot | one `ImportRecord` (programs only) | yes | program names yes; favourite marks/annotations no | partial |
| `p` parameter editor | live edit buffers only (MIDI Edit) | no | none | n/a | not stored; a later store needs its own backup | not a stored write |
| Mix editor live field/name edits | buffer `100` only | no | none | n/a | not stored until `a`/`s` | not a stored write |
| `⏎` select, `a` auto-load, `M` mode select | no memory | no | none | n/a | changes what plays, not what is stored | no undo needed |
| `f`, `t`, `n`, `*` favourites | favourites SQLite | no | none | n/a | old tags/note/rating are overwritten; removal is hidden but retained | no undo |
| `B` full backup, `E` export favourites | disk file | overwrite confirm | none | n/a | file overwrite is not reversible | confirmed overwrite, no undo |
| CLI `send`, `import`, `backup restore`, `init-bank` | unit memory | per-slot backup | no interactive log | no | only manual restore from backup | no session undo |
| CLI `set` | live buffer only | no | none | n/a | not stored | not a stored write |
| `z`/`Z` itself | unit memory | no | entries are consumed | n/a | there is no redo | irreversible by design |

“Backup first” means the per-session backup file written by the store
fence. It is a recovery path, not the `z` log.

## Findings in detail

### 1. Mix undo has no presentation refresh (P0)

Affected records: `MixEditRecord`, both from the editor store and from
`C`.

Missing work:

- update the mix-name cache from the restored bytes;
- reload buffer `100` when the restored mix is the selected mix, because
  the unit does not load a slot write into its live buffer;
- refill the Mixes pane when it is visible.

The storage half is correct. Do not replace it with a new copy-specific
undo path; fix the shared mix undo path.

### 2. Full restore hides mix undo behind the batch path (P1)

`RestoreRecord` contains `MixEditRecord`s. `_undo_done()` walks nested
records but handles only `EditRecord` for names and memory. The restored
mix bytes land, but their names stay stale for the same reason as item 1.
If a restored mix is the selected mix, its live buffer is also stale.

### 3. Program undo does not restore favourite marks (P1)

`_undo_done()` restores the program name and binds the old bytes in preset
memory, but it never calls `favorites.add()` / `favorites.remove()` for the
slot.

Consequences:

- overwriting a favourite with a non-favourite and undoing leaves the slot
  unmarked;
- overwriting a non-favourite with a favourite and undoing can leave a
  favourite mark on content that is not the old bytes;
- the old annotations may survive in preset memory, but the slot's visible
  heart does not come back until something else re-binds it.

This affects the program editor, `I` import and the program part of `R`
restore. `N` init explicitly warns that `z` restores programs, not marks;
that warning is accurate today.

### 4. Import undo is intentionally program-only (P1)

The TUI import flow imports programs. `_import_done()` therefore records
only `EditRecord`s for programs. That is correct for the current screens,
but the CLI supports `--mixes`, `--effects` and `--global`; the CLI has no
session undo at all. If the TUI later exposes those flags, this branch
would silently omit their undo entries.

### 5. CLI writes have no session undo (P2)

`nanocli send`, `nanocli import` with write flags, `nanocli backup restore`,
and `nanocli init-bank` write unit memory without a `z` equivalent. They do
write per-slot backup files through the normal fence, so the recovery path
exists, but it is manual and outside the browser.

### 6. Favourite metadata edits have no undo (P2)

`t`, `n`, `*` and `f` change the favourites database directly. Unfavouriting
does not delete the row, so the annotations survive a restore of the
favourite, but overwriting tags, a note or a rating destroys the previous
value immediately. There is no confirmation and no undo.

### 7. File outputs and undo itself (P3)

- `B` and `E` offer an overwrite confirmation, then replace a file. That is
  outside the instrument and outside `z`; it is recorded here so it is not
  mistaken for an instrument write.
- `z` consumes its log entries. There is no redo, so an undo is itself an
  irreversible action. This is a deliberate simplicity choice, not an
  accident, but it is a limitation.

### 8. Undo log is session-only (P3)

The browser's undo log is not persisted. After restart, the only recovery
is the per-slot backup files or a full backup. This is not a bug in the
current contract, but it bounds what "undoable" means.

## Implementation plan

### Phase 0 — tests first, no behaviour change

Add failing tests that pin the desired contract:

1. **Copy undo is audible and visible.** Copy mix `000` to `007`, select
   `007`, press `z`; assert target bytes, `_mix_names[7]`, live buffer
   `100`, and the Mixes row name all return to the pre-copy values.
2. **Mix editor undo is the same path.** Store an edited mix, undo it, and
   assert the same four facts.
3. **Full restore undo restores mix names.** Restore a backup containing at
   least one mix, undo, and assert the mix-name cache and selected live
   buffer.
4. **Program favourite mark round-trip.** Favourite program `000`, overwrite
   it with another record, undo, and assert both bytes and the favourite
   row/annotations return.
5. **Init/import favourite mark round-trip.** Run `N` or an import over a
   favourite slot, undo, and assert the old mark returns.
6. **Undo while the affected bank is not focused.** Undo from another bank
   and verify the Mixes/User pane refreshes when it becomes visible, or at
   least that the cached names are correct.

Run them against the demo device and an in-memory `Favorites` store first.
Only the hardware opt-in test needs a real unit.

### Phase 1 — repair the mix undo path (P0)

In `nanosyned/app.py`:

- Extend the undo worker so a restored `MixEditRecord` whose number equals
  `self._selected_mix` also writes the restored bytes to buffer `100` after
  the slot write and read-back. Keep this inside the worker's
  `_busy_gate`/`_lock`; never send from `_undo_done()` on the main thread.
- Extend `_undo_done()` to update `self._mix_names[number]` from
  `rec.mix_name(edit.previous)` for every successful `MixEditRecord`,
  including records nested inside a `RestoreRecord`.
- After a successful undo that touched mixes, refresh the Mixes pane if it
  is the current bank. Reuse the same refresh point for User programs
  instead of refreshing only `"USER"`.

Do not add a copy-only branch. `C` is only one producer of
`MixEditRecord`.

### Phase 2 — refresh all affected UI after batch undo (P1)

- Collect the set of affected kinds while the undo worker runs: program,
  mix, effects, global.
- On success, reconcile caches once: program live names, mix names, selected
  mix buffer, and the current bank's rows.
- Keep failed edits on the log as today; a partial undo must not refresh
  names it did not restore.

### Phase 3 — restore favourite marks (P1)

Choose one design before coding:

**Preferred: snapshot the slot mark in the undo record.** Add an optional
favourite snapshot (active, rating, tags, note) to `EditRecord`, captured
before the write. Capture it for:

- program editor stores;
- each import/init target before its write;
- each program in a full restore before its write.

On successful undo, restore the snapshot exactly. This is independent of
the preset-memory sidecar, so it also works for users who run without it.

**Fallback: re-derive from preset memory.** After binding the old digest,
look up whether that digest is a favourite and re-add its annotations. This
is less code but loses information when memory is disabled or the entry was
not remembered.

Whichever design wins, update the `N` completion message: “z restores
programs, not marks” should disappear once marks are restored.

### Phase 4 — decide the CLI contract (P2)

The CLI already writes backups before stores. Either:

- document plainly that only the per-slot backup file is the undo path, or
- add a `nanocli undo <backup-file>` convenience that sends one backup
  through the normal verified write path.

Do not give the CLI an in-memory undo log; a process ends too soon for that
to be a useful contract.

### Phase 5 — favourites metadata (P2, optional)

For `t`, `n`, `*`, either add a confirmation for overwriting non-empty
values or add a small undo row/history in the favourites store. This is
separate from unit undo and should not be bundled into the mix fix.

### Phase 6 — redo and persistence (P3, optional)

The current log is consumed by undo and is session-only. If a redo stack is
wanted, it must be designed together with persistence and with the rule
that a failed undo keeps the original entry. Neither is required for the
mix-copy fix.

## Acceptance criteria for the P0/P1 work

- `z` after `C`, after a mix store and after a full restore restores the
  slot bytes, the visible mix name and, when selected, buffer `100`.
- `z` after a program overwrite/import/init restores the slot's previous
  favourite state as well as its bytes.
- A partial undo leaves failed entries on the log and does not refresh the
  name of a record it failed to restore.
- `make check` is green with new tests for each fixed path.
- Hardware check (optional but preferred): copy one mix, select it, undo,
  and confirm both the audible mix and the stored name revert.
