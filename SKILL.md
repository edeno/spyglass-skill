---
name: spyglass
description: Work with the Spyglass neuroscience data analysis framework. Trigger when user mentions Spyglass, PositionOutput, LFPOutput, SpikeSortingOutput, DecodingOutput, merge tables in a Spyglass context, or specific Spyglass pipelines (spike sorting, position tracking, LFP, decoding, linearization, ripple detection).
---

# Spyglass Data Analysis Skill

## Role & Core Directives

- **Read-only by default**: Never generate code that writes to the database (`insert`, `populate`, `delete`, etc.) unless the user explicitly requests it
- **NEVER delete or drop without explicit confirmation**: This database contains irreplaceable neuroscience research data. Never generate `delete()`, `drop()`, `cautious_delete()`, or any destructive operation without first warning the user what will be affected and getting explicit confirmation. Even when the user asks for deletion, explain what downstream data will be cascade-deleted before providing the code
- **Teaching approach**: Show code, expected output shape, and explain (≤200 words unless asked for more)
- **Best practices**: Use PEP8, descriptive variable names, prefer DataJoint operators over raw SQL
- **Environment**: Do not assume Jupyter or remote NWB files — detect the user's setup from context. Spyglass supports local Docker, local data, and remote-lab workflows
- **Progressive exploration**: Start broad (what sessions exist?), then narrow (what data for this session?)
- **Verify schema before querying**: Always run `Table.describe()` or `Table.heading` to confirm column names before using them in restrictions or fetch calls
- **Source of truth**: When skill reference files conflict with the actual repo, trust the repo. The bundled references here are a starting point, not the final word. Key repo locations:
  - `src/spyglass/common/` — shared tables (Session, IntervalList, Electrode, etc.)
  - `src/spyglass/<pipeline>/` — pipeline code (position, lfp, spikesorting, decoding, linearization, ripple, mua, behavior)
  - `src/spyglass/utils/` — SpyglassMixin, _Merge, and helper utilities
  - `notebooks/py_scripts/` — canonical analysis workflows
  - `tests/` — behavior checks and test fixtures
  - `docs/` — user-facing documentation

## DataJoint Quick Reference

### Core Operators

| Operator | Name | Example |
|----------|------|---------|
| `&` | Restriction | `Session & {'nwb_file_name': 'file.nwb'}` |
| `*` | Join | `Session * Subject` |
| `.proj()` | Projection | `Session.proj('nwb_file_name', 'subject_id')` |
| `.fetch()` | Fetch all | `(Session & key).fetch(as_dict=True)` |
| `.fetch1()` | Fetch one | `(Session & key).fetch1()` |
| `.aggr()` | Aggregation | `Table1.aggr(Table2, n='count(*)')` |

### Spyglass-Specific Operators

| Operator | Name | Example |
|----------|------|---------|
| `<<` | Upstream restrict | `PositionOutput() << "nwb_file_name = 'file.nwb'"` |
| `>>` | Downstream restrict | `Session() >> 'trodes_pos_params_name="default"'` |
| `.restrict_by()` | Explicit restrict | `Table().restrict_by(restr, direction="up")` |

### Table Inspection

```python
Table.describe()          # Schema and primary keys
Table.heading             # All columns as dict
Table.parents()           # Parent tables
Table.children()          # Child tables
```

## Part Tables and Merge Tables

**This is the most important concept in Spyglass.** Almost every pipeline uses this pattern.

### What Are Part Tables?

A **part table** is a sub-table owned by a **master table**. The master defines the primary key; each part table adds its own columns. Part tables share the master's primary key and add foreign keys to other tables.

Part tables are a general DataJoint concept used throughout Spyglass. For example, `Session.Experimenter` is a part table that links sessions to lab members — this is a regular part table, not a merge table.

### What Are Merge Tables?

A **merge table** is a *specific Spyglass convention* that uses part tables to consolidate outputs from **multiple pipeline versions** into a single interface. Each part table corresponds to a different pipeline version or data source. Not all part tables are merge tables — merge tables are master tables whose *only purpose* is to assign UUIDs across multiple upstream pipeline versions.

```
PositionOutput (merge master)     # Only has merge_id as primary key
├── PositionOutput.TrodesPosV1      # Links merge_id → TrodesPosV1's keys
├── PositionOutput.DLCPosV1         # Links merge_id → DLCPosV1's keys
├── PositionOutput.CommonPos        # Links merge_id → IntervalPositionInfo's keys
└── PositionOutput.ImportedPose     # Links merge_id → ImportedPose's keys
```

**Why merge tables exist**: Spyglass has evolved over time. Position data might come from Trodes LED tracking, DeepLabCut pose estimation, or imported pose data. Rather than making downstream code handle each source differently, a merge table gives them all the same `merge_id` interface.

**Key rule**: The `merge_id` is a UUID. Never type it manually — always obtain it programmatically.

### The Merge Table Workflow

All merge tables share the same first 3 steps — get a `merge_id`. Step 4 depends on the pipeline:

```python
# Step 1: Build a restriction key with human-readable fields
key = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "pos 1 valid times",
    "trodes_pos_params_name": "default",
}

# Step 2: Find which part table contains this data
part = MergeTable.merge_get_part(key)
# Returns the specific part table (e.g., PositionOutput.TrodesPosV1)

# Step 3: Get the merge_id from the part table
merge_key = part.fetch1("KEY")
# Returns: {'merge_id': 'abc123-...'}

# Step 4: Fetch data — method depends on the merge table:
#   PositionOutput, LFPOutput, LinearizedPositionOutput:
data = (MergeTable & merge_key).fetch1_dataframe()
#   DecodingOutput: use fetch_results(), fetch_model(), fetch_position_info()
#   SpikeSortingOutput: use get_spike_times(), get_firing_rate(), get_sorting()
```

**Not all merge tables use `fetch1_dataframe()`**. `DecodingOutput` stores results as xarray Datasets on disk (use `DecodingOutput.fetch_results(key)`). `SpikeSortingOutput` has specialized helpers like `get_spike_times()` and `get_firing_rate()`. See the pipeline-specific reference files for the correct data access pattern.

**Common mistake #1**: Trying to restrict a merge table directly with friendly keys like `nwb_file_name`. Merge tables only have `merge_id` as their primary key — you must go through `merge_get_part()` first. (Note: `merge_restrict()` and `<<` work with friendly keys because they traverse the dependency graph internally.)

**Common mistake #2**: `merge_get_part()` raises `ValueError` if zero or multiple sources match (when `multi_source=False`, the default). Wrap in try/except:
```python
try:
    part = MergeTable.merge_get_part(key)
    merge_key = part.fetch1("KEY")
except ValueError:
    print("No data (or multiple sources) found — refine your key or use multi_source=True")
```

**When multiple sources exist**: Use `multi_source=True`:
```python
parts = MergeTable.merge_get_part(key, multi_source=True)
```

### All Pipelines and Their Outputs

| Output Table | Import Path | Type | Data Access (Step 4) |
|-------------|-------------|------|---------------------|
| `PositionOutput` | `spyglass.position` | Merge | `.fetch1_dataframe()`, `.fetch_pose_dataframe()` |
| `LFPOutput` | `spyglass.lfp` | Merge | `.fetch1_dataframe()` |
| `SpikeSortingOutput` | `spyglass.spikesorting.spikesorting_merge` | Merge | `.get_spike_times()`, `.get_firing_rate()`, `.get_sorting()` |
| `DecodingOutput` | `spyglass.decoding` | Merge | `.fetch_results()`, `.fetch_model()`, `.fetch_position_info()` |
| `LinearizedPositionOutput` | `spyglass.linearization.merge` | Merge | `.fetch1_dataframe()` |
| `RippleTimesV1` | `spyglass.ripple.v1` | Direct | `.fetch1_dataframe()` |
| `MuaEventsV1` | `spyglass.mua.v1` | Direct | `.fetch1_dataframe()` |

Common tables root: `from spyglass.common import Session, IntervalList, Nwbfile, ElectrodeGroup, Electrode, Raw`

All tables also inherit `fetch_nwb()` (load NWB objects), `<<`/`>>` (upstream/downstream restrict), and other SpyglassMixin methods — see [references/merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) for the full list.

## Quick Start Examples

### Find sessions and explore data

```python
from spyglass.common import Session, IntervalList

# List sessions
Session.fetch(limit=10)

# Find intervals for a session
nwb_file = "j1620210710_.nwb"
IntervalList & {"nwb_file_name": nwb_file}
```

### Get position data

```python
from spyglass.position import PositionOutput

key = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "pos 1 valid times",
    "trodes_pos_params_name": "default",
}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```

### Get spike times

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# Using friendly keys
merge_ids = SpikeSortingOutput().get_restricted_merge_ids(
    {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"},
    sources=["v1"],  # recommended: avoid legacy v0 results
)
for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
```

### Get LFP data

```python
from spyglass.lfp import LFPOutput

key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "lfp_tets_j16",
    "target_interval_list_name": "02_r1",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": 30000,
}
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

## Communication Style

1. Analogy → formal term → one-sentence definition
2. Use markdown for structure
3. Keep explanations ≤200 words unless user requests more
4. Show code for operational questions; for conceptual questions, prioritize explanation over code
5. When the user asks "how do I get X data", show the merge table workflow (steps 1-3), then the correct data access method for that specific pipeline

## Reference Files

Load a pipeline reference when the user needs to understand pipeline steps, populate tables, debug pipeline-specific errors, or work with parameter tables. For simple "get data" questions, the examples above are usually sufficient.

- **[references/datajoint_api.md](references/datajoint_api.md)**: Complete DataJoint and Spyglass operator reference with examples
- **[references/common_tables.md](references/common_tables.md)**: All common schema tables, their keys, fields, and relationships
- **[references/merge_and_mixin_methods.md](references/merge_and_mixin_methods.md)**: Full _Merge and SpyglassMixin method signatures and usage
- **[references/position_pipeline.md](references/position_pipeline.md)**: Position tracking pipeline (Trodes, DLC, imported pose)
- **[references/lfp_pipeline.md](references/lfp_pipeline.md)**: LFP filtering, artifact detection, band analysis
- **[references/spikesorting_pipeline.md](references/spikesorting_pipeline.md)**: Spike sorting v1 pipeline end-to-end
- **[references/decoding_pipeline.md](references/decoding_pipeline.md)**: Clusterless and sorted spikes decoding
- **[references/other_pipelines.md](references/other_pipelines.md)**: Linearization, ripple, MUA, behavior pipelines
- **[references/workflows.md](references/workflows.md)**: Step-by-step workflows for common analysis tasks
- **[references/dependencies.md](references/dependencies.md)**: External packages (SpikeInterface, PyNWB, non_local_detector, DLC, etc.)
- **[references/setup_and_config.md](references/setup_and_config.md)**: Installation methods, database configuration, directory setup, and troubleshooting
