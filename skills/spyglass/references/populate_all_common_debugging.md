# Debugging `populate_all_common`

Triage failures from the common-ingest driver `spyglass.common.populate_all_common.populate_all_common`. If your failure is in a downstream pipeline's `populate()` / `make()` — not in `populate_all_common` specifically — go to [runtime_debugging.md](runtime_debugging.md) instead.

## Contents

- [Why this needs its own page](#why-this-needs-its-own-page)
- [Primary fix — pass `raise_err=True`](#primary-fix--pass-raise_errtrue)
- [Alternative — skip the driver and run the failing table directly](#alternative--skip-the-driver-and-run-the-failing-table-directly)
- [When to reach for this](#when-to-reach-for-this)
- [Cross-references](#cross-references)

## Why this needs its own page

`populate_all_common` is the common-ingest driver that calls each common-module table in sequence. By default (`raise_err=False`) it catches exceptions per-table and writes only a short message to `common_usage.InsertError` — the full traceback is lost. This is the single most common cause of "fresh ingest completed but my common tables are missing rows."

The failure is *quieter* than a normal Python exception, but not fully silent — current Spyglass emits two recoverable signals before returning:

- A summary `logger.error(...)` line at the end of the run naming the failed tables (`src/spyglass/common/populate_all_common.py:265-272`). It looks like `Errors occurred during population for {nwb_file_name}: Failed tables [...]. See common_usage.InsertError for more details`.
- A return value: a list of `InsertError` keys for the tables that failed. If the user captured the call (`failed = populate_all_common(...)`), that list is the per-table inventory.

Both signals are easy to miss — the logger.error is one line in a long ingest log, and most users discard the return value. Every other debugging path in [runtime_debugging.md](runtime_debugging.md) assumes you have a full traceback to work with. Here you have a name and an `InsertError` row, not a stack trace, so the first move is to force the traceback (next section) once you've used the cheaper signals to confirm which tables actually failed.

## Primary fix — pass `raise_err=True`

The function accepts a `raise_err` parameter (see `src/spyglass/common/populate_all_common.py:159-161`); it's the built-in way to propagate tracebacks:

```python
from spyglass.common import populate_all_common

# IMPORTANT: pass the COPIED filename (the trailing-underscore form
# that lives in `Nwbfile`), not the raw filename. `insert_sessions`
# creates the copy via `copy_nwb_link_raw_ephys` and then passes
# `out_nwb_file_name` to `populate_all_common`
# (`data_import/insert_sessions.py:67-90`). Querying
# `(Nwbfile & {nwb_file_name: ...})` shows the form already
# registered for the session.
populate_all_common("raw_file_.nwb", raise_err=True)  # note trailing _
```

Once you have the traceback, route back to the matching failure signature in [runtime_debugging.md](runtime_debugging.md#failure-signatures) — usually signature A (`fetch1` cardinality) or H (IntegrityError from a missing ancestor row).

## Alternative — skip the driver and run the failing table directly

Useful when you want to isolate which table is failing without re-running the ones that succeeded. The faithful isolation pattern is **NOT** `T().populate(...)` — `populate_all_common` doesn't go through `populate()` for most tables. The driver's per-table loop lives in `single_transaction_make` (`common/populate_all_common.py:114-150`):

- For `SpyglassIngestion` tables (the bulk of the common-tier list — `Session`, `Raw`, `RawPosition`, `PositionSource`, `Electrode`, `ElectrodeGroup`, `DIOEvents`, `VideoFile`, `CameraDevice`, `Probe`, `ProbeType`, `OptogeneticProtocol`, `Virus`, etc.; full list at `populate_all_common.py:7-40`), the driver calls `table().insert_from_nwbfile(nwb_file_name, config=table_config)` directly. The `config` dict comes from `entries.yaml` if present and overrides defaults; calling bare `populate()` skips this.
- For non-`SpyglassIngestion` tables, the driver derives a key from upstream parents and calls `table().make(pop_key)` (`:127, 150`).

Patterns matching the actual driver:

```python
from spyglass.common import Session, Raw, DIOEvents, PositionSource

# SpyglassIngestion tables — pass the copied (trailing-underscore)
# filename and let entries.yaml override defaults if present.
copy_name = "raw_file_.nwb"  # see "Primary fix" above for why this form
for T in [Session, Raw, DIOEvents, PositionSource]:
    T().insert_from_nwbfile(copy_name)   # exception propagates

# Non-SpyglassIngestion tables — derive the key from upstream parents
# (the driver does this via `parents().proj()` joins; the simplest
# manual form when one parent is `Session` is to pass the registered
# Nwbfile name) and call .make(key) directly.
# from spyglass.common.<module> import OtherTable
# OtherTable().make({"nwb_file_name": copy_name})
```

`T().populate(...)` may happen to work for some listed tables whose `make()` body delegates appropriately, but it's not the driver's path and it drops the `entries.yaml` config — so a populate that succeeded under `populate_all_common` can fail under bare `populate()` purely because the config wasn't applied.

## When to reach for this

Any of the following:

- Fresh NWB ingest "completed" but downstream pipelines (position, LFP, spike sorting) can't find rows they expect in common tables.
- `common_usage.InsertError` has entries for the file but the full traceback isn't there.
- You suspect a raw-data issue and need to see the actual failure, not just a label. Common-ingest examples include: malformed experimenter / subject metadata (sex / species / age formatting that the DANDI patcher would normally fix), device / probe-type mismatches between the NWB and the lookup tables, missing `ndx-franklab-novela` / `ndx-pose` / `ndx-optogenetics` / `ndx-ophys-devices` extension objects, or unusual `task_epochs` tag formats (see [ingestion.md](ingestion.md) "TaskEpoch silently drops epochs"). Note that `TrodesPosParams` and other v1-pipeline params live downstream of `populate_all_common` (in `position.v1`, `lfp.v1`, etc.; not in the bundled `table_lists` at `populate_all_common.py:192-247`) — missing-params issues there belong to runtime debugging, not common-ingest debugging.
- `populate_all_common` takes a long time and you want to isolate which specific table is slow or failing.

If the ingest raised immediately (not silently), you already have a traceback — go straight to [runtime_debugging.md](runtime_debugging.md) and match the signature.

## Cross-references

- [runtime_debugging.md](runtime_debugging.md) — failure signatures, cardinality checks, the general populate/make triage flow once you have a traceback
- [ingestion.md](ingestion.md) — `insert_sessions` flow, the raw/copy filename convention, re-ingest with `reinsert=True`
- [setup_troubleshooting.md](setup_troubleshooting.md) — if the failure is install/config-level (imports, connection, base dir). `python skills/spyglass/scripts/verify_spyglass_env.py` is the fast first pass if you're unsure whether you're debugging a populate bug or a broken env.
