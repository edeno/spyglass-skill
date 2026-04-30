# NWB Ingestion

Loading NWB files into Spyglass via `insert_sessions` — filename rules, the post-ingest verification triplet, and the `reinsert=True` re-ingestion path. For the tables ingest writes into, see [common_tables.md](common_tables.md).

## Contents

- [Overview](#overview)
- [Two Filename-Convention Rules (Read First)](#two-filename-convention-rules-read-first)
- [Prerequisites](#prerequisites)
- [The Standard Flow](#the-standard-flow)
- [insert_sessions Parameters](#insert_sessions-parameters)
- [skip_duplicates: When to Use It](#skip_duplicates-when-to-use-it)
- [Inspecting After Ingestion](#inspecting-after-ingestion)
- [Re-ingesting a File](#re-ingesting-a-file)
- [Common Errors](#common-errors)

## Overview

Ingestion is the first-contact flow for a new NWB file: it walks the file, populates a large set of Spyglass common tables (Session, Subject, Electrode, ElectrodeGroup, Raw, DIOEvents, RawPosition, TaskEpoch, …), and registers the file under `Nwbfile`. Most first-time Spyglass tasks start with ingestion.

Entry point: `spyglass.data_import.insert_sessions`. Canonical tutorial notebook: `notebooks/02_Insert_Data.ipynb` (a worked walkthrough; for schema/API facts trust `src/spyglass/...`. `notebooks/py_scripts/02_Insert_Data.py` is the jupytext mirror kept for PR review). Docs: `docs/src/Features/Ingestion.md`.

Some lab-specific or custom metadata (labs, probes, devices) is often populated manually before calling `insert_sessions`, since those lookup tables are shared across sessions.

## Two Filename-Convention Rules (Read First)

These two rules are the most common source of ingestion errors. Both are covered in detail below, but mentioning them up front so they're not missed:

1. **Pass the RAW filename** (`my_session.nwb`) to `insert_sessions`, not the "copy" name. Spyglass copies the file on ingestion and appends `_` before `.nwb`, then stores that under `Nwbfile`. Downstream queries use the copy name (`my_session_.nwb`). Mixing these up is a common footgun — see [Inspecting After Ingestion](#inspecting-after-ingestion).
2. **Do NOT use `skip_duplicates=True` for raw NWB re-ingestion.** Use `reinsert=True` instead. `skip_duplicates` is for lookup-table inserts (ProbeType, Lab, etc.). See [skip_duplicates: When to Use It](#skip_duplicates-when-to-use-it).

## Prerequisites

Before calling `insert_sessions`:

1. **Spyglass is installed and `SPYGLASS_BASE_DIR` is set** — see [setup_install.md](setup_install.md) and [setup_config.md](setup_config.md)
2. **The NWB file is in the raw directory** — `$SPYGLASS_RAW_DIR`, usually `$SPYGLASS_BASE_DIR/raw/`
3. **Optional pre-inserts**: `Lab`, `LabMember`, `Institution`, `ProbeType`, `Probe` rows for any custom hardware. The notebook shows this pattern for a custom probe:

```python
from spyglass.common import ProbeType

# `probe_description` is required (`common/common_device.py:344`); the
# canonical insert in 02_Insert_Data.ipynb provides it. Omitting it
# raises a DataJointError on the insert.
ProbeType.insert1(
    {
        "probe_type": "128c-4s6mm",
        "probe_description": "128 channel polymer probe, 4 shanks, 6mm",
        "manufacturer": "Lawrence Livermore National Lab",
        "num_shanks": 4,
    },
    skip_duplicates=True,
)
```

4. **Tutorials and older READMEs may show stale import paths.** Spyglass
   has reorganized its package layout multiple times. If an external
   snippet shows `from spyglass import insert_sessions` or
   `from spyglass.common import SortGroup`, prefer the current paths:

   | Tutorial / stale import | Current path |
   |---|---|
   | `from spyglass import insert_sessions` | `from spyglass.data_import import insert_sessions` |
   | `from spyglass.common import SortGroup` | `from spyglass.spikesorting.v1 import SortGroup` |
   | `from spyglass.common import HeadDir` / `Speed` | (removed; use `common_position` tables) |
   | `from spyglass.common import SpikeSortingBackUp` | (removed) |

   When in doubt, verify against the current source tree:

   ```bash
   python -c 'from spyglass.data_import import insert_sessions'
   python -c 'from spyglass.spikesorting.v1 import SortGroup'
   ```

## The Standard Flow

```python
import spyglass.data_import as sgi

# Single file — the supported path
sgi.insert_sessions("my_session.nwb")

# Glob wildcard resolving to exactly one file is also accepted
sgi.insert_sessions("j1620210710_*.nwb")
```

`insert_sessions` accepts just the filename (it looks in `$SPYGLASS_RAW_DIR`), not a full path. If you pass a path, only the basename is used.

**Gotcha — multi-file input is broken in the current implementation.** Passing a list (`sgi.insert_sessions(["a.nwb", "b.nwb"])`) only processes the first file: the function wraps a single-file value in a list, then returns from inside the loop on the first iteration (see `src/spyglass/data_import/insert_sessions.py:90`). Process multiple files by looping yourself:

```python
for fname in ["session_01.nwb", "session_02.nwb"]:
    sgi.insert_sessions(fname)
```

## insert_sessions Parameters

```python
insert_sessions(
    nwb_file_names,           # str — one filename in $SPYGLASS_RAW_DIR; list input is broken (see Gotcha above)
    rollback_on_fail=False,   # On any per-table failure logged to InsertError, super_delete the Nwbfile row (cascades DB rows, does NOT clean files; mutually exclusive with raise_err=True — see populate_all_common.py:257)
    raise_err=False,          # Raise on first error instead of logging and continuing
    reinsert=False,           # Allow re-insertion of a file already in Nwbfile
)
```

### Error handling modes

The default is **permissive**: errors are logged, and ingestion continues across tables. Choose a stricter mode when you need it:

- `rollback_on_fail=True` — On any error, delete the `Nwbfile` entry so you can retry cleanly. Useful during debugging, when partial state would interfere with the next attempt.
- `raise_err=True` — Skip error logging and raise immediately. Useful when stepping through with a debugger. Warning: does not roll back; parent-table entries may remain even after child failures (transactions only cover sibling tables).

## skip_duplicates: When to Use It

`skip_duplicates=True` is a common DataJoint kwarg that silently ignores rows that would conflict with existing primary keys. It's useful in two places:

- **Pre-inserting lookup rows**: `ProbeType.insert1(..., skip_duplicates=True)` — idempotent, safe to re-run.
- **Re-running Selection inserts** during pipeline development.

It is **not** appropriate for raw data ingestion. `insert_sessions` does NOT accept `skip_duplicates` — passing it raises `TypeError: unexpected keyword argument 'skip_duplicates'` (see SKILL.md Core Directives + common_mistakes.md #3). Use `reinsert=True` for re-ingestion of a file that's already in `Nwbfile`.

## Inspecting After Ingestion

**All inspection queries use the COPY filename** (`my_session_.nwb`), not the raw filename you passed to `insert_sessions`. This is the most common filename mistake — see the filename-convention rule at the top of this file.

```python
from spyglass.common import Session, Nwbfile
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

# Derive the copy filename once, reuse everywhere downstream
nwb_copy_file_name = get_nwb_copy_filename("my_session.nwb")  # "my_session_.nwb"

# Was the file registered?
Nwbfile & {"nwb_file_name": nwb_copy_file_name}

# What got ingested into Session?
Session & {"nwb_file_name": nwb_copy_file_name}

# Who was the experimenter?
Session.Experimenter & {"nwb_file_name": nwb_copy_file_name}
```

Spyglass copies the NWB file on ingestion and registers the copy under `Nwbfile` with `_` appended before `.nwb`. You pass the **raw** filename to `insert_sessions`; everything downstream references the copy. Summary:

```python
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

nwb_file_name = "my_session.nwb"          # what you pass to insert_sessions
nwb_copy_file_name = get_nwb_copy_filename(nwb_file_name)  # "my_session_.nwb"
# Session & {"nwb_file_name": nwb_copy_file_name}
```

## Re-ingesting a File

To overwrite an existing ingestion:

```python
sgi.insert_sessions("my_session.nwb", reinsert=True)
```

**What `reinsert=True` actually does.** `insert_sessions` checks whether `Nwbfile & {nwb_file_name: ...}` already exists; if so AND `reinsert=True`, it calls `query.delete(safemode=False)` on the Nwbfile row first, then re-copies and re-runs `populate_all_common` (`data_import/insert_sessions.py:73-92`). If `reinsert=False` and the file already exists, it warns and **skips** — does NOT raise. So:

- `reinsert=True` is **destructive — full cascade**. Deletes every downstream row that FKs the Nwbfile: `Session`, `IntervalList` rows for this file, and every populate-tier output produced from them.
- **Permission gating.** The deletion runs through SpyglassMixin's cautious_delete flow; missing `Session.Experimenter` linkage or a permission failure can stop the delete partway, leaving a partially-deleted state that subsequent `reinsert=True` calls have to clean up before they can re-ingest.
- **Inspect topology before running.** `Session.descendants()` returns table names / `FreeTable` objects, not a restrictable relation. For the dependency view use `python skills/spyglass/scripts/db_graph.py path --down Session`, or loop `Session.descendants(as_objects=True)` and restrict each table by `nwb_file_name` to count rows that will be lost.
- **Back up analysis outputs you care about before running.** Spyglass cleanup *will* remove unused DataJoint-managed external files (raw and analysis stores; `cautious_delete.py:238` calls DataJoint external cleanup with `delete_external_files=True` after the row delete), but it will not preserve arbitrary lab-managed files, hand-curated derivatives, or exports living outside the tracked external stores. Copy out anything in that second category before `reinsert=True`.
- `reinsert=False` (default) on an already-ingested file is a no-op with a warning. Don't expect re-ingestion behavior unless you pass `reinsert=True` explicitly.

### Delete Quirks (read before deleting a Session)

Two non-obvious behaviors:

1. **Delete requires Experimenter + LabTeam wiring.** Deleting a `Session` raises `PermissionError` in two distinct cases (see `src/spyglass/utils/mixins/cautious_delete.py`): (a) **the session has no `Experimenter` row** — checked first, raises with "Please ensure all Sessions have an experimenter in Session.Experimenter"; (b) the user doing the delete does not share a `LabTeam` with the session's experimenter — checked second. If the error mentions "experimenter", fix (a) by inserting into `Session.Experimenter` before trying again. Only if (a) passes do you need to check `LabTeam.LabTeamMember` for shared team membership.
2. **Session delete does NOT delete the `Nwbfile` row or the file on disk.** After `(Session & key).delete()`, the corresponding `Nwbfile` entry still blocks re-ingestion (with "already exists") and the file stays on disk until you explicitly run `Nwbfile().cleanup(delete_files=True)` — itself destructive. Full re-ingest therefore needs: delete downstream → delete `Session` → delete `Nwbfile` row → (optional) cleanup files.

## Common Errors

- **File not found**: `insert_sessions` looks in `$SPYGLASS_RAW_DIR`. Confirm the file is there and `SPYGLASS_BASE_DIR` is set correctly — `python skills/spyglass/scripts/verify_spyglass_env.py --check base_dir_resolved --check subdirs_exist_writable` reports both in one call.
- **"... is already in Nwbfile table"**: not `Session` — `insert_sessions` checks the *copied* filename against `Nwbfile` (`data_import/insert_sessions.py:70`). Pass `reinsert=True`, or delete the existing `Nwbfile` row first.
- **Device/probe not in lookup table**: pre-insert `ProbeType`, `Probe`, `DataAcquisitionDevice` etc. with `skip_duplicates=True` before ingestion.
- **Partial ingestion after failure**: if `rollback_on_fail=False` (default) and something failed midway, some tables have entries and some don't. **Recovery is not a one-liner** — `insert_sessions(..., reinsert=False)` on a file already in `Nwbfile` is a no-op with a warning (see "What `reinsert=True` actually does" above), so simply re-running won't pick up where it left off. Inspect first: `(Nwbfile & {nwb_file_name: ...})`, then walk `Session.descendants(as_objects=True)` and restrict each table by `nwb_file_name` (or run `python skills/spyglass/scripts/db_graph.py path --down Session` for a topology summary) to see what landed — `Session.descendants() & {...}` does NOT work because `descendants()` returns names / `FreeTable` objects, not a restrictable relation. Then either (a) rerun with `reinsert=True, rollback_on_fail=True` to delete-and-redo cleanly, or (b) manually delete only the stale downstream rows and let the next populate fill them in. Both are destructive — read the destructive-ops warning in SKILL.md before either.
- **Extension not registered**: NWB extensions (`ndx-franklab-novela`, `ndx-optogenetics`, `ndx-ophys-devices`, `ndx-pose`; see `pyproject.toml:53-56`) must be importable. They're installed with Spyglass's core deps.
- **"A different version of X.nwb has already been placed"** or
  **"downloaded but did not pass checksum"**: DataJoint tracks
  content-hash for external-store files. Deleting the NWB with plain
  `rm` (instead of `Nwbfile().cleanup(delete_files=True)`) leaves an
  orphan external-store row, and re-ingesting a file with a different
  hash is rejected. Editing the raw NWB in place breaks the same
  check. Always delete via
  `(Nwbfile & key).delete(); Nwbfile().cleanup(delete_files=True)`
  and never edit an ingested NWB in place — work on a copy.
- **`ValueError: Name has unsupported format for <name>. Must use exactly
  one comma+space (i.e., ', ') or space.`**: `LabMember.insert_from_nwbfile`
  routes through `decompose_name`
  (`src/spyglass/common/common_lab.py:366`), which accepts only
  exactly-two-token names — either `'First Last'` (single space, no
  comma) or `'Last, First'` (one comma+space). Multi-token entries
  like `'Kyu Hyun Lee'` (three tokens, no comma) fail. Fix: rewrite
  to `'Lee, Kyu Hyun'` before ingest, or pre-insert the `LabMember`
  row manually with `lab_member_name` set explicitly.
- **`PopulateException: Data acquisition device properties ... do not
  match`**: a `DataAcquisitionDevice` with the same
  `data_acquisition_device_name` already exists in the DB with
  different secondary values. This is common when tutorial NWBs ship
  with different canonical metadata than the lab DB. Compare the
  conflicting fields:

  ```python
  DataAcquisitionDevice & {'data_acquisition_device_name': name}
  ```

  Either update the NWB to match the DB entry, or rename the device
  per-session. Do not `.delete()` the DB row to "force" the match —
  other sessions depend on it.
- **`ValueError: ElementIdentifiers must contain integers`**
  (during `AnalysisNwbfile.add_nwb_object()` /
  `DynamicTable.from_dataframe`): `hdmf >= 3.14` requires integer IDs.
  Passing a DataFrame whose index is a float column (e.g. time) trips
  this. Keep the time column as a regular column; let pandas provide
  the default RangeIndex, or pass an explicit integer `id` column.
- **`original_reference_electrode` stuck at `-1` after re-ingesting a
  fixed NWB**: Spyglass's `Electrode.make` reads per-electrode
  reference/probe metadata only when the NWB ElectrodeGroup uses the
  `ndx_franklab_novela.Probe` device. For a generic
  `pynwb.ecephys.ElectrodeGroup`, it falls back to default values
  (commonly `-1`) silently. The right fixes, in order of preference:
  - **Fix the NWB.** Rewrite the file to use `ndx_franklab_novela.Probe`
    so the make() handler picks up the per-electrode metadata, then
    re-ingest with `reinsert=True` (destructive — see "What
    `reinsert=True` actually does" above).
  - **Use the supported config / metadata override before
    re-ingestion** if your install exposes one (consult
    `02_Insert_Data.ipynb` and `common_ephys.Electrode.make` on the
    install). This avoids hand-editing rows that downstream tables
    already FK to.
  - **Don't** patch already-ingested rows via
    `Electrode.insert(..., allow_direct_insert=True)` as a routine
    fix. Direct-update of a row that downstream tables FK to is
    risky scientific-data guidance: any populated table whose
    `make()` already used the `-1` value won't be re-run, so the
    inconsistency persists. If you genuinely need the in-place
    edit, inspect the descendants first and confirm with the user
    before proceeding.

## Probe / electrode conflicts from the NWB

Several ingestion failures trace back to the identity model that
Spyglass's `common_ephys` tables enforce on top of the NWB electrodes
table. The symptom depends on which invariant your NWB breaks:

| Symptom | What's wrong in the NWB |
|---|---|
| `PopulateException: Probe type properties ... do not match` | Multiple physical probes share the same `probe_type` / `description`, so Spyglass collapses them to one row |
| `IntegrityError (_electrode_ibfk_2 ...)` | The IntegrityError comes from `Electrode`'s composite FK to `Probe.Electrode`, not from `Electrode.name` itself: `Electrode` keys on `(nwb_file_name, electrode_group_name, electrode_id)` and `name` is a **secondary** attribute (`common/common_ephys.py:73-79`). The triggering condition is usually that the NWB electrodes table assigns the same (probe, electrode_id) to electrodes belonging to physically different probes, or that `Probe.Electrode` rows are missing for the (probe_id, probe_electrode) tuple the row tries to FK. Verify with `code_graph.py describe Electrode` and inspect `(Probe.Electrode & {"probe_id": ...})` for the row you're inserting. |
| DataJoint formatting error on `Probe.Electrode() & key` / `NaN` in queries | `rel_x` / `rel_y` / `rel_z` is NaN or None in the NWB electrodes table |
| `AssertionError: ChannelSliceRecording: channel ids are not all in parents` | NWB electrodes table has a `channel_name` column; SpikeInterface >=0.99 reads that column instead of `electrode_id` |

**Check before inserting.**

```python
import pynwb
with pynwb.NWBHDF5IO(path, 'r') as io:
    nwb = io.read()
    print('colnames:', nwb.electrodes.colnames)    # look for 'channel_name'
    df = nwb.electrodes.to_dataframe()
    # `Electrode.name` is a SECONDARY varchar set from `str(electrode_id)`
    # (`common/common_ephys.py:73, 163`); the FK-sensitive identity is
    # the (probe, shank, probe_electrode) tuple plus the per-NWB
    # `electrode_id` PK. Diagnose conflicts on those, not on `name`:
    if 'electrode_id' in df.columns:
        print('duplicate electrode_id:',
              df.duplicated(subset=['electrode_id']).sum())
    probe_cols = [c for c in ('probe_id', 'probe_type', 'probe_shank',
                              'probe_electrode') if c in df.columns]
    if probe_cols:
        print('duplicate probe-tuple rows:',
              df.duplicated(subset=probe_cols).sum())
    print('NaN geometry:',
          df[['rel_x', 'rel_y', 'rel_z']].isna().sum().to_dict())
```

**Fix.** Assign a distinct `probe_type` per physical probe, generate
globally unique `electrode_id` integers across probes (the per-NWB
PK on `Electrode`; `Electrode.name` is just `str(electrode_id)` and
not what FK lookups key on), pre-insert `Probe.Electrode` rows for
every `(probe_id, probe_shank, probe_electrode)` tuple that any
electrode FKs, replace NaN geometry with `-1` or require real
coordinates, and if the NWB uses `channel_name` make sure Spyglass
is on a version that handles it (confirm by searching
`src/spyglass/common/common_ephys.py` for `channel_name` support).

## TaskEpoch silently drops epochs on tag-format mismatch

`TaskEpoch` relies on numeric tags to match NWB epochs against
`IntervalList` intervals, **and** the table's `epoch` primary-key
field is `int` (`common/common_task.py:128`). Two distinct failure
modes flow from non-numeric values, and they fail at different
stages:

- **Nonnumeric `task_epochs` value (e.g. `'custom_name'` in `nwbfile.processing['tasks'].task_table.task_epochs`).** This is the value that gets cast to the int `epoch` PK. A non-castable string raises at the `TaskEpoch.insert(...)` step in `make()` (DataJoint type coercion / int cast on the PK), not silently. The exact exception text depends on the DataJoint version; historically users have reported `ValueError: invalid literal for int()` and similar, but current source does not raise a `could not convert string to float` here — that earlier wording was inaccurate.
- **Nonnumeric or unconventional `nwbfile.epochs.tags` value.** This is the tag that gets matched against `IntervalList` interval names by `get_epoch_interval_name` (`common/common_task.py:315`). On no match or ambiguous match, the method **logs a warning and returns `None`** — the row for that epoch is then silently dropped. This is the "rows silently missing for some epochs" failure mode.
- `KeyError: 0` on a multi-row task table is a separate quirk in upstream traversal — distinct from either of the above.
- Tag `'2'` double-matching multiple intervals (e.g. `'02_r1'` AND `'12_s2'`) — current `get_epoch_interval_name` (`common/common_task.py:315-355`) uses **substring** checks for the zero-padded forms (`str(epoch).zfill(2) in interval`), not exact matching. The two-digit-only-match prioritization helps the `'1'` vs `'12'` case, but unique-match isn't guaranteed; the method emits a warning and returns `None` when ambiguous.

**Required NWB shape.**

- `nwbfile.epochs.tags` — numeric strings. `get_epoch_interval_name`
  tries exact match first, then two-digit zero-padded substring, then
  three-digit zero-padded substring (`common/common_task.py:315-355`).
  `'1'`, `'01'`, and `'001'` all match an interval named `'01'` (or
  `'001'`). Zero-padding is a *convention* in modern Spyglass, not a
  hard requirement; older versions did require strict zero-padding,
  so if the user is on an older release this is still the typical
  fix.
- `nwbfile.processing['tasks'].task_table.task_epochs` — numeric
  values per row. **One task-table row can carry a list of multiple
  epoch numbers**: `_process_task_epochs` loops over each row's
  `task_epochs` field (`common/common_task.py:172-194, 277-301`), so
  one task row legitimately produces multiple `TaskEpoch` rows. Don't
  expect task-row count to equal epoch count.

**Check before ingest.**

```python
import pynwb
with pynwb.NWBHDF5IO(path, 'r') as io:
    nwb = io.read()
    print('epoch tags:', [list(e) for e in nwb.epochs.tags[:]])
    print('task table:', nwb.processing['tasks'].task_table.to_dataframe())
```

If any tag isn't numeric, rewrite the NWB before re-ingesting;
Spyglass does not coerce. (Verify the current behavior by reading the
relevant `make()` body — if a future Spyglass version coerces tags,
this caveat becomes moot; until the source coerces, the NWB-side fix
is required.)
