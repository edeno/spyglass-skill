# Debugging `populate_all_common`

Triage failures from the common-ingest driver `spyglass.common.populate_all_common.populate_all_common`. If your failure is in a downstream pipeline's `populate()` / `make()` — not in `populate_all_common` specifically — go to [runtime_debugging.md](runtime_debugging.md) instead.

## Contents

- [Why this needs its own page](#why-this-needs-its-own-page)
- [Primary fix — pass `raise_err=True`](#primary-fix--pass-raise_errtrue)
- [Alternative — skip the driver and populate tables directly](#alternative--skip-the-driver-and-populate-tables-directly)
- [When to reach for this](#when-to-reach-for-this)
- [Cross-references](#cross-references)

## Why this needs its own page

`populate_all_common` is the common-ingest driver that calls each common-module table in sequence. By default (`raise_err=False`) it catches exceptions per-table and writes only a short message to `common_usage.InsertError` — the full traceback is lost. This is the single most common cause of "fresh ingest completed but my common tables are missing rows."

The failure is silent from the caller's perspective: no exception, no log line, just missing data downstream. Every other debugging path in [runtime_debugging.md](runtime_debugging.md) assumes you have a traceback to work with. Here you don't — you have to force one.

## Primary fix — pass `raise_err=True`

The function accepts a `raise_err` parameter (see `src/spyglass/common/populate_all_common.py:159-161`); it's the built-in way to propagate tracebacks:

```python
from spyglass.common import populate_all_common
populate_all_common(nwb_file_name, raise_err=True)
```

Once you have the traceback, route back to the matching failure signature in [runtime_debugging.md](runtime_debugging.md#failure-signatures) — usually signature A (`fetch1` cardinality) or H (IntegrityError from a missing ancestor row).

## Alternative — skip the driver and populate tables directly

Useful when you want to isolate which table is failing without re-running the ones that succeeded:

```python
from spyglass.common import Session, Raw, DIOEvents, PositionSource

for T in [Session, Raw, DIOEvents, PositionSource]:
    T().populate({'nwb_file_name': nwb_file_name})   # exception propagates
```

This also works around cases where the per-table exception itself comes from a table that's expensive to re-run from scratch — you only rerun the table that failed.

## When to reach for this

Any of the following:

- Fresh NWB ingest "completed" but downstream pipelines (position, LFP, spike sorting) can't find rows they expect in common tables.
- `common_usage.InsertError` has entries for the file but the full traceback isn't there.
- You suspect a raw-data issue (e.g., missing `trodes_pos_params` row, unusual epoch tag format, malformed NWB module) and need to see the actual failure, not just a label.
- `populate_all_common` takes a long time and you want to isolate which specific table is slow or failing.

If the ingest raised immediately (not silently), you already have a traceback — go straight to [runtime_debugging.md](runtime_debugging.md) and match the signature.

## Cross-references

- [runtime_debugging.md](runtime_debugging.md) — failure signatures, cardinality checks, the general populate/make triage flow once you have a traceback
- [ingestion.md](ingestion.md) — `insert_sessions` flow, the raw/copy filename convention, re-ingest with `reinsert=True`
- [setup_troubleshooting.md](setup_troubleshooting.md) — if the failure is install/config-level (imports, connection, base dir)
