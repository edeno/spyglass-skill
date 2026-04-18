---
name: spyglass
description: Use when working with the Spyglass framework, Spyglass merge tables (PositionOutput, LFPOutput, SpikeSortingOutput, DecodingOutput), Spyglass pipelines (spike sorting, position tracking, LFP, decoding, linearization, ripple detection), Spyglass setup/config (SPYGLASS_BASE_DIR, dj_local_conf), querying Spyglass common tables (Session, IntervalList, ElectrodeGroup), or Spyglass NWB ingestion (insert_sessions).
---

# Spyglass Data Analysis Skill

## Role & Core Directives

- **NEVER delete or drop without explicit confirmation**: This database contains irreplaceable neuroscience research data. Never generate `delete()`, `drop()`, `cautious_delete()`, or any destructive operation without first warning the user what will be affected and getting explicit confirmation. Explain what downstream data will be cascade-deleted before providing the code
- **Writes are normal workflow**: Spyglass pipelines require inserting selection rows and populating tables. When the user asks how to run a pipeline, show the full workflow including inserts and populates. Explain what each write does, but don't refuse to show it
- **Environment**: Do not assume Jupyter or remote NWB files — detect the user's setup from context. Spyglass supports local Docker, local data, and remote-lab workflows
- **Verify schema when unsure**: Use `Table.describe()` or `Table.heading` to confirm column names if you can't determine them from source code or skill references
- **Source of truth**: When skill references conflict with the repo, trust the repo. Key locations:
  - `src/spyglass/common/` — shared tables; `src/spyglass/<pipeline>/` — pipeline code
  - `src/spyglass/utils/` — SpyglassMixin, _Merge; `notebooks/py_scripts/` — canonical workflows

## Merge Tables — The Key Concept

Merge tables consolidate outputs from multiple pipeline versions into a single `merge_id` interface. Not all part tables are merge tables — `Session.Experimenter` is a regular part table.

**Two ways to access merge table data:**

**Direct access** (DecodingOutput accepts friendly keys and resolves internally):
```python
results = DecodingOutput.fetch_results(key)  # no manual merge resolution needed
model = DecodingOutput.fetch_model(key)
# Still raises ValueError if key matches 0 or >1 entries
```

**Manual merge resolution** (when you need the merge_id explicitly):
```python
part = MergeTable.merge_get_part(key)       # raises ValueError if 0 or >1 match
merge_key = part.fetch1("KEY")              # {'merge_id': 'abc123-...'}
data = (MergeTable & merge_key).fetch1_dataframe()  # for position, LFP, linearization
```

**Gotcha**: `merge_get_part()` raises `ValueError` on zero or multiple matches. Use `multi_source=True` to allow multiple.

**Gotcha**: Don't restrict merge tables with friendly keys directly — use `merge_get_part()`, `merge_restrict()`, or `<<`.

### All Pipelines

| Output Table | Import Path | Type | Data Access |
|-------------|-------------|------|-------------|
| `PositionOutput` | `spyglass.position` | Merge | `.fetch1_dataframe()`, `.fetch_pose_dataframe()` (DLC/imported only) |
| `LFPOutput` | `spyglass.lfp` | Merge | `.fetch1_dataframe()` |
| `SpikeSortingOutput` | `spyglass.spikesorting.spikesorting_merge` | Merge | `.get_spike_times()`, `.get_firing_rate()`, `.get_sorting()` |
| `DecodingOutput` | `spyglass.decoding` | Merge | `.fetch_results()`, `.fetch_model()`, `.fetch_position_info()` |
| `LinearizedPositionOutput` | `spyglass.linearization.merge` | Merge | `.fetch1_dataframe()` |
| `RippleTimesV1` | `spyglass.ripple.v1` | Direct | `.fetch1_dataframe()` |
| `MuaEventsV1` | `spyglass.mua.v1` | Direct | `.fetch1_dataframe()` |

Common tables: `from spyglass.common import Session, IntervalList, Nwbfile, ElectrodeGroup, Electrode, Raw`

All tables inherit `fetch_nwb()`, `<<`/`>>`, and other SpyglassMixin methods — see [references/merge_and_mixin_methods.md](references/merge_and_mixin_methods.md).

## Quick Start

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                                  # List sessions — find your nwb_file_name
IntervalList & {"nwb_file_name": nwb_file}               # Find intervals for that session
```

```python
from spyglass.position import PositionOutput

# Discover what exists, then build your key
PositionOutput.merge_restrict({"nwb_file_name": nwb_file})
key = {"nwb_file_name": nwb_file, "interval_list_name": interval_name,
       "trodes_pos_params_name": "default"}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

merge_ids = SpikeSortingOutput().get_restricted_merge_ids(
    {"nwb_file_name": nwb_file, "interval_list_name": interval_name}, sources=["v1"])
for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
```


## Reference Routing

For simple data queries, the examples above are usually sufficient. For deeper questions, load the right reference:

| User question is about... | Load this reference | Or inspect this repo path |
|--------------------------|--------------------|-----------------------|
| DataJoint query syntax | [datajoint_api.md](references/datajoint_api.md) | — |
| Session, IntervalList, Electrode tables | [common_tables.md](references/common_tables.md) | `src/spyglass/common/` |
| _Merge / SpyglassMixin methods | [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) | `src/spyglass/utils/` |
| Position tracking pipeline | [position_pipeline.md](references/position_pipeline.md) | `src/spyglass/position/` |
| LFP filtering / band analysis | [lfp_pipeline.md](references/lfp_pipeline.md) | `src/spyglass/lfp/` |
| Spike sorting pipeline | [spikesorting_pipeline.md](references/spikesorting_pipeline.md) | `src/spyglass/spikesorting/` |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) | `src/spyglass/decoding/` |
| Linearization, ripple, MUA, behavior | [other_pipelines.md](references/other_pipelines.md) | `src/spyglass/{linearization,ripple,mua,behavior}/` |
| NWB ingestion / insert_sessions | [other_pipelines.md](references/other_pipelines.md) | `src/spyglass/data_import/`, `docs/src/Features/Ingestion.md` |
| Installation / DB config / directories | [setup_and_config.md](references/setup_and_config.md) | `scripts/install.py`, `src/spyglass/settings.py` |
| External packages (SI, PyNWB, DLC) | [dependencies.md](references/dependencies.md) | — |
| End-to-end analysis workflows | [workflows.md](references/workflows.md) | `notebooks/py_scripts/` |

When a reference file and the repo disagree, trust the repo. For canonical examples, inspect `notebooks/py_scripts/` directly.
