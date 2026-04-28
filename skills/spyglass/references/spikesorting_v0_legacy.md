# Spike Sorting v0 (Legacy)

v0 is legacy. All new work uses the v1 pipeline — see [spikesorting_v1_pipeline.md](spikesorting_v1_pipeline.md). This file covers what you need to know if you're reading existing v0 code or querying existing v0 sortings through `SpikeSortingOutput`.

## Contents

- [When You'll Encounter v0](#when-youll-encounter-v0)
- [v0 vs v1 API Divergences](#v0-vs-v1-api-divergences)
- [Class-name Collisions to Watch For](#class-name-collisions-to-watch-for)
- [Querying Existing v0 Sortings](#querying-existing-v0-sortings)

## When You'll Encounter v0

v0 sortings exist in most long-running labs' databases — they were produced before the v1 pipeline landed, and re-running them under v1 is not required for downstream use. The `SpikeSortingOutput.CuratedSpikeSorting` part table exposes those v0 entries so they participate in the same merge-table interface that v1 sortings use (`get_spike_times`, `get_recording`, `get_sorting`, etc.). If a user's code imports from `spyglass.spikesorting.v0.*`, they are almost certainly reading or querying pre-existing data rather than producing new sortings.

## v0 vs v1 API Divergences

- **Imports**: `spyglass.spikesorting.v1.*` (current) vs `spyglass.spikesorting.v0.*` (legacy). Module names also differ — `v1/recording.py`, `v1/sorting.py`, `v1/curation.py`, `v1/metric_curation.py` vs a different v0 layout (`v0/spikesorting_recording.py`, `v0/spikesorting_sorting.py`, `v0/spikesorting_curation.py`, `v0/spikesorting_artifact.py`).
- **Selection inserts**: v1 uses the `insert_selection(...)` classmethod convention (`SpikeSortingSelection.insert_selection(key)`). v0 uses plain `.insert1(key)` on the selection table. Using `insert1` on a v1 table skips the validation/UUID generation `insert_selection` performs.
- **Curation**: v1 has a dedicated `CurationV1` table with `insert_curation(...)`, linking back to a specific `SpikeSorting` row via `sorting_id`. v0 threads curation through separate tables (`Curation`, `WaveformSelection`, `Waveforms`, `MetricSelection`, `QualityMetrics`, `AutomaticCurationSelection`, `AutomaticCuration`, `CuratedSpikeSortingSelection`, `CuratedSpikeSorting`).
- **Class-name collisions**: several names exist in both v0 and v1 modules. When reading code, confirm which module is imported at the top of the file — see the table below.

## Class-name Collisions to Watch For

These class names exist in BOTH `spyglass.spikesorting.v0.*` and `spyglass.spikesorting.v1.*`. They are distinct tables with different schemas and different insert conventions — always disambiguate by import path before reasoning about a table.

| Class name | v1 import | v0 import |
| ------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------- |
| `SortGroup` | `spyglass.spikesorting.v1.recording` | `spyglass.spikesorting.v0.spikesorting_recording` |
| `SpikeSortingPreprocessingParameters` | `spyglass.spikesorting.v1.recording` | `spyglass.spikesorting.v0.spikesorting_recording` |
| `SpikeSortingRecordingSelection` | `spyglass.spikesorting.v1.recording` | `spyglass.spikesorting.v0.spikesorting_recording` |
| `SpikeSortingRecording` | `spyglass.spikesorting.v1.recording` | `spyglass.spikesorting.v0.spikesorting_recording` |
| `ArtifactDetectionParameters` | `spyglass.spikesorting.v1.artifact` | `spyglass.spikesorting.v0.spikesorting_artifact` |
| `ArtifactDetectionSelection` | `spyglass.spikesorting.v1.artifact` | `spyglass.spikesorting.v0.spikesorting_artifact` |
| `ArtifactDetection` | `spyglass.spikesorting.v1.artifact` | `spyglass.spikesorting.v0.spikesorting_artifact` |
| `SpikeSorterParameters` | `spyglass.spikesorting.v1.sorting` | `spyglass.spikesorting.v0.spikesorting_sorting` |
| `SpikeSortingSelection` | `spyglass.spikesorting.v1.sorting` | `spyglass.spikesorting.v0.spikesorting_sorting` |
| `SpikeSorting` | `spyglass.spikesorting.v1.sorting` | `spyglass.spikesorting.v0.spikesorting_sorting` |
| `WaveformParameters` | `spyglass.spikesorting.v1.metric_curation` | `spyglass.spikesorting.v0.spikesorting_curation` |
| `MetricParameters` | `spyglass.spikesorting.v1.metric_curation` | `spyglass.spikesorting.v0.spikesorting_curation` |
| `BurstPairParams` | `spyglass.spikesorting.v1.burst_curation` | `spyglass.spikesorting.v0.spikesorting_burst` |
| `BurstPairSelection` | `spyglass.spikesorting.v1.burst_curation` | `spyglass.spikesorting.v0.spikesorting_burst` |
| `BurstPair` | `spyglass.spikesorting.v1.burst_curation` | `spyglass.spikesorting.v0.spikesorting_burst` |
| `RecordingRecomputeVersions` | `spyglass.spikesorting.v1.recompute` | `spyglass.spikesorting.v0.spikesorting_recompute` |
| `RecordingRecomputeSelection` | `spyglass.spikesorting.v1.recompute` | `spyglass.spikesorting.v0.spikesorting_recompute` |
| `RecordingRecompute` | `spyglass.spikesorting.v1.recompute` | `spyglass.spikesorting.v0.spikesorting_recompute` |

## Querying Existing v0 Sortings

The merge table treats v0 sortings as first-class citizens — the spike-times accessor is source-agnostic, so downstream code does not need to branch on pipeline version:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# Restrict to v0 entries only for a session
merge_ids = SpikeSortingOutput().get_restricted_merge_ids(
    {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"},
    sources=["v0"],
)

# Same accessor as v1 — the merge table handles the dispatch
for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
```

Pass `sources=["v0", "v1"]` (or omit `sources`) to mix both. For new sorting/curation work, use v1 — do not populate v0 tables. See `notebooks/10_Spike_SortingV0.ipynb` (or its jupytext mirror `notebooks/py_scripts/10_Spike_SortingV0.py`) for the historical v0 populate flow if you need to read existing v0 code.

## `Curation.get_curated_sorting` does not filter rejected units

Spyglass v0 keeps curation labels in `curation_labels` on the
`Curation` row and does NOT re-wrap the SpikeInterface sorting per
curation step. `get_curated_sorting` returns the underlying sorting
including units labeled `'reject'`.

To apply labels, route through `CuratedSpikeSorting.fetch_nwb`:

```python
# `fetch_nwb()` does NOT raise on multiple-row restrictions — it
# silently returns a list across every match. Verify cardinality
# first before indexing [0], otherwise you'll grab an arbitrary
# row's units. See common_mistakes.md #4 / runtime_debugging.md.
rel = CuratedSpikeSorting & key
assert len(rel) == 1, f"key matched {len(rel)} rows; tighten before fetch_nwb"
nwb_obj = rel.fetch_nwb()[0]
units = nwb_obj['units']        # labels already applied
```

Or replicate the logic from `Curation.save_sorting_nwb`. Prefer the
v1 pipeline for new work — it doesn't have this split.
