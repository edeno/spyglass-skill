# NWB Ingestion


## Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [The Standard Flow](#the-standard-flow)
- [insert_sessions Parameters](#insert_sessions-parameters)
- [skip_duplicates: When to Use It](#skip_duplicates-when-to-use-it)
- [Inspecting After Ingestion](#inspecting-after-ingestion)
- [Re-ingesting a File](#re-ingesting-a-file)
- [Common Errors](#common-errors)

## Overview

Ingestion is the first-contact flow for a new NWB file: it walks the file, populates a large set of Spyglass common tables (Session, Subject, Electrode, ElectrodeGroup, Raw, DIOEvents, RawPosition, TaskEpoch, …), and registers the file under `Nwbfile`. Most first-time Spyglass tasks start with ingestion.

Entry point: `spyglass.data_import.insert_sessions`. Canonical notebook: `notebooks/py_scripts/02_Insert_Data.py`. Docs: `docs/src/Features/Ingestion.md`.

Some lab-specific or custom metadata (labs, probes, devices) is often populated manually before calling `insert_sessions`, since those lookup tables are shared across sessions.

## Prerequisites

Before calling `insert_sessions`:

1. **Spyglass is installed and `SPYGLASS_BASE_DIR` is set** — see [setup_and_config.md](setup_and_config.md)
2. **The NWB file is in the raw directory** — `$SPYGLASS_RAW_DIR`, usually `$SPYGLASS_BASE_DIR/raw/`
3. **Optional pre-inserts**: `Lab`, `LabMember`, `Institution`, `ProbeType`, `Probe` rows for any custom hardware. The notebook shows this pattern for a custom probe:

```python
from spyglass.common import ProbeType

ProbeType.insert1(
    {"probe_type": "128c-4s6mm", "manufacturer": "Lawrence Livermore National Lab", "num_shanks": 4},
    skip_duplicates=True,
)
```

## The Standard Flow

```python
import spyglass.data_import as sgi

# Single file
sgi.insert_sessions("my_session_.nwb")

# Multiple files
sgi.insert_sessions(["session_01_.nwb", "session_02_.nwb"])

# Glob wildcard matching exactly one file
sgi.insert_sessions("j1620210710_*.nwb")
```

`insert_sessions` accepts just the filename (it looks in `$SPYGLASS_RAW_DIR`), not a full path. If you pass a path, only the basename is used.

## insert_sessions Parameters

```python
insert_sessions(
    nwb_file_names,           # str or List[str] — filename(s) in $SPYGLASS_RAW_DIR
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

```python
from spyglass.common import Session, Nwbfile

# Was the file registered?
Nwbfile & {"nwb_file_name": "my_session_.nwb"}

# What got ingested into Session?
Session & {"nwb_file_name": "my_session_.nwb"}

# Who was the experimenter?
Session.Experimenter & {"nwb_file_name": "my_session_.nwb"}
```

Spyglass copies the NWB file and registers a "copy" filename with `_` appended before `.nwb` (e.g., `mysession_.nwb`). Downstream tables reference the copy, not the original.

## Re-ingesting a File

To overwrite an existing ingestion:

```python
sgi.insert_sessions("my_session_.nwb", reinsert=True)
```

**Before reinserting**, delete existing downstream entries — otherwise foreign keys will block the replacement. Review the delete implications carefully (see the destructive ops warning in SKILL.md).

## Common Errors

- **File not found**: `insert_sessions` looks in `$SPYGLASS_RAW_DIR`. Confirm the file is there and `SPYGLASS_BASE_DIR` is set correctly.
- **"Session already exists"**: pass `reinsert=True`, or delete the existing `Nwbfile` row first.
- **Device/probe not in lookup table**: pre-insert `ProbeType`, `Probe`, `DataAcquisitionDevice` etc. with `skip_duplicates=True` before ingestion.
- **Partial ingestion after failure**: if `rollback_on_fail=False` (default) and something failed midway, some tables have entries and some don't. Easiest recovery: `rollback_on_fail=True` on a retry, or manually delete the `Nwbfile` entry and its downstream cascades.
- **Extension not registered**: NWB extensions (`ndx-franklab-novela`, `ndx-pose`) must be importable. They're installed with Spyglass's core deps.
