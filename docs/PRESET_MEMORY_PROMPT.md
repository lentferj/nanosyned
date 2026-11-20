<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Content-addressed preset memory — implementation prompt

**Read this file first. It is both the specification and the orchestration
prompt.** The coordinating agent is the only writer of commits; every
implementation task is one fresh subagent session on the model named in the
task table.

This feature is independent of the init/append plan in
`docs/EXPORT_INIT_APPEND_PLAN.md`, but it is designed so init can later
unbind a slot without losing the memory. Do **not** implement init or
append here.

---

## Kickoff (paste this into the orchestrator session)

> You are implementing content-addressed preset memory for the repository at
> `/home/lentferj/git-repos/nanosyned`.
>
> **Branch:** create `preset-memory` from the current branch
> (`import-parity`) after confirming the worktree is clean. If
> `git status --short` is not empty, stop and ask the user; do not stash,
> commit or carry unrelated work onto the new branch. Never work on
> `master`.
>
> **Python:** every command uses `.venv/bin/python -m …`. The last known
> full-suite baseline on this worktree is **752 passed, 8 skipped**; re-run
> it after branching and never go below it. Tests need
> `-o addopts=""` because the configured coverage plugin is unavailable in
> the ambient interpreter.
>
> **Execution shape:** one task card = one subagent, fresh context. Use the
> `subagent` tool with `agent: "general"`, the model named in the task
> table, and the per-task prompt template below. Do not batch two cards
> into one subagent. Do not let a subagent commit, push, switch branches,
> create worktrees, or edit outside its allowed files.
>
> **You are the reviewer and the only committer.** Read the diff, run the
> task's verification yourself, then commit with the message in the table.
> If a task fails twice, stop and report; do not weaken a test.
>
> **Hardware and write permission.** No subagent opens a MIDI port. The
> user bank is a scratch area: full permission is granted to write,
> overwrite, init/clear, restore and otherwise exercise User `000`–`126`.
> The human/orchestrator does not need to ask for each User-bank write.
> User `127` remains hardwired and is never written. “Free to write” removes
> the permission question, not the safety fence: gate, destination read,
> backup, read-back verification and undo still apply. The test suite uses
> the demo device and synthetic records.
>
> **Stop conditions:** dirty worktree before branching; a task needs a file
> outside its allowlist; the design would put mutable memory in
> `catalog.json` or change `vinsynlib`'s favourites schema; a safety
> invariant would be weakened; the full suite drops below baseline; or a
> subagent wants to write real bank data into the repository.

---

## 0. Goal

Remember a program by its **content**, not by the slot it happens to occupy.
When a bank or a single preset is loaded later from any `.syx`/`.sqs` file,
the app computes the 350-byte program record's SHA-256, looks it up in the
memory, and — if the memory says that content was favourited — restores the
heart and its annotations on the destination slot.

The user-facing summary is:

> “I have seen this preset before. It was a favourite. Mark it again.”

This is not the same as the existing slot-keyed favourites database. The
existing database remains the UI's slot/occurrence layer. The new memory is
the content-identity layer.

## 1. Hard design contract

These decisions are not open for subagent improvisation.

### 1.1 Where the memory lives

- **Do not put it in `nano/data/catalog.json`.** The catalog is generated,
  disposable name data (printed names plus live names). The user's
  annotations are not catalog data and must not be lost when the catalog is
  regenerated.
- **Do not change `vinsynlib.favorites`' schema.** The favourites database
  is shared by the family; this feature is nanosyned-only for now.
- Use a new sidecar SQLite database, `preset-memory.db`, beside
  `favorites.db` in `nano.favorites.data_dir()`.
- The sidecar is authoritative for content identity and annotations.
  `favorites.db` remains authoritative for which slots currently display a
  heart.
- The sidecar path is injectable through
  `--preset-memory PATH` and the app constructor, so tests never touch the
  user's real data.

### 1.2 What is hashed

- Hash the canonical **350-byte unpacked program record**:
  `bytes(record[:records.PROGRAM_BYTES])` after
  `records.check_size(record, PROGRAM_BYTES, "a program")`.
- Use **SHA-256** (`hashlib.sha256(...).hexdigest()`), lower-case, 64 hex
  characters. Do not use MD5 or SHA-1; they are unnecessary here and both
  have known collision attacks.
- Version 1 hashes the **full record**, including the ten-character name.
  Renaming a preset therefore creates a new identity. That limitation is
  deliberate and documented; a name-insensitive “same sound” hash is out of
  scope for this branch.
- Effects, mixes and global records are not part of a program's identity.
  The hash identifies the program record only. A different effect patch can
  change the sound without changing the program hash; document that
  limitation.

### 1.3 Identity vs occurrence

- `preset_memory.favourite` is **content-level**. It answers “was this
  preset content favourited?”.
- A row in `favorites.db` is an **occurrence**. It answers “does this slot
  currently show a heart?”.
- When a favourite is toggled on a slot whose digest is known, the content
  flag changes and the app updates every bound slot for that digest. If the
  same content is in two slots, one `f` off clears both. This is deliberate;
  tests pin it.
- If the digest is unknown (old slot-only favourite, no record read yet),
  keep the current slot behaviour and do **not** write the memory. The next
  time that record is seen, lazy adoption (M7) binds it.
- The memory survives a slot being overwritten or cleared. Init later may
  unbind slots, but must not delete `preset_memory` rows.

### 1.4 Import vs manual edit

- **Import / send / restore:** the incoming content is the identity. If the
  memory says it is a favourite, mark the destination; if not, remove any
  old active mark on that destination. Do not transfer the old slot's
  favourite state to a different imported preset.
- **Manual program store of an edited favourite:** carry the old annotations
  to the new digest. The user edited their favourite; the edited version is
  also a favourite. The old digest remains in memory as seen (and remains
  favourite, because it was), so loading the old version later still marks
  it.
- **Manual store of a non-favourite:** remember the new content, but do not
  invent a favourite flag.

### 1.5 Seen vs favourite

- Every verified program is `remember`ed as seen.
- `favourite` starts false unless adopted from an existing active slot
  favourite or set by `f`.
- Version 1 UI only consumes the memory to restore hearts. A “seen before”
  badge for non-favourites is out of scope; the data is there for a later
  task.

### 1.6 Write permission

- The User bank `000`–`126` is a scratch area for this branch. Full
  permission is granted to write, overwrite, init/clear, restore, and use
  any of those slots for verification.
- No extra “may I write this slot?” confirmation is needed beyond the
  existing gate and the feature's own confirmations.
- User `127` is hardwired silent and is never a write destination.
- The safety fence is unchanged: read the destination, back it up, store,
  read back, and only claim success when the read-back agrees. “Free to
  write” is permission, not a reason to skip verification.
- A hardware run must still leave the bank in a known state and name its
  backups in the report.

### 1.7 Out of scope

- Name-insensitive / “same sound” hashing.
- Cross-unit sound identity, firmware differences, or hashing effects/global
  records.
- ROM-bank content identity (only the User bank's records are readable).
- A new browser key or a new screen.
- Init/append implementation.
- Automatic full-bank hashing at startup. Startup reads names, not records;
  hashing happens when a record is actually seen.
- Migrating the shared favourites schema.

## 2. Data model

`nano/preset_memory.py` owns the sidecar. Schema version 1:

```sql
CREATE TABLE IF NOT EXISTS preset_memory (
    digest      TEXT PRIMARY KEY,   -- lower-case SHA-256, 64 hex chars
    name        TEXT NOT NULL DEFAULT '',
    favourite   INTEGER NOT NULL DEFAULT 0,
    rating      INTEGER NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL DEFAULT 0,
    last_seen   REAL NOT NULL DEFAULT 0,
    seen_count  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS slot_content (
    bank_id     TEXT NOT NULL,
    number      INTEGER NOT NULL,
    digest      TEXT NOT NULL,
    updated_at  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (bank_id, number)
);

CREATE INDEX IF NOT EXISTS slot_content_digest
    ON slot_content (digest);
```

Rules:

- `bank_id` is `"USER"`; `number` is `000`–`126`. `127` is rejected.
- `remember(record, name=None)` is an upsert. It updates `name` when a
  non-empty name is supplied, `last_seen`, and `seen_count`; it preserves
  `favourite`, `rating`, `tags` and `note`. A new row starts unseen except
  for `seen_count = 1`.
- `set_favourite(digest, value, *, rating=None, tags=None, note=None)`
  requires an existing row; it never invents content. It updates only the
  arguments that are supplied.
- `bind_slot(bank_id, number, digest)` requires the digest to exist.
- The store is thread-safe: one connection with
  `check_same_thread=False`, an `RLock` around each statement, WAL mode.
  The app's main thread and import worker both reach it.
- A newer `user_version` is refused rather than guessed at.
- `close()` commits and closes; the class is a context manager.

## 3. API contract

`nano/identity.py`:

```python
def canonical(record: bytes) -> bytes: ...
def digest(record: bytes) -> str: ...
def program_name(record: bytes) -> str: ...
```

`nano/preset_memory.py`:

```python
@dataclass(frozen=True)
class MemoryEntry:
    digest: str
    name: str
    favourite: bool
    rating: int
    tags: str
    note: str
    first_seen: float
    last_seen: float
    seen_count: int


class PresetMemory:
    MEMORY_NAME: ClassVar[str]

    def __init__(self, path: str | None = None) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> PresetMemory: ...
    def __exit__(self, *exc: object) -> None: ...
    def remember(self, record: bytes, *, name: str | None = None) -> MemoryEntry: ...
    def get(self, digest: str) -> MemoryEntry | None: ...
    def set_favourite(
        self,
        digest: str,
        favourite: bool,
        *,
        rating: int | None = None,
        tags: str | None = None,
        note: str | None = None,
    ) -> MemoryEntry: ...
    def favourites(self) -> list[MemoryEntry]: ...
    def seen(self) -> list[MemoryEntry]: ...
    def bind_slot(self, bank_id: str, number: int, digest: str) -> None: ...
    def slot_digest(self, bank_id: str, number: int) -> str | None: ...
    def slots_for(self, digest: str) -> list[tuple[str, int]]: ...
    def forget_slot(self, bank_id: str, number: int) -> None: ...


def default_path() -> str: ...
```

`nano/favorites.py` adds only the path binding:

```python
MEMORY_NAME = "preset-memory.db"


def memory_path() -> str: ...
```

`default_path()` in `preset_memory.py` uses
`nano.favorites.data_dir()` plus `MEMORY_NAME`.

## 4. Model assignment

Model names are exact `provider/model` IDs; `#variant` is the reasoning
level. If the harness rejects a variant, use the same ID without the
variant and note it. If the named model is unavailable or quota-exhausted,
fall back in this order and record which one was used:

1. the model named in the task row;
2. `opencode/deepseek-v4.1-flash-free#high`;
3. `opencode/flint-40b-free#high`;
4. `opencode/beam-free#high`.

Do not use `openrouter/openrouter/free` (the router is nondeterministic).
Do not use a vision model unless a task genuinely needs an image.

| Task | Work shape | Model | Why this one |
|---|---|---|---|
| M1 | Byte-exact canonicalisation and SHA-256 | `opencode/deepseek-v4.1-flash-free#high` | Exact record-size and bit-level work; low tolerance for invention |
| M2 | SQLite schema, locking, upsert semantics | `opencode/tidepool-alpha-free#high` | Data-model and migration reasoning |
| M3 | Path/CLI/app plumbing | `opencode/flint-40b-free#high` | Mechanical code with clear seams |
| M4 | App import/store integration | `opencode/beam-free#high` | Cross-module integration and prose-quality comments |
| M5 | CLI import/send integration | `openrouter/cohere/north-mini-code:free#thinking` | Code-focused CLI task |
| M6 | Favourite toggle identity policy | `opencode/deepseek-v4.1-flash-free#high` | Edge-case semantics and duplicate handling |
| M7 | Lazy migration of old favourites | `opencode/longcat-2.5-free` | Long-context migration and compatibility |
| M8 | Adversarial tests for duplicates/renames/partials | `opencode/mimo-v2.6-flash-free` | Code/reasoning test construction |
| M9 | README and resolution-note prose | `opencode/beam-free#high` | Documentation and precise limitations |
| M10 | Final review | `opencode/tidepool-alpha-free#max` | Strongest overall review pass |

## 5. Task order, dependencies and commits

Bold rows are serialisation points. M1 and M2 may run in parallel; M4 and M5
may run in parallel after M3. M6 and M7 both touch `nanosyned/app.py` and
must not overlap.

| # | Task | Depends | Subagent model | Commit after review |
|---|---|---|---|---|
| 1 | **M1** identity digest | — | `opencode/deepseek-v4.1-flash-free#high` | `feat(memory): hash program records with sha-256` |
| 2 | **M2** memory store | — | `opencode/tidepool-alpha-free#high` | `feat(memory): store seen presets in a sidecar database` |
| 3 | **M3** path and wiring | M2 | `opencode/flint-40b-free#high` | `feat(memory): wire preset memory through cli and app` |
| 4 | **M4** app import/store hook | M1, M2, M3 | `opencode/beam-free#high` | `feat(memory): remember verified imports and manual stores` |
| 5 | M5 CLI import/send hook | M1, M2, M3 | `openrouter/cohere/north-mini-code:free#thinking` | `feat(cli): remember imported and sent programs` |
| 6 | **M6** favourite toggle policy | M4 | `opencode/deepseek-v4.1-flash-free#high` | `feat(memory): make favourite toggles content-aware` |
| 7 | M7 lazy adoption | M6 | `opencode/longcat-2.5-free` | `feat(memory): adopt existing slot favourites lazily` |
| 8 | M8 adversarial tests | M4–M7 | `opencode/mimo-v2.6-flash-free` | `test(memory): pin duplicates, renames and partial imports` |
| 9 | M9 docs and limitations | M4–M8 | `opencode/beam-free#high` | `docs: describe content-addressed preset memory` |
| 10 | **M10** review and full suite | M1–M9 | `opencode/tidepool-alpha-free#max` | `chore: preset memory review` |

Waves:

- **W0** M1–M3 — pure code and wiring.
- **W1** M4–M5 — import/store and CLI.
- **W2** M6–M7 — toggle and migration.
- **W3** M8–M9 — adversarial tests and docs.
- **W4** M10 — review.

Do not start a new wave until the previous wave's full suite is green and
the diffs have been read.

## 6. Task cards

### M1 — identity digest

**Allowed files:** `nano/identity.py` (new), `tests/test_identity.py` (new).

**Do:**

- Implement `canonical`, `digest`, `program_name` exactly as in §3.
- `canonical` checks size with `records.check_size(record,
  PROGRAM_BYTES, "a program")` and returns exactly the first 350 bytes.
- `digest` returns `hashlib.sha256(canonical(record)).hexdigest()`.
- `program_name` returns `records.program_name(record).rstrip()`.
- No name-insensitive hash; no third-party hash; no catalog change.

**Tests:**

- A pinned SHA-256 for one synthetic 350-byte record (compute it once and
  assert the exact hex string).
- Same bytes -> same digest; one changed parameter byte -> different digest;
  changed name -> different digest.
- A record longer than 350 bytes is truncated to 350 before hashing.
- A short record raises `ProtocolError`.
- Digest is 64 lower-case hex characters.

**Acceptance:** no vinsynlib edit, no catalog edit, no hardware.

---

### M2 — preset memory store

**Allowed files:** `nano/preset_memory.py` (new),
`tests/test_preset_memory.py` (new).

**Do:**

- Implement the schema, `MemoryEntry`, `PresetMemory`, `default_path`, and
  `MEMORY_NAME` from §2–§3.
- Use standard-library `sqlite3`, `threading.RLock`, `check_same_thread=False`,
  `PRAGMA journal_mode=WAL`, and `PRAGMA user_version`.
- `remember` is an upsert that preserves annotations and increments
  `seen_count`; `first_seen` is set only once.
- `set_favourite` requires an existing digest and validates rating `0..5`.
- `bind_slot` requires an existing digest and rejects `USER:127` and any
  bank other than `USER`.
- `favourites()` and `seen()` return deterministic sorted lists.
- Do not import `vinsynlib.favorites` internals; path binding may use
  `nano.favorites.data_dir()`.

**Tests:**

- Create, close, reopen; rows persist.
- New remember starts `favourite=False`, `seen_count=1`; second remember
  increments and updates `last_seen`; annotations are preserved.
- `set_favourite` true/false keeps annotations; rating out of range raises.
- `bind_slot` then `slot_digest` and `slots_for`; `forget_slot`.
- `USER:127`, `P1:0`, `-1`, `128` refused.
- Newer `user_version` refused.
- Context manager closes.
- Two threads can remember/bind without a SQLite exception.

**Acceptance:** no shared schema change; no real user path in tests.

---

### M3 — path and wiring

**Allowed files:** `nano/favorites.py`, `nanosyned/cli.py`,
`nanosyned/app.py`, `tests/test_memory_paths.py` (new).

**Do:**

- Add `MEMORY_NAME = "preset-memory.db"` and `memory_path()` to
  `nano/favorites.py`.
- Add a global `--preset-memory PATH` to `nanocli` and re-declare it for
  `import` and `send` via the existing `_inherit` helper, so it works
  before and after the subcommand.
- Add `memory_path: str | None = None` to `NanosynedApp.__init__`; when
  supplied, open `PresetMemory(memory_path)` and keep it on `self`; when
  `None`, no memory is opened (tests and embedders).
- In the app's `main`, pass `preset_memory.default_path()`.
- Do not open the default memory in tests; every test that needs it passes
  a `tmp_path`.
- No new key, no new screen.

**Tests:**

- `memory_path()` ends with `preset-memory.db` and sits in the app's data
  directory.
- CLI parses `--preset-memory` before and after `import`/`send`.
- App with `memory_path=tmp` has a live memory; app with `None` does not.
- No test creates a file in the real home data directory.

**Acceptance:** no CLI behaviour change beyond the new path; no catalog
write.

---

### M4 — app import and manual-store hook

**Allowed files:** `nanosyned/app.py`, `tests/test_app.py` or
`tests/test_memory_app.py` (new).

**Do:**

- Add one private helper on the app:
  `_remember_program(bank_id, number, record, *, manual: bool)`.
  It must do the §1.3/§1.4 work:
  - `entry = self.memory.remember(record, name=...)`
  - `self.memory.bind_slot("USER", number, entry.digest)`
  - if `entry.favourite`: ensure `self.favorites.add("USER", number,
    name=..., rating=..., tags=..., note=...)` is active.
  - if not favourite: `self.favorites.remove("USER", number)` (dormant, not
    `forget`).
- Hook `_import_done`: for every result with `stage == "verified"` and
  `kind == "program"` and a number, call the helper with `manual=False`.
  Do this before the final status line; include a short “remembered N;
  re-marked M” suffix.
- Hook `_store_done` for a verified manual program store:
  compute the old digest from `previous`, see whether the slot was an
  active favourite, and if so carry its annotations to the new digest
  (`manual=True`). Remember/bind the new content regardless.
- Do not touch init; it does not exist in this branch.
- Do not update the catalog for this feature.
- Refresh favourite counts/views after re-marking (reuse the existing
  refresh path).

**Tests:**

- Import a verified program whose digest is a remembered favourite: target
  slot is active and shows the memory rating/tags/note.
- Import a non-favourite over an active favourite slot: the old mark is
  removed, the new content is remembered as seen.
- Partial/cancelled import: only verified results are remembered.
- Manual edit of a favourite slot: new digest is favourite with the old
  annotations; old digest remains in memory.
- Manual edit of a non-favourite: new digest is seen, not favourite.
- No memory injected: existing behaviour unchanged.
- No `catalog.json` writes.

**Acceptance:** only verified writes affect memory; no hardware.

---

### M5 — CLI import and send hook

**Allowed files:** `nanosyned/cli.py`,
`tests/test_cli_memory.py` (new).

**Do:**

- Open `PresetMemory(args.preset_memory or default_path())` for `import`
  and `send` only when the command will actually write (not `--list`,
  not `--dry-run`).
- Collect verified `writing.Result`s from `_import_write` and `send`'s
  run. For each `kind == "program"` with a number:
  - remember and bind;
  - if the memory says favourite, open the favourites store (the existing
    `_favorites(args)` helper) and activate the slot with the memory
    annotations;
  - if not favourite, `remove` any old active slot mark.
- Close both stores in `finally`.
- Do not remember a dry-run, a list, a failed read, or a failed verify.
- Print a short note only if something was actually re-marked; do not
  change the existing write lines.

**Tests:**

- `nanocli import` with `--preset-memory tmp` remembers a verified program.
- Pre-seeded favourite digest -> destination is re-marked.
- `--dry-run` leaves the memory file untouched/empty.
- Failed verify/read does not remember.
- `--preset-memory` works before and after the subcommand.
- No test touches the real user database.

**Acceptance:** exit codes and gate rules unchanged.

---

### M6 — favourite toggle identity policy

**Allowed files:** `nanosyned/app.py`,
`tests/test_memory_favourites.py` (new) or `tests/test_app.py`.

**Do:**

- In `action_toggle_favorite`, resolve the slot digest from
  `self.memory.slot_digest("USER", number)` if memory exists.
- If the digest is known:
  - toggling on updates the memory entry's `favourite=True` and copies the
    slot's `name`, `rating`, `tags`, `note` into the memory (only when the
    slot row actually carries annotations; do not erase memory annotations
    with blanks).
  - toggling off sets `favourite=False` and deactivates every active slot
    occurrence for that digest via `memory.slots_for` + `favorites.remove`.
  - the current slot's `f` result and the memory must agree.
- If the digest is unknown: keep today's slot-only behaviour and write
  nothing to the memory.
- Preserve the existing `notify_status` wording where possible; add a
  single note if a duplicate slot was also unmarked.
- No schema change to `favorites.db`.

**Tests:**

- Known digest, one slot: on/off; annotations round-trip.
- Known digest, two bound slots: one `f` off clears both; one `f` on marks
  both? If marking all active occurrences is impractical, mark the current
  slot and leave the other occurrence to the next import. State the chosen
  behaviour in the task report and pin it with a test. The contract is:
  the **content flag** is authoritative; the current slot must agree.
- Unknown digest: old behaviour and no memory row.
- `USER:127` never gets a memory binding.

**Acceptance:** no shared favourites schema change.

---

### M7 — lazy adoption of existing favourites

**Allowed files:** `nanosyned/app.py`, `nano/preset_memory.py` (only if a
small helper is needed), tests in `tests/test_memory_migration.py` (new).

**Do:**

- When a record is remembered for a slot and the slot has an active
  favourite row, adopt that row's `name`, `rating`, `tags`, `note` into a
  memory entry whose annotations are empty. If the memory already has
  annotations, keep the memory's values.
- Bind the slot to the digest.
- If two active slot favourites hash to the same new content, choose the
  earliest `added` row's annotations; do not silently concatenate notes or
  merge tags. Record the conflict in the task report; a test pins the
  deterministic choice.
- This is lazy: do not read the whole User bank at startup. It happens the
  first time a record is seen (import, manual store, preview, or any future
  read path).
- Do not delete dormant rows.

**Tests:**

- Pre-seed `favorites.db` with an active slot favourite; import/remember
  the same record -> memory favourite with the row's annotations.
- Existing memory annotations win over a different slot row.
- Two old rows with the same digest -> deterministic earliest-added
  annotations.
- Dormant row alone does not make content favourite.
- No startup MIDI reads.

**Acceptance:** old slot favourites migrate without data loss and without
a full-bank scan.

---

### M8 — adversarial tests

**Allowed files:** tests only, preferably
`tests/test_memory_edges.py` (new). Do not edit production files.

**Do:** write tests for the failure modes the happy path can hide:

- duplicate content in two slots, favourite toggled on/off;
- same bytes with a changed name -> different digest and no false match;
- same name with changed bytes -> different digest;
- import partial/cancel/failed verify;
- old active slot favourite over an imported non-favourite;
- dormant row not adopted;
- `USER:127` refusal;
- memory path persistence across app restart;
- no `catalog.json` writes;
- no real home data touched.

If a test exposes a production bug, **stop and report** the failing test and
the smallest suggested fix. Do not edit production files outside the
allowlist.

**Acceptance:** tests pass, or the report names the bug and no production
file was changed.

---

### M9 — docs and limitations

**Allowed files:** `README.md`, `docs/RESOLUTION_NOTES.md` (and this prompt
only if a factual correction is required).

**Do:**

- Add a “Preset memory” section to `README.md`: what is hashed, where the
  sidecar lives, how favourites return on import, the identity-vs-slot
  distinction, duplicate behaviour, and the limitations.
- Add a resolution note with the same facts and the reason the catalog is
  not the home for mutable memory.
- State clearly:
  - full-record SHA-256; renaming creates a new identity;
  - program-only identity, not effects/global sound identity;
  - no startup full-bank scan;
  - existing favourites migrate lazily;
  - `preset-memory.db` can be backed up with `favorites.db`.
- Do not claim hardware verification that did not happen.

**Acceptance:** docs match the implementation; no code changes.

---

### M10 — review

**Allowed files:** none; review only.

**Do:**

- Read every diff, run `make lint typecheck` and the full suite:
  `.venv/bin/python -m pytest -o addopts="" -q`.
- Check no `catalog.json` or `vinsynlib` schema edits; no real bank data;
  no subagent hardware; no new dependency; no test writing to the real
  home data directory. The orchestrator/human may run the opt-in §10
  hardware checks, including User-bank writes and inits, under the
  permission granted there.
- Run the demo import end to end with a synthetic favourite and confirm the
  heart returns.
- If a fix is needed, report it as a new task; do not edit code in M10.
- Record the final counts and any model fallbacks used.

**Acceptance:** full suite at or above baseline; every task committed; no
unreviewed file.

## 7. Per-task subagent prompt template

Send exactly this shape; do not paraphrase allowed files or constraints.

```text
GOAL
Implement task {TASK} from /home/lentferj/git-repos/nanosyned/docs/PRESET_MEMORY_PROMPT.md
(§6, the card titled "{TITLE}").

CONTEXT
- Repository: /home/lentferj/git-repos/nanosyned
- Branch: preset-memory (already checked out; do NOT switch or create)
- Python: .venv/bin/python
- Read first: docs/PRESET_MEMORY_PROMPT.md §§1–3 and task card §6/{TASK};
  then the existing files named below.
- The design contract in §§1–3 is not negotiable.
- Baseline suite: at least 752 passed, 8 skipped. Do not weaken a test.

ALLOWED FILES (edit only these)
{FILES}

WHAT TO DO
{STEPS}

CONSTRAINTS
- Standard library only; no new dependency.
- Keep line length 88; match the surrounding tone and docstring style.
- No hardware in this subagent session: no MIDI port, no
  `make test-hardware`. The orchestrator/human may run the opt-in §10
  checks outside this session.
- No commit, no push, no branch change, no worktree.
- Do not edit a file outside ALLOWED FILES. If you need one, stop and say why.
- Do not put memory data in catalog.json.
- Every unit-derived string goes through nanosyned.text.literal() before
  Textual markup.
- Use synthetic 350-byte records in tests; never commit real bank data.

VERIFY (run all; paste the exact output)
{VERIFY}

ACCEPTANCE
{ACCEPT}

OUTPUT
- What changed and why, one paragraph per file.
- Exact verification commands and final lines.
- Anything deliberately not done.
- Model actually used, if it differed from the assigned one.
- Do not commit.
```

## 8. Wave gates

After every task, the orchestrator runs on touched files:

```sh
.venv/bin/python -m ruff check <touched files>
.venv/bin/python -m ruff format --check <touched files>
.venv/bin/python -m mypy
```

After every wave (W0–W4), additionally:

```sh
.venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider
```

and one demo smoke test. Do not start the next wave until both are green
and the diff has been read.

## 9. Commit protocol

- The orchestrator commits; subagents never do.
- One commit per task, message from §5; add a short body explaining the
  user-visible behaviour.
- Re-run the task's tests after any review fix; the commit contains only
  that task's files.
- Never commit a fixture containing real bank data from
  `~/Dokumente/SYNTHS/Nanosynth/` or a real `favorites.db` /
  `preset-memory.db`.
- Keep the worktree clean between tasks so a bad task can be dropped.

## 10. Hardware protocol — full User-bank write rights

- No subagent opens a MIDI port. The orchestrator/human may run the hardware
  checks below.
- **Permission is granted in advance** to write, overwrite, init/clear,
  restore and otherwise exercise User `000`–`126`. Do not stop to ask for
  each User-bank write. The bank is treated as scratch space for this
  feature.
- **User `127` is never written.** It remains hardwired silent.
- The existing fence still applies to every write: gate, destination read,
  backup, store, read-back, and an honest report. “Free to write” is not a
  reason to skip verification.
- The hardware run is not part of `make check`; it is an opt-in check after
  the full suite is green.

### 10.1 Digest stability (read-only)

1. Read one User preset twice with a normal read.
2. Compare the two 350-byte records.
3. If they differ, stop: the full-record hash is not stable on this unit,
   and a canonicalisation decision is needed before shipping.
4. If they agree, record the unit identity/firmware and the digest in
   `docs/RESOLUTION_NOTES.md`.

### 10.2 Favourite round-trip (writes allowed)

This is the check that proves the feature, not just the SQLite code.

1. Choose a scratch User slot `000`–`126`; back it up first.
2. Put a known preset in it; favourite it; confirm the memory row now has
   that digest with `favourite=1` and its annotations.
3. Overwrite that slot, or init/clear the User bank if the init feature is
   present, so the slot no longer holds the same content.
4. Re-import or restore the original preset from its file.
5. Confirm the heart returns and the rating/tags/note are restored from
   the memory, not from the slot's old row.
6. Confirm `127` was never written and name the backup paths in the run
   report.
7. Leave the User bank in a known state; restoring the backup is allowed
   and does not need a further permission prompt.

### 10.3 If hardware is unavailable

Leave both checks documented and unrun. Do not mark them passed. The test
suite must still pass with the demo device.

## 11. Definition of done

- [ ] `preset-memory.db` schema and `PresetMemory` API exist and are tested.
- [ ] SHA-256 is over the canonical 350-byte program; MD5/SHA-1 absent.
- [ ] `--preset-memory` works before and after `import`/`send`.
- [ ] Imported verified programs are remembered and bound.
- [ ] A remembered favourite is re-marked on import, with annotations.
- [ ] A non-favourite import removes an old active slot mark.
- [ ] A manual edit of a favourite carries annotations to the new digest.
- [ ] Duplicate content policy is explicit and tested.
- [ ] Existing slot favourites migrate lazily; no full-bank scan.
- [ ] `catalog.json` and `vinsynlib` schema are untouched.
- [ ] No real user data in tests; every test uses `tmp_path`.
- [ ] Docs state the rename, effects/global, and no-startup-scan limits.
- [ ] Full suite at or above baseline; ruff/format/mypy green.
- [ ] Hardware digest-stability check and favourite round-trip either
      recorded or clearly unrun; no User `127` write.
- [ ] Every task committed separately; no unreviewed file.

## 12. Final note to the orchestrator

If a task's requirements conflict with the repository's existing safety
rules, the safety rules win. If the design contract and the code disagree,
stop and ask rather than silently changing the identity model. The feature
is only useful if “seen before” means the same bytes; do not paper over a
hash mismatch with a name or a slot.
