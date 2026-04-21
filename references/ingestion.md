# NWB Ingestion

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

Entry point: `spyglass.data_import.insert_sessions`. Canonical notebook: `notebooks/02_Insert_Data.ipynb` (run this one; `notebooks/py_scripts/02_Insert_Data.py` is the jupytext mirror kept for PR review). Docs: `docs/src/Features/Ingestion.md`.

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

ProbeType.insert1(
    {"probe_type": "128c-4s6mm", "manufacturer": "Lawrence Livermore National Lab", "num_shanks": 4},
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

   ```python
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
    rollback_on_fail=False,   # Undo all inserts if any table fails
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

It is **not** appropriate for raw data ingestion. `insert_sessions` uses `reinsert=True` instead, which explicitly intends to overwrite an existing Nwbfile entry. Using `skip_duplicates` on raw data silently masks real errors.

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

**Before reinserting**, delete existing downstream entries — otherwise foreign keys will block the replacement. Review the delete implications carefully (see the destructive ops warning in SKILL.md).

### Delete Quirks (read before deleting a Session)

Two non-obvious behaviors:

1. **Delete requires Experimenter + LabTeam wiring.** Deleting a `Session` raises `PermissionError` in two distinct cases (see `src/spyglass/utils/mixins/cautious_delete.py`): (a) **the session has no `Experimenter` row** — checked first, raises with "Please ensure all Sessions have an experimenter in Session.Experimenter"; (b) the user doing the delete does not share a `LabTeam` with the session's experimenter — checked second. If the error mentions "experimenter", fix (a) by inserting into `Session.Experimenter` before trying again. Only if (a) passes do you need to check `LabTeam.LabTeamMember` for shared team membership.
2. **Session delete does NOT delete the `Nwbfile` row or the file on disk.** After `(Session & key).delete()`, the corresponding `Nwbfile` entry still blocks re-ingestion (with "already exists") and the file stays on disk until you explicitly run `Nwbfile().cleanup(delete_files=True)` — itself destructive. Full re-ingest therefore needs: delete downstream → delete `Session` → delete `Nwbfile` row → (optional) cleanup files.

## Common Errors

- **File not found**: `insert_sessions` looks in `$SPYGLASS_RAW_DIR`. Confirm the file is there and `SPYGLASS_BASE_DIR` is set correctly.
- **"Session already exists"**: pass `reinsert=True`, or delete the existing `Nwbfile` row first.
- **Device/probe not in lookup table**: pre-insert `ProbeType`, `Probe`, `DataAcquisitionDevice` etc. with `skip_duplicates=True` before ingestion.
- **Partial ingestion after failure**: if `rollback_on_fail=False` (default) and something failed midway, some tables have entries and some don't. Easiest recovery: `rollback_on_fail=True` on a retry, or manually delete the `Nwbfile` entry and its downstream cascades.
- **Extension not registered**: NWB extensions (`ndx-franklab-novela`, `ndx-pose`) must be importable. They're installed with Spyglass's core deps.
- **"A different version of X.nwb has already been placed"** or
  **"downloaded but did not pass checksum"**: DataJoint tracks
  content-hash for external-store files. Deleting the NWB with plain
  `rm` (instead of `Nwbfile().cleanup(delete_files=True)`) leaves an
  orphan external-store row, and re-ingesting a file with a different
  hash is rejected. Editing the raw NWB in place breaks the same
  check. Always delete via
  `(Nwbfile & key).delete(); Nwbfile().cleanup(delete_files=True)`
  and never edit an ingested NWB in place — work on a copy.
- **`ValueError: Names should be stored as 'last, first'. Skipping <name>`**:
  `LabMember.insert_from_nwbfile` expects the NWB `experimenter` field
  in `'Last, First'` (comma-separated) format. Multi-token first names
  without a comma (`'Kyu Hyun Lee'`) trip this. Either rewrite
  `experimenter` to `'Lee, Kyu Hyun'` before ingest, or pre-insert the
  LabMember row manually.
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

## Probe / electrode conflicts from the NWB

Several ingestion failures trace back to the identity model that
Spyglass's `common_ephys` tables enforce on top of the NWB electrodes
table. The symptom depends on which invariant your NWB breaks:

| Symptom | What's wrong in the NWB |
|---|---|
| `PopulateException: Probe type properties ... do not match` | Multiple physical probes share the same `probe_type` / `description`, so Spyglass collapses them to one row |
| `IntegrityError (_electrode_ibfk_2 ...)` | Electrode `name` / `id` is not globally unique across probes (post-#1454 uniqueness) |
| DataJoint formatting error on `Probe.Electrode() & key` / `NaN` in queries | `rel_x` / `rel_y` / `rel_z` is NaN or None in the NWB electrodes table |
| `AssertionError: ChannelSliceRecording: channel ids are not all in parents` | NWB electrodes table has a `channel_name` column; SpikeInterface >=0.99 reads that column instead of `electrode_id` |

**Check before inserting.**

```python
import pynwb
with pynwb.NWBHDF5IO(path, 'r') as io:
    nwb = io.read()
    print('colnames:', nwb.electrodes.colnames)    # look for 'channel_name'
    df = nwb.electrodes.to_dataframe()
    print('duplicate names per probe:',
          df.groupby(['group_name', 'name']).size().max())
    print('NaN geometry:',
          df[['rel_x', 'rel_y', 'rel_z']].isna().sum().to_dict())
```

**Fix.** Assign a distinct `probe_type` per physical probe, ensure
electrode `name` + `id` are unique across probes (generate globally
unique integer IDs at NWB creation), replace NaN geometry with `-1`
or require real coordinates, and if the NWB uses `channel_name` make
sure Spyglass is on a version that handles it (post-PR #1447).

## TaskEpoch silently drops epochs on tag-format mismatch

`TaskEpoch` relies on numeric tags to match NWB epochs against
`IntervalList` intervals. Failures look like:

- Rows silently missing for some epochs
- `KeyError: 0` on a multi-row task table
- `ValueError: could not convert string to float` for tags like `'custom_name'`
- Tag `'2'` double-matching `'02_r1'` AND `'03_s2'` after PR #1459

**Required NWB shape.**

- `nwbfile.epochs.tags` — numeric strings, zero-padded to the
  convention used elsewhere in the file (e.g. `'01'`, `'02'`, not
  `'1'`, `'2'`).
- `nwbfile.processing['tasks'].task_table.task_epochs` — numeric
  values, with row count matching the epoch count.

**Check before ingest.**

```python
import pynwb
with pynwb.NWBHDF5IO(path, 'r') as io:
    nwb = io.read()
    print('epoch tags:', [list(e) for e in nwb.epochs.tags[:]])
    print('task table:', nwb.processing['tasks'].task_table.to_dataframe())
```

If any tag isn't numeric, rewrite the NWB before re-ingesting;
Spyglass does not coerce. Tracked upstream in #1432 / #1443 / #1485.
