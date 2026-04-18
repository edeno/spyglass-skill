---
name: spyglass
description: Use when working with the Spyglass framework, spyglass.* imports, Spyglass merge tables (PositionOutput, LFPOutput, SpikeSortingOutput, DecodingOutput), Spyglass pipelines or config (SPYGLASS_BASE_DIR, dj_local_conf, insert_sessions), or Spyglass common tables (Session, IntervalList, ElectrodeGroup).
---

# Spyglass Data Analysis Skill

## Role & Core Directives

- **NEVER delete or drop without explicit confirmation**: This database contains irreplaceable neuroscience research data. Never generate destructive operations without first warning the user what will be affected and getting explicit confirmation. Explain what downstream data will be cascade-deleted before providing the code. Destructive operations include:
  - DataJoint: `delete()`, `drop()`, `cautious_delete()`, `super_delete()`, `delete_quick()`
  - Merge-table helpers: `merge_delete()`, `merge_delete_parent()`, `delete_downstream_parts()`
  - File cleanup: `cleanup()`, `delete_orphans()` — these remove analysis files from disk
- **Writes are normal workflow**: Spyglass pipelines require inserting selection rows and populating tables. When the user asks how to run a pipeline, show the full workflow including inserts and populates. Explain what each write does, but don't refuse to show it
- **Environment**: Do not assume Jupyter or remote NWB files — detect the user's setup from context. Spyglass supports local Docker, local data, and remote-lab workflows
- **Verify schema before querying**: Run `Table.describe()` or `Table.heading` to confirm column names before using them in restrictions or fetch calls
- **Source of truth**: When skill references conflict with the repo, trust the repo. Key locations:
  - `src/spyglass/common/` — shared tables; `src/spyglass/<pipeline>/` — pipeline code
  - `src/spyglass/utils/` — SpyglassMixin, _Merge; `notebooks/py_scripts/` — canonical workflows
- **Pip/conda users (no repo checkout)**: The `src/spyglass/` layout lives under the installed package — find it with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`. Notebooks, docs, and `scripts/` are NOT installed; fetch them from GitHub:
  - Notebooks: `https://github.com/LorenFrankLab/spyglass/tree/master/notebooks/py_scripts/`
  - Docs: `https://lorenfranklab.github.io/spyglass/` (or `https://github.com/LorenFrankLab/spyglass/tree/master/docs/src/`)

## First Step: Classify the User's Stage

Before answering, decide which stage the user is in:

1. **Setup/install** → route to `setup_and_config.md` or `00_Setup.py` notebook
2. **NWB ingestion** (first data load) → [ingestion.md](references/ingestion.md) + `02_Insert_Data.py` notebook. Warn that `skip_duplicates=True` is for lookup tables / pipeline reruns only, not raw data — use `reinsert=True` for raw re-ingestion
3. **Concepts/merge tables** (first time using the framework) → this SKILL.md + `04_Merge_Tables.py` notebook
4. **Pipeline work** (running or querying analyses) → merge table workflow below + pipeline reference files

Users may span stages — when in doubt, ask.

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

**Gotcha — too-loose restriction** (common, not merge-specific): a restriction like `{"nwb_file_name": nwb_file}` alone usually matches MANY rows — every interval, every parameter set, every pipeline version for that session. That's what causes `fetch1()`, `merge_get_part()`, `fetch_results()`, and `fetch_nwb()` to raise "expected one row, got N" — the restriction was under-specified. The same footgun applies to any Spyglass or DataJoint table, not just merge tables. Fix: include enough primary-key fields to pick exactly one row (typically `nwb_file_name` + `interval_list_name` + a params name). When unsure what exists, restrict loosely first, print the result, then build a fully-specified key:

```python
# Discover, don't guess — shows you every matching row and its full key
PositionOutput.merge_restrict({"nwb_file_name": nwb_file})
# Once you see the options, pick ONE and build a fully-specified key
key = {"nwb_file_name": nwb_file, "interval_list_name": "02_r1",
       "trodes_pos_params_name": "default"}
```

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

| User question is about... | Load this reference | Canonical notebook | Repo path |
|--------------------------|--------------------|-----|-----------|
| Installation / DB config | [setup_and_config.md](references/setup_and_config.md) | `00_Setup.py` | `scripts/install.py`, `src/spyglass/settings.py` |
| Framework concepts / merge tables | [merge_and_mixin_methods.md](references/merge_and_mixin_methods.md) | `01_Concepts.py`, `04_Merge_Tables.py` | `src/spyglass/utils/` |
| NWB ingestion / insert_sessions | [ingestion.md](references/ingestion.md) | `02_Insert_Data.py` | `src/spyglass/data_import/insert_sessions.py`, `docs/src/Features/Ingestion.md` |
| DataJoint query syntax | [datajoint_api.md](references/datajoint_api.md) | — | — |
| Session, IntervalList, Electrode tables | [common_tables.md](references/common_tables.md) | — | `src/spyglass/common/` |
| Spike sorting pipeline | [spikesorting_pipeline.md](references/spikesorting_pipeline.md) | `10_Spike_SortingV1.py`, `11_Spike_Sorting_Analysis.py` | `src/spyglass/spikesorting/` |
| Position tracking (Trodes / DLC) | [position_pipeline.md](references/position_pipeline.md) | `20_Position_Trodes.py`, `21_DLC.py` | `src/spyglass/position/` |
| Linearization | [other_pipelines.md](references/other_pipelines.md) | `24_Linearization.py` | `src/spyglass/linearization/` |
| LFP / theta / ripple | [lfp_pipeline.md](references/lfp_pipeline.md) | `30_LFP.py`, `31_Theta.py`, `32_Ripple_Detection.py` | `src/spyglass/lfp/`, `src/spyglass/ripple/` |
| Decoding (clusterless / sorted) | [decoding_pipeline.md](references/decoding_pipeline.md) | `40_Extracting_Clusterless_Waveform_Features.py`, `41_Decoding_Clusterless.py`, `42_Decoding_SortedSpikes.py` | `src/spyglass/decoding/` |
| MUA detection | [other_pipelines.md](references/other_pipelines.md) | `50_MUA_Detection.py` | `src/spyglass/mua/` |
| Behavior / MoSeq | [other_pipelines.md](references/other_pipelines.md) | `60_MoSeq.py` | `src/spyglass/behavior/` |
| Cross-table exploration / troubleshooting | [workflows.md](references/workflows.md) | — | — |
| Export for papers / reproducible snapshots | [export.md](references/export.md) | `05_Export.py` | `src/spyglass/common/common_usage.py` |
| Interactive viz / web curation (FigURL) | [figurl.md](references/figurl.md) | — | `src/spyglass/spikesorting/v1/figurl_curation.py`, `src/spyglass/decoding/decoding_merge.py` |
| External packages (SI, PyNWB, DLC) | [dependencies.md](references/dependencies.md) | — | — |

When a reference file and the repo disagree, trust the repo. The `notebooks/py_scripts/` files are the canonical end-to-end examples.
