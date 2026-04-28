# Export Pipeline

## Contents

- [Overview](#overview)
- [Workflow](#workflow)
- [Key Tables and Methods](#key-tables-and-methods)
- [Common Patterns](#common-patterns)

## Overview

The export pipeline produces a reproducible snapshot of tables and files used in a paper or analysis. It logs every fetch during an "export session," then bundles the touched tables and analysis files into an export package.

```python
from spyglass.common.common_usage import ExportSelection, Export
```

Canonical notebook: `notebooks/05_Export.ipynb` (run this one; `notebooks/py_scripts/05_Export.py` is the jupytext mirror kept for PR review). Source: `src/spyglass/common/common_usage.py`.

## Workflow

Export has 3 phases: **log**, **populate**, **package**.

```python
# 1. Log — start an export session, run your analysis, stop the session
ExportSelection().start_export(paper_id="my_paper", analysis_id="analysis_v1")

# ... run any queries/fetches you want included ...
# Queries against tables that inherit SpyglassMixin / ExportMixin
# participate. Custom dj.Manual / dj.Computed tables that don't inherit
# the mixin are NOT logged on direct access — see "Pitfalls" below.

ExportSelection().stop_export()

# 2. Populate — resolve the logged queries into a concrete export set
Export().populate_paper(paper_id="my_paper")

# 3. Package — list the files and tables captured for the paper
paths = ExportSelection().list_file_paths({"paper_id": "my_paper"})
tables = ExportSelection().preview_tables(paper_id="my_paper")
```

## Key Tables and Methods

### `ExportSelection` (Manual)
Tracks which queries/fetches were made during an export session.

- `start_export(paper_id, analysis_id)` — Begin logging
- `stop_export()` — End logging
- `list_file_paths(key, as_dict=True)` — File paths captured for a paper
- `preview_tables(**kwargs)` — Tables captured for a paper
- `show_all_tables(**kwargs)` — Full table set including ancestors
- `paper_export_id(paper_id, return_all=False)` — Lookup export ID by paper
- `get_restr_graph(...)` — Build the dependency graph of logged restrictions

### `Export` (Computed)
Materializes the export from `ExportSelection`.

- `populate_paper(paper_id, ...)` — Populate export for a specific paper
- `prepare_files_for_export(key, n_processes=1)` — **admin-gated, in-place patcher** (NOT just staging). Iterates `Export.File.file_path` (raw and analysis NWB paths captured for the export, plus any unlinked files — `common/common_usage.py:640`) and calls `update_analysis_for_dandi_standard(filepath)` (`utils/dandi_file_updates.py:17`) on each, which opens the file in append mode (`h5py.File(filepath, "a")` at `:42`) and mutates targeted attrs/datasets inside the `with` block (sex / species / age / experimenter formatting; float16 → float32 conversion; missing DynamicTable id columns; source-script filename) — not a whole-file rewrite. After the edit it updates the DataJoint external table + checksum via `_resolve_external_table` (`:79-82`); the location resolves to `"raw"` for files ending in `_.nwb` and `"analysis"` otherwise (`:79`), so the helper updates raw external checksums too.

### `ExportErrorLog` (Manual)
Logs errors encountered during export.

## Pitfalls (read before running an export)

1. **Only one export can be active per Python instance.** Calling `start_export` while another is running silently stops the first. If multiple people share a Python process (e.g., shared notebook kernel), coordinate export sessions or use separate processes.
2. **Direct calls on tables without `SpyglassMixin` aren't logged.** Tables that inherit plain `dj.Manual`/`dj.Computed` (no `ExportMixin` via `SpyglassMixin`) won't write log entries when *they* are the entry point of a fetch — no error, the call is just invisible to `ExportSelection`. The export bundle isn't necessarily missing those tables' rows, though: ancestor tables can still be reached through the restriction graph from logged Spyglass tables and pulled into the export that way. The failure shape to watch for is "I called `MyCustomTable & key` directly and the rows didn't show up in `preview_tables`" — fix by adding `SpyglassMixin` so direct accesses also log.
3. **Compound `&` restrictions inside an export are logged as OR, not AND.** A query built like `(Table & a) & b` during an active export produces an export bundle that includes every row matching `a` OR `b`, not just the intersection. For AND semantics, use `Table & dj.AndList([a, b])` or a single SQL string `Table & "a AND b"`. Verify with `preview_tables(paper_id=...)` after stopping the export.
4. **`Export().populate_paper(paper_id="foo")` overwrites any previous export for the same `paper_id`.** No prompt, no confirmation — the prior bash script and `Export` rows are replaced. Use a new `paper_id` (or a new `analysis_id` within the same paper) for iterative exports.

## Common Patterns

### Logging a paper's queries

```python
sel = ExportSelection()
sel.start_export(paper_id="smith2024", analysis_id="fig2")

# fetch / fetch1 / restrict / join on SpyglassMixin tables during
# this window are captured. fetch_nwb only writes a file-log entry
# when the underlying NWB attribute is "analysis"
# (`utils/mixins/fetch.py:306-310`); fetch_nwb on raw-only tables
# still records the table/restriction but won't log a file row.
from spyglass.position import PositionOutput
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position = (PositionOutput & merge_key).fetch1_dataframe()

sel.stop_export()
Export().populate_paper(paper_id="smith2024")
```

### Previewing what will be exported

```python
# See the tables captured for the paper
ExportSelection().preview_tables(paper_id="smith2024")

# List file paths (analysis NWB files) that will be bundled
ExportSelection().list_file_paths({"paper_id": "smith2024"})
```

### How export logging works

Spyglass tables that inherit `SpyglassMixin` get `ExportMixin` by composition. When an export session is active, calls like `.fetch()`, `.fetch1()`, `.restrict()`, and `.join()` on those tables write log entries to `ExportSelection` via the `_log_fetch` and `_run_with_log` hooks. `.fetch_nwb()` writes a file-log entry only when the underlying NWB attribute is `"analysis"` (`utils/mixins/fetch.py:306-310`) — fetches against tables backed by raw-only NWB attrs still record the table/restriction but don't add a file row. Pass `log_export=False` to skip logging for a specific call.

### Scoping an export to a single analysis

`analysis_id` within a `paper_id` lets you run multiple analyses and export them together or separately. Use `paper_export_id(paper_id, return_all=True)` to see all exports for a paper.

## Preparing an export for DANDI

`Export().populate_paper(...)` produces analysis NWBs that Spyglass
wrote with older pynwb conventions; `pynwb.validate()` and Dandi
upload check against current pynwb rules. Common validation
failures, grouped by what the patcher does and doesn't address:

**Fixed by `update_analysis_for_dandi_standard`** (`utils/dandi_file_updates.py:41-63`):

- `general/source_script` — missing `source_script_file_name` attribute
- `/general/subject/sex` — non-single-letter values (e.g. `"Female"` → `"F"`)
- `/general/subject/species` — `"Rat"` → `"Rattus norvegicus"`
- Missing `/general/subject/age` (default `"P4M/P8M"`)
- Experimenter name format → `"Last, First"`
- Float16 datasets → Float32
- DynamicTable rows missing the `id` ElementIdentifiers column

**NOT covered by the patcher** (you may still see these from `pynwb.validate`):

- `/specifications/...` — unused extension namespaces left on the file
- Multi-dim `SpatialSeries` — legacy multi-LED layout
- Other pynwb-version-specific failures the patcher doesn't enumerate

For these, see the DANDI-prep tracking issue or hand-patch with `h5py` (admin / data-owner only — same caveats as the patcher).

**Run the patcher first.**

```python
from spyglass.common.common_usage import Export, ExportSelection

# `prepare_files_for_export` is the orchestrator — it iterates
# `Export.File.file_path` for the export and calls
# `update_analysis_for_dandi_standard` on each.
# (`update_analysis_for_dandi_standard` is a standalone function in
# `spyglass.utils.dandi_file_updates`, not a method on Export.) Note
# the admin-gate caveat below.
Export().prepare_files_for_export(paper_key)

# Then re-validate. `list_file_paths` returns a list of dicts by
# default (`{"file_path": "..."}`) — pass `as_dict=False` for plain
# strings (`common/common_usage.py:228`). `pynwb.validate` is
# keyword-only on `paths=[...]` in current pynwb (`pynwb/validate.py:131`).
import pynwb
for path in ExportSelection().list_file_paths(paper_key, as_dict=False):
    pynwb.validate(paths=[path])
```

**Admin-permission gate note.** Both layers gate on admin:
`Export.prepare_files_for_export` invokes `make_file_obj_id_unique`
(in `spyglass.utils.dj_helper_fn`), which calls
`LabMember.check_admin_privilege()`, AND
`update_analysis_for_dandi_standard` itself runs
`LabMember().check_admin_privilege(...)` at
`utils/dandi_file_updates.py:36-38`. There is no non-admin code path
through this helper. If you are a non-admin preparing your own
export, work with a lab admin to run it. **Don't manually edit
analysis files outside this admin-gated helper** — the helper
opens the NWB in append mode AND updates the DataJoint external
table / checksum via `_resolve_external_table`
(`utils/dandi_file_updates.py:79-82`); a hand-edit that skips that
re-checksum step will trip every subsequent `fetch_nwb()` on the
file. The DANDI-prep tracking issue lists the individual h5py
patch scripts that implement each sub-fix; if you need to run them
out-of-band, route the result back through the external-table
resolve afterwards.
