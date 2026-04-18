# Custom Pipeline Authoring

## Contents

- [Overview](#overview)
- [Five-Step Decision Tree](#five-step-decision-tree)
- [Non-Negotiables](#non-negotiables)
- [Canonical Schema Skeleton](#canonical-schema-skeleton)
- [Extending an Existing Pipeline](#extending-an-existing-pipeline)
- [Building from Ingested Tables](#building-from-ingested-tables)
- [AnalysisNwbfile Storage Pattern](#analysisnwbfile-storage-pattern)
- [Merge Table Guardrail](#merge-table-guardrail)
- [Further Reading in Spyglass docs](#further-reading-in-spyglass-docs)

## Overview

This reference is for **authoring** a new pipeline that plugs into Spyglass — not for *using* existing pipelines. Typical authoring cases:

- You want to run a new analysis downstream of an existing merge table (`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`).
- You want to run a new analysis on raw/ingested data directly (`Session`, `Raw`, `IntervalList`, `RawPosition`, `Electrode`).

Both cases follow the same DataJoint tier convention: **parameters → selection → computed**, with outputs stored in an `AnalysisNwbfile`. A merge table is only warranted when multiple interchangeable versions of the same analysis need a unified downstream interface.

Authoritative source for these patterns is `docs/src/ForDevelopers/` in the spyglass repo — links at the bottom of this file.

## Five-Step Decision Tree

For each new step in your analysis, pick the smallest option that fits:

1. **Use an existing upstream table directly** — if your analysis is a one-off and doesn't need to be re-run with different parameters, you may not need any new tables at all. Just query.
2. **Add a preprocessing / grouping table** (`dj.Manual`) — when you need to combine units, intervals, or electrodes from the raw tables into analysis-ready sets (e.g., "units from these tetrodes during this epoch").
3. **Add a Parameters table** (`dj.Lookup` with `contents`) — any tunable value the analysis reads. Name ends in `Parameters` or `Params`.
4. **Add a Selection table** (`dj.Manual`) — pairs a specific input (upstream key) with a specific parameter set. Name ends in `Selection`. This is the row you `insert1` before calling `populate`.
5. **Add a Computed table** (`dj.Computed`) with a `make()` method — takes the Selection row, runs the analysis, writes output (typically to an AnalysisNwbfile) and inserts the row. Part tables hang off this for row-wise results.

**Add a merge table only if** you end up with multiple interchangeable implementations of the same analysis (e.g., `FooV1`, `FooV2`, `FooImported`) and downstream consumers want a single `merge_id` interface. Do not introduce a merge table for a single-source pipeline — it adds complexity without benefit.

## Non-Negotiables

These are the rules most likely to cause mysterious failures if ignored:

1. **`SpyglassMixin` must be first in inheritance order**, before `dj.Manual`/`Lookup`/`Computed`/`Imported`/`Part`. From `docs/src/ForDevelopers/Classes.md`: "SpyglassMixin must be the first class inherited to ensure method overrides work correctly." Part tables use `SpyglassMixinPart` instead.
2. **Choose the right tier**. `dj.Lookup` for params (contents baked into the class), `dj.Manual` for selection/grouping tables the user populates, `dj.Computed` with `make()` for analysis outputs, `dj.Imported` for tables populated by walking an NWB file. See the tier list in `TableTypes.md`.
3. **Keep Parameters, Selection, and Computed tables separate.** Combining them (e.g., putting a `params` blob directly on a Computed table) breaks reproducibility and makes re-runs with different params impossible without deleting rows.
4. **Write analysis outputs to `AnalysisNwbfile`** when the result is sizeable (arrays, waveforms, posteriors). Keep only small metadata in DataJoint columns. Tables should reference exactly one AnalysisNwbfile table — Spyglass validates this on declaration.
5. **Only introduce a merge table for genuinely multi-source outputs.** If you only have one implementation, skip the merge table and let downstream tables FK-ref your Computed table directly.
6. **Never use `skip_duplicates=True` when your `make()` inserts into `IntervalList`.** Spyglass's built-in pipelines protect against orphaned-interval drift by nuking orphans on every delete — but custom `make()`s that call `IntervalList.insert1(..., skip_duplicates=True)` bypass that protection. Scenario: you delete the downstream entry, leave the interval row in place, re-run `make()` — the new computation silently attaches to the OLD interval row. Silent wrong data. If your pipeline needs a new `IntervalList` row, either insert without `skip_duplicates` (let it raise) or delete the old interval first. See `docs/src/ForDevelopers/Management.md`.

## Canonical Schema Skeleton

Minimal authoring module. This compiles and follows every non-negotiable. Structure derived from the canonical example in `docs/src/ForDevelopers/Schema.md` lines 43–201; part-table syntax uses `SpyglassMixinPart` as documented in `docs/src/ForDevelopers/Classes.md` line 206.

```python
import datajoint as dj

from spyglass.common import IntervalList, Session  # noqa: F401
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.utils import SpyglassMixin, SpyglassMixinPart

schema = dj.schema("my_username_myanalysis")

@schema
class MyAnalysisParams(SpyglassMixin, dj.Lookup):
    """Parameters for MyAnalysis. Lookup tier: contents baked in."""

    definition = """
    myanalysis_params_name: varchar(32)
    ---
    myanalysis_params: blob
    """
    contents = [
        ["default", {"window_s": 0.5, "threshold": 3.0}],
    ]

@schema
class MyAnalysisSelection(SpyglassMixin, dj.Manual):
    """One row per (session interval, params) pair to analyze."""

    definition = """
    -> Session
    -> IntervalList
    -> MyAnalysisParams
    """

@schema
class MyAnalysis(SpyglassMixin, dj.Computed):
    """Computed analysis; output stored in an AnalysisNwbfile."""

    definition = """
    -> MyAnalysisSelection
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    class Unit(SpyglassMixinPart):
        definition = """
        -> master
        unit_id: int
        ---
        value: float
        """

    def make(self, key):
        params = (MyAnalysisParams & key).fetch1("myanalysis_params")
        # ... compute using upstream data + params ...
        nwb_file_name = (Session & key).fetch1("nwb_file_name")

        # Builder context manages CREATE -> POPULATE -> REGISTER for you.
        # Do NOT mix builder with separate create()/add()/add_nwb_object()
        # calls — that path raises "Cannot call add_nwb_object() in state:
        # REGISTERED" (see AnalysisTables.md troubleshooting).
        with AnalysisNwbfile().build(nwb_file_name) as builder:
            result_object_id = builder.add_nwb_object(
                result_array, table_name="result"
            )
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "result_object_id": result_object_id,
        })
        self.Unit().insert(part_rows, skip_duplicates=True)
```

Master insert must come before part inserts. Always call `self.insert1(key)` first.

## Extending an Existing Pipeline

When your analysis consumes output from an existing merge table, FK-ref the merge table as an upstream key.

```python
from spyglass.position import PositionOutput

@schema
class PosDerivedAnalysis(SpyglassMixin, dj.Computed):
    definition = """
    -> PositionOutput
    -> MyAnalysisParams
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    def make(self, key):
        # Option A: require a specific upstream source (safer)
        parent = PositionOutput().merge_get_parent(key)
        if parent.camel_name != "TrodesPosV1":
            raise ValueError("PosDerivedAnalysis requires TrodesPosV1")
        position_df = (PositionOutput & key).fetch1_dataframe()
        # ... compute ...

        # Option B: accept any source (use fetch_data / fetch1_dataframe)
        # position_df = (PositionOutput & key).fetch1_dataframe()
```

Same pattern applies to `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, `LinearizedPositionOutput`.

## Building from Ingested Tables

When your analysis consumes raw/ingested data directly, FK-ref the relevant common table(s). A grouping table is often the first step.

```python
from spyglass.common import Session, IntervalList, ElectrodeGroup

@schema
class MyElectrodeGroup(SpyglassMixin, dj.Manual):
    """Set of electrodes to analyze together."""

    definition = """
    my_group_name: varchar(32)
    -> Session
    """

    class Electrode(SpyglassMixinPart):
        definition = """
        -> master
        -> ElectrodeGroup
        """

@schema
class MyRawAnalysis(SpyglassMixin, dj.Computed):
    definition = """
    -> MyElectrodeGroup
    -> IntervalList
    -> MyAnalysisParams
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    def make(self, key):
        # fetch raw data restricted to the group's electrodes + interval
        ...
```

Common upstream tables for authoring: `Session`, `IntervalList`, `Raw`, `RawPosition`, `Electrode`, `ElectrodeGroup`, `LabMember`, `DIOEvents`.

## AnalysisNwbfile Storage Pattern

Outputs too large for DataJoint columns (arrays, waveforms, posteriors, timeseries) go into an AnalysisNwbfile. The DataJoint row stores only the filename and object IDs.

**Use the `build()` context manager** for all analysis-file writes. It handles the CREATE → POPULATE → REGISTER lifecycle atomically and prevents the common "Cannot call add_nwb_object() in state: REGISTERED" error that arises when separate `create()`, `add_nwb_object()`, `add()` calls are interleaved.

```python
from spyglass.common.common_nwbfile import AnalysisNwbfile

# Inside a Computed table's make(key):
nwb_file_name = (Session & key).fetch1("nwb_file_name")

# table_name is the NAME the object gets in the NWB scratch space
# (the retrieval key), not a description. DataFrames and numpy arrays
# are auto-wrapped into DynamicTable / ScratchData respectively.
# ALWAYS pass table_name explicitly — default is "pandas_table", so
# multiple add_nwb_object() calls without distinct names collide in
# scratch space and later retrieval fails.
with AnalysisNwbfile().build(nwb_file_name) as builder:
    obj_id = builder.add_nwb_object(my_numpy_array, table_name="result")
    analysis_file_name = builder.analysis_file_name
# File is auto-registered on context exit. Builder methods cannot be
# called after exit — the state machine blocks it.

self.insert1({**key, "analysis_file_name": analysis_file_name,
              "result_object_id": obj_id})
```

**Anti-pattern (do not do this):**

```python
# ❌ Raises "Cannot call add_nwb_object() in state: REGISTERED"
analysis_file_name = AnalysisNwbfile().create(nwb_file_name)
AnalysisNwbfile().add(nwb_file_name, analysis_file_name)  # registers
AnalysisNwbfile().add_nwb_object(...)                      # fails
```

**Constraint**: a table may reference only one AnalysisNwbfile table (either `common.common_nwbfile.AnalysisNwbfile` or a custom per-user one, not both). Spyglass validates this on declaration.

## Merge Table Guardrail

Skip this unless you have **multiple interchangeable implementations** of the same analysis that downstream consumers need to treat uniformly. Signals it's warranted:

- Two independently-written versions (`MyAnalysisV1`, `MyAnalysisV2`) exist and both should remain usable.
- You want users to be able to import the same source analysis from outside Spyglass (`MyAnalysisImported`) alongside the computed one.
- A downstream table needs a single `merge_id` FK regardless of which implementation produced the row.

If none of these apply, let downstream tables FK-ref your Computed table directly. Adding a merge table for a single-source pipeline adds complexity (UUID indirection, `merge_get_part` calls) with no benefit.

When you do add one, follow the conventions in `TableTypes.md`: name it `{Pipeline}Output`, use tier `_Merge`, primary key `merge_id: uuid`, non-primary key `source: varchar`.

## Further Reading in Spyglass docs

All authoritative; this reference summarizes them for skill-time lookup:

- `docs/src/ForDevelopers/CustomPipelines.md` — full worked example, FK-ref syntax gotchas, `make()` conventions.
- `docs/src/ForDevelopers/TableTypes.md` — tier choice cheat-sheet, naming conventions for each role.
- `docs/src/ForDevelopers/Schema.md` — canonical schema file skeleton, import ordering, definition-string grammar.
- `docs/src/ForDevelopers/Classes.md` — SpyglassMixin rules, AnalysisMixin methods, part-table inheritance.
- `docs/src/ForDevelopers/Reuse.md` — formatting (black/isort/ruff), NumPy docstring style, pre-commit hooks.
