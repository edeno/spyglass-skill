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

Canonical notebook: `notebooks/py_scripts/05_Export.py`. Source: `src/spyglass/common/common_usage.py`.

## Workflow

Export has 3 phases: **log**, **populate**, **package**.

```python
# 1. Log — start an export session, run your analysis, stop the session
ExportSelection().start_export(paper_id="my_paper", analysis_id="analysis_v1")

# ... run any queries/fetches you want included ...
# All fetch/fetch1/fetch_nwb calls are logged while the session is active.
# Every query participates in the export via SpyglassMixin/ExportMixin.

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
- `prepare_files_for_export(key, n_processes=1)` — Stage files for transfer

### `ExportErrorLog` (Manual)
Logs errors encountered during export.

## Pitfalls (read before running an export)

1. **Only one export can be active per Python instance.** Calling `start_export` while another is running silently stops the first. If multiple people share a Python process (e.g., shared notebook kernel), coordinate export sessions or use separate processes.
2. **Every logged table must inherit `SpyglassMixin`.** Custom tables that inherit plain `dj.Manual`/`dj.Computed` are silently excluded from the export — no error, just missing data. This is one of the reasons the authoring reference puts SpyglassMixin first in the non-negotiables list.
3. **Compound `&` restrictions inside an export are logged as OR, not AND.** A query built like `(Table & a) & b` during an active export produces an export bundle that includes every row matching `a` OR `b`, not just the intersection. For AND semantics, use `Table & dj.AndList([a, b])` or a single SQL string `Table & "a AND b"`. Verify with `preview_tables(paper_id=...)` after stopping the export.
4. **`Export().populate_paper(paper_id="foo")` overwrites any previous export for the same `paper_id`.** No prompt, no confirmation — the prior bash script and `Export` rows are replaced. Use a new `paper_id` (or a new `analysis_id` within the same paper) for iterative exports.

## Common Patterns

### Logging a paper's queries

```python
sel = ExportSelection()
sel.start_export(paper_id="smith2024", analysis_id="fig2")

# Any fetch_nwb, fetch, fetch1 during this window is captured
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

Every Spyglass table inherits `ExportMixin`. When an export session is active, calls like `.fetch()`, `.fetch1()`, `.fetch_nwb()`, `.restrict()`, and `.join()` write log entries to `ExportSelection` via the `_log_fetch` and `_run_with_log` hooks. Pass `log_export=False` to skip logging for a specific call.

### Scoping an export to a single analysis

`analysis_id` within a `paper_id` lets you run multiple analyses and export them together or separately. Use `paper_export_id(paper_id, return_all=True)` to see all exports for a paper.
