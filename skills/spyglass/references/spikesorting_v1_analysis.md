<!-- pipeline-version: v1 -->
# Spike Sorting Analysis (v1)

Post-pipeline analysis surface that sits *downstream* of `SpikeSortingOutput` and `CurationV1`. The pipeline itself (recording preprocessing → sorting → curation → metrics → burst-pair) is in [spikesorting_v1_pipeline.md](spikesorting_v1_pipeline.md); this file covers the tables and helpers used after a curated sort exists: aggregating units into groups for downstream pipelines (decoding, ripple-detection, MUA), annotating units, and the SpikeInterface accessors.

For tutorial flow, see `notebooks/11_Spike_Sorting_Analysis.ipynb`; for schema/API authority, trust `src/spyglass/...` over the notebook prose.

## Contents

- [SortedSpikesGroup](#sortedspikesgroup)
- [Unit Annotations](#unit-annotations)
- [Common Patterns](#common-patterns)
- [Cross-references](#cross-references)

## SortedSpikesGroup

Groups units across sort groups for downstream analysis (decoding, population analysis).

```python
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup, UnitSelectionParams
```

**UnitSelectionParams** (Manual)

- Key: `unit_filter_params_name`
- Defaults: `"all_units"`, `"exclude_noise"`, `"default_exclusion"` — declared in `contents` plus `insert_default()` (`spikesorting/analysis/v1/group.py:17-59`). Despite being a `dj.Manual`, the rows are *not* auto-inserted on import. **On a fresh DB, run `UnitSelectionParams().insert_default()` once** before any `SortedSpikesGroup.create_group(..., unit_filter_params_name=...)` call that references one of these names — otherwise the FK insert fails with no matching row.

**SortedSpikesGroup** (Manual)

- Key: `nwb_file_name`, `unit_filter_params_name`, `sorted_spikes_group_name`
- Part table: `SortedSpikesGroup.Units` — links to SpikeSortingOutput entries

### Key Methods

```python
# Create a group. `keys` are inserted directly into the part table
# `SortedSpikesGroup.Units`, which FKs
# `SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')`
# (`spikesorting/analysis/v1/group.py:73, 97-103`). Each entry must
# therefore use the renamed key, NOT raw `merge_id`.
SortedSpikesGroup().create_group(
    group_name='HPC_02_r1',
    nwb_file_name=nwb_file,
    unit_filter_params_name='all_units',
    keys=[{"spikesorting_merge_id": merge_id} for merge_id in merge_ids],
)

# Fetch spike times with unit filtering
spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    key, return_unit_ids=True
)
# spike_times: list of arrays, one per unit
# unit_ids: list of unit identifiers

# Get spike indicator matrix
spike_indicator = SortedSpikesGroup().get_spike_indicator(key, time)
# Returns: np.array of shape (n_time, n_units)

# Get firing rates
firing_rate = SortedSpikesGroup().get_firing_rate(
    key, time, multiunit=False, smoothing_sigma=0.015
)
```

**`time_slice` accepts a `slice`, list, or tuple.** The docstring says
`time_slice: list of float, optional`; the implementation at
`src/spyglass/spikesorting/analysis/v1/group.py:231-232` converts a
list/tuple to a slice via `time_slice = slice(*time_slice)`. Both of
these work:

```python
# list or tuple — converted internally
SortedSpikesGroup().fetch_spike_data(key, time_slice=[t0, t1])

# slice — used directly
SortedSpikesGroup().fetch_spike_data(key, time_slice=slice(t0, t1))
```

Prefer `slice(t0, t1)` for clarity; the internal conversion is an
implementation detail that could change.

## Unit Annotations

```python
from spyglass.spikesorting.analysis.v1.unit_annotation import UnitAnnotation
```

**UnitAnnotation** (Manual)

- Key: `spikesorting_merge_id`, `unit_id`
- Part table: `UnitAnnotation.Annotation` — stores label + quantification
- Methods: `add_annotation(key, **kwargs)`, `fetch_unit_spikes(return_unit_ids)`

## Common Patterns

### Get spike times for a session

```python
# Method 1: Using friendly keys
merge_ids = SpikeSortingOutput().get_restricted_merge_ids({
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1',
})
for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})

# Method 2: Using merge_id directly
spikes = SpikeSortingOutput().get_spike_times({"merge_id": known_merge_id})
```

### Compute firing rates

```python
import numpy as np
from spyglass.common import IntervalList

# Get interval boundaries
interval_times = (IntervalList & {
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1'
}).fetch1('valid_times')

# Fetch spike data with unit IDs (from SortedSpikesGroup, see above)
spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    spike_group_key, return_unit_ids=True
)

# Compute per-unit firing rate
for unit_id, spikes in zip(unit_ids, spike_times):
    n_spikes = np.sum(
        (spikes >= interval_times[0, 0]) &
        (spikes <= interval_times[-1, 1])
    )
    duration = np.sum(interval_times[:, 1] - interval_times[:, 0])
    print(f"Unit {unit_id}: {n_spikes / duration:.2f} Hz")
```

### Access SpikeInterface objects

These accessors route through the merge's part class. They work for
v0 `CuratedSpikeSorting` (the v0 merge part at
`SpikeSortingOutput.CuratedSpikeSorting`, `spikesorting_merge.py:9-10`)
and v1 `CurationV1` sortings, but `ImportedSpikeSorting` deliberately
raises `NotImplementedError`
(`spikesorting/imported.py:95-104`) — Spyglass cannot reconstruct a
SpikeInterface recording / sorting from arbitrary external NWB units.
For an imported sorting, read the units table directly from the
analysis NWB.

```python
# Get recording (preprocessed) — fails on ImportedSpikeSorting
recording = SpikeSortingOutput().get_recording({"merge_id": merge_id})

# Get sorting — same caveat. Note: NumpySorting from get_sorting()
# does NOT carry curation-label properties; for labels, route through
# CurationV1.get_sorting(key, as_dataframe=True).
sorting = SpikeSortingOutput().get_sorting({"merge_id": merge_id})
```

## Cross-references

- [spikesorting_v1_pipeline.md](spikesorting_v1_pipeline.md) — pipeline that produces the curated sortings these helpers consume.
- [group_tables.md](group_tables.md) — `*Group.create_group()` shape used by `SortedSpikesGroup`, `PositionGroup`, etc.
- [decoding_pipeline.md](decoding_pipeline.md) — primary downstream consumer (`SortedSpikesDecodingV1` FKs `SortedSpikesGroup`).
- [mua_pipeline.md](mua_pipeline.md) — `MuaEventsV1` also FKs `SortedSpikesGroup`.
