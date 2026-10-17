# vinsynlib → nanosyned API-surface audit

Scope: the current public API of `vinsynlib` (version **0.4.2**, tag `v0.4.2`,
`55e936d`), what `nanosyned` imports/uses, what it reimplements locally, and
what adoption each unused module would delete. All references are
`file:line` at the heads below.

- vinsynlib repo: `/home/lentferj/git-repos/vinsynlib`, `HEAD = 55e936d`
  (`v0.4.2`), working tree clean.
- nanosyned repo: `/home/lentferj/git-repos/nanosyned`, `HEAD = 16e3a95`,
  working tree clean.
- vinsynlib package version lives at
  `src/vinsynlib/__init__.py:59` (`__version__ = "0.4.2"`).

---

## 1. Public surface: every vinsynlib module, purpose, key names

vinsynlib is deliberately UI-free except `vinsynlib.ui.*`, and `ui/__init__.py`
imports nothing eagerly (`src/vinsynlib/ui/__init__.py:22`: "Import a module,
not this package").

| Module | File / lines | Purpose | Key public names (with line) |
|---|---|---|---|
| `vinsynlib` (top) | `__init__.py` (108 lines) | Package docstring + version gate helper | `__all__` :46; `__version__` :59; `_release_parts` :62; `is_compatible_version` :87 |
| `vinsynlib.spec` | `spec.py` | The family's CLI contract as data: flags, subcommands, exit codes | `EXIT_OK/ERROR/USAGE` :56/:60/:64; `Flag` :68; `CANONICAL_FLAGS` :117; `Subcommand` :202; `SUBCOMMANDS` :239; `SILENT_SUFFIX` :308; `flag_names` :311; `flag_help` :329; `subcommand_names` :345; `aliases_for` :350 |
| `vinsynlib.cli` | `cli.py` | Builds argparse parsers from `spec` | `make_parser` :46; `add_common_arguments` :107; `append_flag_help` :180; `validate_common` :202; `channel_of` :234 |
| `vinsynlib.config` | `config.py` | TOML settings cache + ui-state sidecar | `DEFAULT_PATH` :87; `MIDI_CHANNELS` :92; `MAX_DEVICE_ID` :98; `_Unset`/`UNSET` :152/:178; `Settings` :196; `bind` :738; `config_dir` :749; `default_config_path` :804; `config_help` :816; `MIGRATION_NOTE` :832; `migrate_legacy_config` :845 |
| `vinsynlib.favorites` | `favorites.py` | SQLite favourites: ratings, tags, notes | `SCHEMA_VERSION=2` :91; `DB_NAME` :94; `APP_NAME` :98; `data_dir` :101; `default_path` :172; `Favorite` :270; `Favorites` :294; `Bound` :715; `bind` :739; `split_key` :747; `rating_cell` :814 |
| `vinsynlib.catalog` | `catalog.py` | Printed preset names + live layer, keyed `BANK:NNN` | `UNNAMED` :68; `wire_to_display` :71; `display_to_wire` :82; `make_key` :87; `split_key` :98; `Entry` :117; `Catalog` :137; `empty` :275; `load` :303; `dump` :354 |
| `vinsynlib.livenames` | `livenames.py` | The live-names JSON layer over a `Catalog` | `FILE_NAME` :57; `key` :60; `load` :65; `apply_to` :94; `save` :113 |
| `vinsynlib.build` | `build.py` | Which build/commit/tag is running | `Build` :58; `version_of` :72; `build_of` :88 |
| `vinsynlib.keys` | `keys.py` | Canonical keymap + wrapped legend | `Key` :82; `BROWSER_KEYS` :104; `FAVOURITE_KEYS` :121; `EDITOR_KEYS` :128; `CANONICAL_LEGEND` :142; `FAVOURITE_BLOCKS` :160; `CHANNEL_BLOCKS` :165; `key_for` :170; `legend` :184; `wrap_blocks` :215; `legend_from_bindings` :247 |
| `vinsynlib.midi` | `midi.py` | Port discovery, sweeping, SysEx identity | exceptions :80–:102; `list_ports` :128; `bidirectional_ports` :166; `likely_ports` :178; `open_remembered_or_swept` :220; `render_ports` :293; `install_clean_exit` :331; `ThrottledOut` :386; `MultiIn` :417; `open_input` :486; `open_output` :507; `identity_request` :534; `IdentityReply` :540; `DeviceIdentity` :550; `parse_identity_reply` :571 |
| `vinsynlib.terms` | `terms.py` | Vocabulary registry (sound/container/device words) | `FAMILY` :64; `ALLOWED_SOUND_WORDS` :87; `ALLOWED_CONTAINER_WORDS` :99; `plural` :116; `Terminology` :131; `REGISTRY` :213; `for_app` :216; `register` :232 |
| `vinsynlib.backup` | `backup.py` | Named whole-device backup files | `FORMAT=1` :16; `Backup` :22; `save` :51; `load` :95; `list_backups` :130 |
| `vinsynlib.undo` | `undo.py` | Undo records/log for editors | `Record` :16; `UndoLog` :23 |
| `vinsynlib.render` | `render.py` | Plain-text table + progress bar | `table` :43; `progress` :78 |
| `vinsynlib.conformance` | `conformance.py` | The checks a project runs on its own front end | `check_flags` :72; `check_bindings` :173; `check_legend` :223; `check_terms` :262 |
| `vinsynlib.devchecks` | `devchecks.py` | Source-level checks (imports, drift) | `FAMILY_THIRD_PARTY` :58; `iter_test_sources` :67; `config_saves_without_path` :107; `foreign_imports` :143; `check_foreign_imports` :183; `release_parts_invariants` :287; `release_parts_drift` :398 |
| `vinsynlib.ui.hints` | `ui/hints.py` | Textual key-hint bar widget | `KeyHints` |
| `vinsynlib.ui.report` | `ui/report.py` | Shared report/frame modal | `ReportScreen` |
| `vinsynlib.ui.prompt` | `ui/prompt.py` | One-line text prompt modal | `PromptScreen` |
| `vinsynlib.ui.confirm` | `ui/confirm.py` | Yes/no confirm modal | `ConfirmScreen` |
| `vinsynlib.ui.modals` | `ui/modals.py` | Report/Choice/Search/Rating/Category/Picker modals (0.4.0) | `ChoiceScreen`, `RatingFilter`, `RatingFilterScreen`, … |
| `vinsynlib.ui.browser` | `ui/browser.py` | The shared browser screen (0.4.0) | browser screen class |
| `vinsynlib.ui.protocol` | `ui/protocol.py` | `AppProtocol` (the app seam, 0.4.0) | `AppProtocol` (`notify_status`) |
| `vinsynlib.ui.work` | `ui/work.py` | Busy gate / worker helpers | `BusyGate`, `close_when_idle`, `QUIET_BRIDGE_ERRORS` |

---

## 2. Per-module: does nanosyned use it, where, else local equivalent

### 2.1 Used by nanosyned

| vinsynlib module | Import site | Notes |
|---|---|---|
| `config` | `nano/config.py:40` (`from vinsynlib.config import DEFAULT_PATH, Settings`) | `nano/config.py:54` binds `Settings("nanosyned", DEFAULT_PATH)`; module aliases :59–:67. Local `load_port_pair` :71 wraps `Settings.load_ports` (:76). |
| `favorites` | `nano/favorites.py:34` (`from vinsynlib import favorites as _favorites`), :35 (`SCHEMA_VERSION, Favorite`) | `data_dir()` :54, `default_path()` :61, `class Favorites(_favorites.Favorites)` :66. |
| `terms` | `nano/terms.py:32` (`Terminology, register`) | `TERMS = Terminology(app_name="nanosyned", sound="program", container="bank", device="Alesis NanoSynth")` :34; `register(TERMS)` :47. |
| `midi` | `nano/bridge.py:48` (`from vinsynlib import midi`) | `open_remembered_or_swept` used at `bridge.py:505`. `nanosyned/cli.py:39` uses `list_ports, render_ports`. |
| `cli` | `nanosyned/app.py:65` and `nanosyned/cli.py:33` (`add_common_arguments, make_parser, validate_common`; cli also `channel_of`) | Parser construction. |
| `keys.wrap_blocks` | `nanosyned/app.py:66` (`wrap_blocks as _wrap_blocks`) | Local `wrap_blocks` :103 delegates. |
| `ui.hints` | `nanosyned/app.py:67` (`KeyHints`) | Used :246. |
| `conformance` | `tests/test_conformance.py:26` | Test-only. |
| `devchecks` | `tests/test_config_paths.py:39`, `tests/test_version_gate_copy.py:19` | Test-only (`config_saves_without_path`, `release_parts_drift`). |

### 2.2 Reimplemented locally (candidates for adoption)

| vinsynlib module | nanosyned local equivalent | What adoption would delete/replace |
|---|---|---|
| `catalog` | `nano/catalog.py` (224 lines) — its own `Entry` (with `program_change` instead of display `number`/`kind`), `Catalog`, `empty`, `load`. | Replace with `from vinsynlib import catalog`. Differences to reconcile: vinsynlib keys on **display** numbers + optional `kind` (`make_key` :87, `wire_to_display` :71) and has `dump` (:354); nanosyned keys on raw `program_change` and hand-rolls `catalog.json` loading (`nano/catalog.py:183-224`). nanosyned's `disagreement()` (:134) is extra (not in the library) and would stay project-side. |
| `livenames` | none — nanosyned has no live-names file; live names live only in-memory in `nano/catalog.py` (`_live`). | vinsynlib.livenames is **unused**. Adopting it would give nanosyned a persisted live layer (`load`/`save`/`apply_to`, :65/:113/:94) and let `Catalog.set_live_name` be keyed the family way. |
| `render.table` / `render.progress` | `nanosyned/cli.py:44` local `_table`; app renders via Textual `DataTable`, not text tables. | Swap `cli._table` for `vinsynlib.render.table` (`render.py:43`). Sibling rxved/emorphed already import `vinsynlib.render` (see §3). |
| `ui.report` (`ReportScreen`) | `nanosyned/app.py:113 class ReportScreen(ModalScreen[None])` | Replace with `from vinsynlib.ui.report import ReportScreen`. Siblings: rxved `from vinsynlib.ui.report import ReportScreen as _Frame`; p2ked `ReportScreen`; emorphed `ReportScreen as _Frame`. |
| `ui.prompt` (`PromptScreen`) | `nanosyned/app.py:145 class PromptScreen(ModalScreen[str | None])` | Replace with `from vinsynlib.ui.prompt import PromptScreen`. emorphed already does. |
| `keys.legend` / `keys_from_bindings` | app constructs `KeyHints(KEY_HINTS)` directly (`app.py:246`). | Could use `vinsynlib.keys.legend_from_bindings` (:247) for the same string the other tools show. |
| `backup` | none. | Not applicable until nanosyned grows whole-device backup; p2ked/emorphed use it. |
| `undo` | none. | Not applicable (nanosyned is read-only except `select`); p2ked/emorphed use it. |
| `ui.modals`, `ui.browser`, `ui.protocol`, `ui.work`, `ui.confirm` | partially: there is no local modals/browser/confirm; `app.py` uses raw `ModalScreen` subclasses. | Adopt as the app is refactored onto `ui.browser`/`ui.protocol`/`ui.work`, matching emorphed/emorphed. |
| `build` | none — nanosyned has no build/commit line in its output. | Adopt `build_of` (`build.py:88`) as siblings do (`rxved`, `p2ked`, `emorphed` all import it) for a `--version`/report build line. |
| `spec.flag_help` | none — nanosyned relies on `add_common_arguments` only. | rxved uses `spec.flag_help` for its own flags; nanosyned could for tool-specific help. |

`nano/banks.py`, `nano/messages.py`, `nano/records.py`, `nano/dumps.py` are
hardware/protocol code that stays project-side by design (the library
docstring: "What stays in each project is what the hardware owns:
the wire format, the bank table, the meaning of a byte",
`__init__.py:25-28`).

---

## 3. Version gate and how the family pins/integrates it

### 3.1 The gate in the library

`vinsynlib/__init__.py:87 is_compatible_version(version_string, minimum) -> bool`
uses `_release_parts` (:62), which parses leading numeric components and
returns `None` for a non-numeric component. Documented behaviours
(:96-102): `"0.1"`→`(0,1,0)`, `"0.2rc1"`→`(0,2,0)`, `"0.0.9"` < `(0,1,0)`,
`"0.1.x"`/`None` → `False`.

`devchecks.release_parts_drift(entry_path)` (`devchecks.py:398`) compares a
project's *copy* of `_release_parts` against the library's
(`_library_version` :372, `release_parts_invariants` :287,
`_parts_function` :211): the symptom it guards is *"nanosyned is broken with
this vinsynlib and the other nine work"* (`devchecks.py:408`).

### 3.2 nanosyned's gate

`nanosyned/entry.py` runs before anything imports the library
(docstring :17-28). It carries a **local** `_release_parts` (:47) and
`_diagnose` (:70) checks `vinsynlib.__version__` against a local
`MINIMUM`/`SOURCE`:

- `nanosyned/entry.py:44` → `MINIMUM = (0, 2, 0)`
- `nanosyned/entry.py:47` → `SOURCE = "vinsynlib>=0.2.0"`
- `nanosyned/pyproject.toml:11` → `dependencies = [... "vinsynlib>=0.3.1"]`

> **Mismatch:** the packaging floor is `0.3.1` but the runtime gate still
> says `0.2.0` and entry.py does **not** call
> `vinsynlib.is_compatible_version`; it re-implements the comparison. Commit
> `16e3a95` moved the pyproject floor to `0.3.1` and added
> `tests/test_version_gate_copy.py` (which calls
> `devchecks.release_parts_drift`), but `MINIMUM`/`SOURCE` were left at
> `0.2.0`. `tests/test_entry.py:19,65-84` still pins `"vinsynlib>=0.2.0"`.

### 3.3 Family floors (current pyproject)

| repo | pyproject line | floor |
|---|---|---|
| nanosyned | `pyproject.toml:11` | `vinsynlib>=0.3.1` (runtime gate says 0.2.0) |
| rxved | `pyproject.toml:60` | `vinsynlib>=0.4.2` (comment :259 says bindings now) |
| p2ked | `pyproject.toml:19` | `vinsynlib>=0.4.2` |
| emorphed | `pyproject.toml:11` | `vinsynlib>=0.4.2` |

rxved, p2ked and emorphed all add `vinsynlib` to `known-first-party` in ruff
config (rxved `:272`, p2ked `:100`, emorphed `:61`) because it is a sibling
checkout, installed editable.

nanosyned is the **only** family member still on a pre-0.4 floor.

---

## 4. `spec.py` common-CLI catalogue vs what each tool passes

### 4.1 `CANONICAL_FLAGS` (`spec.py:117-198`), in `--help` order

| # | flag | kind | editor_only | canonical helps |
|---|---|---|---|---|
| 1 | `--port` | str | – | line 118 |
| 2 | `--scan` | flag | – | 125 |
| 3 | `--recv-port` | str | – | 131 |
| 4 | `--channel` | int | – | 137 |
| 5 | `--device-channel` (alias `--midi-channel`) | int | – | 143 |
| 6 | `--device-id` | int | – | 150 |
| 7 | `--exclusive-channel` | int | – | 156 |
| 8 | `--demo` | flag | – | 162 |
| 9 | `--timeout` | int | – | 163 |
| 10 | `--catalog` | str | – | 169 |
| 11 | `--config` | str | – | 175 |
| 12 | `--favorites` | str | – | 181 |
| 13 | `--yes` | flag | – | 187 |
| 14 | `--allow-write` | flag | **yes** | 192 |

`flag_names(tier=...)` (:311) returns browser = 1–13, editor = all 14.

### 4.2 `SUBCOMMANDS` (`spec.py:239-304`)

browser tier: `ports`, `status`, `banks` (aliases `groups`,`regions`,`roms`),
`list`, `find` (alias `search`), `fav` (alias `favorites`), `tags`, `names`,
`current`, `select` (alias `reach`), `read` (alias `syx`), `dump`, `send`
(writes), `hardware` (aliases `config`,`inquire`), `channels`, `multi`,
`mixes`, `resolve`.
editor tier: `params`, `programs`, `samples`, `audit`, `header`, `get`,
`set` (writes), `memory`, `catalog`.

### 4.3 What nanosyned passes

`add_common_arguments` signature: `cli.py:107-121`.

- **nanosyned app** `nanosyned/app.py:799-808`:
  `port=True, scan=True, recv_port=True, device_channel=True, catalog=True,
  config=True, favorites=True`. Defaults fill the rest: `channel=True`,
  `demo=True`; `device_id`, `exclusive_channel`, `timeout`, `yes`,
  `allow_write` stay **False**.
- **nanocli** `nanosyned/cli.py:291-301`:
  `port=True, scan=True, recv_port=True, channel=True, catalog=True,
  config=True, demo=True, yes=True`. Omits `device_channel` (app has it, CLI
  does not), and `device_id`/`exclusive_channel`/`timeout`/`allow_write`.

nanosyned **omits**: `--device-id`, `--exclusive-channel`, `--timeout`,
`--allow-write` everywhere.

### 4.4 How the siblings differ

| tool | call site | flags passed | notable differences |
|---|---|---|---|
| rxved cli | `rxved/cli.py:1146` | `recv_port, channel, device_id, demo, timeout, catalog, config, favorites` | **no `port`/`scan`**; has `device_id`, `timeout`, `favorites` |
| rxved app | `rxved/app.py:2861` | (see file; `--scan` handled specially per :2848) | uses `spec.flag_help` |
| p2ked cli | `p2ked/cli.py:716` | `port, scan, recv_port, channel, device_id, catalog, config` (`favorites=False`) | has `device_id` |
| p2ked app | `p2ked/app.py:3675` | adds `favorites`, `allow_write` | editor-style |
| emorphed cli | `emorphed/cli.py:466` | `port, scan, recv_port, channel, device_id, catalog, config, demo, yes, favorites` | full browser set + `favorites` |
| emorphed app | `emorphed/app.py:2405` | `device_channel, device_id, allow_write` | editor-style |

So nanosyned's CLI is the *leanest* in the family: it is the only one that
never passes `device_id`, `timeout` or `allow_write`, and the only one whose
CLI and app disagree on `device_channel`.

---

## 5. Exact signatures (config, favorites, catalog, livenames)

### `vinsynlib.config` (`config.py`)

```python
class Settings:                                          # :196
    app_name: str
    default_path: str = DEFAULT_PATH                     # "config.toml" :87
    # fields: _warned: set[str] (init=False)

    def read(self, path: str | None = None) -> tuple[dict[str, Any], str]      # :229
    def update(self, path: str | None = None, **changes: Any) -> None          # :~330
    def load_channel(self, path=None) -> int | None
    def save_channel(self, channel: int, path=None) -> None
    def load_port(self, path=None) -> str | None
    def save_port(self, port: str, path=None) -> None
    def load_recv_port(self, path=None) -> str | None
    def save_recv_port(self, port: str, path=None) -> None
    def load_ports(self, path=None) -> tuple[str, str] | None                  # :469
    def save_ports(self, send_port: str, recv_port: str, path=None) -> None    # :484
    def load_device_id(self, path=None) -> int | None
    def save_device_id(self, device_id: int, path=None) -> None
    def read_ui_state(self, path=None) -> tuple[dict[str, Any], str]           # :540
    def load_ui_state(self, key: str, path=None, *, default: Any = UNSET) -> Any   # :561
    def save_ui_state(self, key: str, value: str|int|float|bool|None, path=None) -> None  # :676

def bind(app_name: str, default_path: str = DEFAULT_PATH) -> Settings          # :738
def config_dir(tool: str) -> str                                               # :749
def default_config_path(tool: str) -> str                                      # :804
def config_help(tool: str) -> str                                              # :816
def migrate_legacy_config(app_name: str, *, legacy: str = DEFAULT_PATH,
                          target: str | None = None) -> str | None             # :845
UNSET = _Unset()                                                               # :178
MIGRATION_NOTE: str                                                            # :832
```

`config_dir` (§3.7 migration, added in 0.4.0): Windows `%LOCALAPPDATA%\<tool>`;
macOS `~/Library/Application Support/<tool>`; else `$XDG_CONFIG_HOME/<tool>`
or `~/.config/<tool>`; **does not create** the directory; raises `ValueError`
for an empty/`.`/`..`/separator-bearing name (:749-801).

### `vinsynlib.favorites` (`favorites.py`)

```python
data_dir(app_name: str = APP_NAME) -> str                                      # :101
default_path(app_name: str = APP_NAME, db_name: str = DB_NAME) -> str          # :172

@dataclass class Favorite:                                                     # :270
    bank_id: str; number: int; name: str = ""; rating: int = 0
    tags: str = ""; note: str = ""; added: float = 0.0
    @property key -> str          # "BANK:NNN"

class Favorites:                                                               # :294
    def __init__(self, path: str | None = None, *,
                 app_name: str = APP_NAME, db_name: str = DB_NAME) -> None      # :307
    def close(self) -> None
    def __enter__(self) -> Favorites; def __exit__(self, *_exc) -> None
    def get(self, bank_id: str, number: int) -> Favorite | None                 # :341
    def keys(self) -> set[str]; def keys_for_bank(self, bank_id) -> set[int]
    def all(self, *, order: str = "added") -> list[Favorite]
    def search(self, needle: str) -> list[Favorite]
    def with_tag(self, tag: str) -> list[Favorite]
    def tags(self) -> dict[str, int]
    def add(self, bank_id, number, *, name="", rating=0, tags="", note="") -> Favorite  # :541
    def remove(self, bank_id, number) -> bool
    def forget(self, bank_id, number) -> bool
    def dormant(self) -> list[Favorite]
    def toggle(self, bank_id, number, *, name="") -> bool
    def set_rating(self, bank_id, number, rating: int) -> None                  # :645
    def set_tags(self, bank_id, number, tags: str) -> None                      # :666
    def set_note(self, bank_id, number, note: str) -> None
    def refresh_names(self, lookup: Callable[[str, int], str | None]) -> int

@dataclass class Bound:                                                        # :715
    app_name: str; db_name: str = DB_NAME
    def data_dir(self) -> str; def default_path(self) -> str
    def store(self, path: str | None = None) -> Favorites
def bind(app_name: str, db_name: str = DB_NAME) -> Bound                        # :739
def split_key(key: str | tuple[str, int]) -> tuple[str, int]                    # :747
def rating_cell(rating: int, *, scale: int = 5) -> str                          # :814
SCHEMA_VERSION = 2                                                              # :91
```

Note `set_rating`/`set_tags`/`set_note` create a favourite for a slot that
was not one (:645-654 documents this as deliberate and test-pinned).

### `vinsynlib.catalog` (`catalog.py`)

```python
UNNAMED = "--"                                                                 # :68
def wire_to_display(wire: int, *, offset: int = 1) -> int                      # :71
def display_to_wire(display: int, *, offset: int = 1) -> int                   # :82
def make_key(bank_id: str, number: int, kind: str = "") -> str                 # :87
def split_key(key: str) -> tuple[str, str, int]                                # :98

@dataclass(frozen=True) class Entry:                                           # :117
    bank_id: str; number: int; name: str; kind: str = ""
    @property key -> str

class Catalog:                                                                 # :137
    def __init__(self, entries: Iterable[Entry] = (), *,
                 source: str = "", generated: str = "") -> None                # :148
    def entry(self, bank_id, number, kind="") -> Entry | None
    def name(self, bank_id, number, kind="") -> str | None
    def has(self, bank_id, *, kind: str | None = None) -> bool
    def __len__(self); def __bool__(self)
    def set_live_name(self, bank_id, number, name, kind="") -> None
    def live_name(self, bank_id, number, kind="") -> str | None
    def is_live(self, bank_id, number, kind="") -> bool
    def display_name(self, bank_id, number, kind="") -> str
    def differs(self, bank_id, number, kind="") -> bool
    def search(self, needle) -> list[...]

def empty() -> Catalog                                                         # :275
def load(path: str | None = None) -> Catalog                                   # :303
def dump(catalog: Catalog, path: str, *, source="", generated="",
         note="") -> ...                                                        # :354
```

Key grammar: `BANK:NNN` or `BANK:KIND:NNN`; `number` is the **display**
number; `wire_to_display`/`display_to_wire` convert at the edge. `load`
prints a warning and skips unreadable rows (:352) rather than failing.

### `vinsynlib.livenames` (`livenames.py`)

```python
FILE_NAME = "live-names.json"                                                  # :57
def key(bank_id: str, number: int, kind: str = "") -> str                      # :60
def load(path: str) -> dict[str, str]                                          # :65
def apply_to(catalog: Catalog, path: str) -> int                               # :94
def save(path: str, names: dict[str, str]) -> None                             # :113
```

`load` is best-effort (returns `{}` and warns on malformed files, :75-84);
`apply_to` skips unparseable keys and returns how many applied; `save` is
read-modify-write and write-then-rename (:113-130).

---

## 6. vinsynlib changes since nanosyned's pinned version

nanosyned's pyproject floor is `0.3.1` (`pyproject.toml:11`) and its runtime
gate says `0.2.0` (`entry.py:44`). Tags after `v0.3.1` (2026-10-10):
`v0.4.0` (2026-10-11), `v0.4.1` (2026-10-12), `v0.4.2` (2026-10-13).

### 6.1 v0.4.0 (`d3844ec`) — the big surface expansion

New public modules nanosyned does **not** yet use:

- `catalog.py` — commit `be9af93` "Wave 5 Agent B: catalog (§3.6)".
  Replaces nanosyned's local `nano/catalog.py`. Adds `make_key`/`split_key`
  key grammar, `kind`, `wire_to_display`, `dump`, and a named refusal on
  `load` (`92c5fcf` "catalog.load named refusal (finding 2); one key grammar
  for picker+catalog (finding 3)").
- `config_dir` + ui-state sidecar — `121e4ea` "Wave 5 Agent C: config_dir
  (§3.7) + ui-state (§3.15)". **The §3.7 migration changes where a config
  file lives** (`config.py:832 MIGRATION_NOTE`); a tool adopting it must call
  `migrate_legacy_config`. nanosyned still binds the relative `DEFAULT_PATH`.
- `ui.modals` — `afbd510` "Wave 5 Agent A: modals (§3.12) — Report/Choice/
  Search/Rating/Category/Picker".
- `ui.browser` + `ui.protocol.AppProtocol` + `ui.work` — `f582937` "Wave 4:
  AppProtocol (§6.4), browser (§3.11), worker (§3.10)"; `738b883`/`16e4cf1`.
- `backup.py` — `06c47f6` "Wave 3 Agent B: backup (§3.14)".
- `undo.py` — `130d4bb` "Wave 3 Agent A: undo (§3.5)".
- transport/identity work — `565511c` transport, `bc81d90` identity
  (`d2360ab` "identity parser accepts real replies").
- `favorites.rating_cell` exported — `f2eac97` "export rating_cell".
- `midi` hardening — `a3ff6e5`, `c58a555` (BusyGate), `542046c`.

### 6.2 v0.4.1 (`8265f63`)

- `f358339` "report: one frame for the family's nine copies, and a build
  line" — the shared `ui.report.ReportScreen` frame + `build.build_of` line.
- `423aa0a` "undo: a plan/settle seam beside the synchronous door"
  (`v0.4.1` also carries `18701ce` merge of the undo seam, p2ked converted).

### 6.3 v0.4.2 (`55e936d`, `HEAD`)

- `4fac892` "tests: the XDG branch of config_dir is not every POSIX one, so
  guard it".
- `43b426b` "build: a file URL's path is a URI path, so the drive keeps its
  slash".
- `79ce061` "build: a linked worktree's tags are one file away".
- `55e936d` "Release 0.4.2".

### 6.4 What nanosyned must adopt (release-notes → action)

1. **Fix the gate mismatch** (§3.2): bump `entry.py:44 MINIMUM` /
   `entry.py:47 SOURCE` to match `pyproject.toml:11` (`>=0.3.1`, or move both
   to `>=0.4.2` to match siblings) and update `tests/test_entry.py:19`.
   Better: call `vinsynlib.is_compatible_version` and keep the local
   `_release_parts` only for `devchecks.release_parts_drift`
   (`tests/test_version_gate_copy.py`).
2. **Adopt `vinsynlib.catalog`** in place of `nano/catalog.py`, reconciling
   the display-number/`kind` key grammar (`make_key` :87) against
   nanosyned's `program_change`-keyed `Entry`. Keep `disagreement()`
   project-side. Adoption also brings `dump` and the named `load` refusal.
3. **Adopt `vinsynlib.livenames`** to persist the live layer
   (`load`/`save`/`apply_to`), which nanosyned currently keeps only in memory.
4. **Adopt `vinsynlib.render.table`** in `nanosyned/cli.py:44`.
5. **Adopt `ui.report.ReportScreen` and `ui.prompt.PromptScreen`** in place of
   `nanosyned/app.py:113` and `:145` (matches rxved/p2ked/emorphed).
6. **Consider the §3.7 config_dir migration** — but note it is its own
   release because it moves a file; nanosyned has not opted in.
7. **Add `build.build_of`** for a build line, as all three siblings already
   do (`rxved`, `p2ked`, `emorphed` import `build_of`).
8. **CLI parity with siblings**: pass `device_id` (and, if hardware has one,
   `timeout`) so nanosyned's command line matches the family; today it is the
   only tool omitting `device_id`. Also reconcile app vs CLI on
   `device_channel` (`app.py:804` has it, `cli.py:291` does not).
