<!-- pipeline-version: v1 -->
# Spike Sorting Pipeline

## Contents

- [Overview](#overview)
- [v0 Legacy Pointer](#v0-legacy-pointer)
- [Canonical Example (v1)](#canonical-example-v1)
- [SpikeSortingOutput Merge Table](#spikesortingoutput-merge-table)
- [V1 Pipeline Flow](#v1-pipeline-flow)
- [Step 1: Recording Preprocessing](#step-1-recording-preprocessing)
- [Step 2: Artifact Detection (Optional)](#step-2-artifact-detection-optional)
- [Step 3: Spike Sorting](#step-3-spike-sorting)
- [Step 4: Curation](#step-4-curation)
- [Step 5: Quality Metrics (Optional)](#step-5-quality-metrics-optional)
- [Step 6: Burst-Pair Curation (Optional)](#step-6-burst-pair-curation-optional)
- [Analysis: SortedSpikesGroup](#analysis-sortedspikesgroup)
- [Analysis: Unit Annotations](#analysis-unit-annotations)
- [Common Patterns](#common-patterns)
- [Imported Spike Sorting](#imported-spike-sorting)

## Overview

The spike sorting pipeline processes raw electrophysiology data into curated spike times. The v1 pipeline is current/recommended; v0 is legacy but still accessible through the merge table.

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup, UnitSelectionParams
from spyglass.spikesorting.analysis.v1.unit_annotation import UnitAnnotation
```

## v0 Legacy Pointer

Use v1 for new work. If you're reading v0 code or querying existing v0 sortings, see [spikesorting_v0_legacy.md](spikesorting_v0_legacy.md) — v0 and v1 have class-name collisions and different insert conventions.

## Canonical Example (v1)

End-to-end v1 flow: recording → artifact detection (optional) → sorting → curation → publish to `SpikeSortingOutput`. Each step uses the `insert_selection()` classmethod convention to generate UUIDs and validate keys — calling `.insert1()` directly on a v1 Selection table skips that validation.

**Return-value gotcha — `insert_selection` is rerun-tolerant.** Both
`SpikeSortingRecordingSelection.insert_selection` and
`SpikeSortingSelection.insert_selection` return a single key **dict**
when they insert a fresh row, but a **list of dicts** when a matching
row is already present (`recording.py:176-182`,
`sorting.py:222-228`). Splatting the result with `**rec_key` blows up
on rerun. Normalize to a single dict before reuse — pull the first
element when the function returned a list.

```python
from spyglass.spikesorting.v1 import (
    SortGroup,
    SpikeSortingRecordingSelection, SpikeSortingRecording,
    SpikeSortingSelection, SpikeSorting,
    CurationV1,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

def _one(result):
    """Normalize insert_selection's (dict | list[dict]) return to a dict."""
    return result[0] if isinstance(result, list) else result

# 1. Group electrodes by shank (warning: overwrites existing groups for
#    this session — cascades to downstream sorts; see doc #11 gotcha).
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)

# 2. Recording preprocessing
rec_key = _one(SpikeSortingRecordingSelection.insert_selection({
    "nwb_file_name": nwb_file, "sort_group_id": 0,
    "interval_list_name": interval_name,
    "preproc_param_name": "default", "team_name": "my_team",
}))
SpikeSortingRecording.populate(rec_key)

# 3. Sort. `sorter_params` is sorter-specific — mountainsort5 params do
#    NOT interchange with kilosort / ironclust. Use the paired defaults
#    in SpikeSorterParameters.
sort_key = _one(SpikeSortingSelection.insert_selection({
    **rec_key,                # carries interval_list_name already
    "sorter": "mountainsort4",
    "sorter_param_name": "franklab_tetrode_hippocampus_30KHz",
}))
SpikeSorting.populate(sort_key)

# 4. Register an initial curation (no edits — just anchors the sort_id).
#    `insert_curation` returns the FULL key dict, not a scalar id
#    (`spikesorting/v1/curation.py:117-128`).
curation_key = CurationV1.insert_curation(
    sorting_id=sort_key["sorting_id"], description="initial",
)

# 5. Publish to the merge table. `insert` takes a LIST of dicts (not a
#    bare dict — that raises TypeError). Use `part_name` to pick which
#    part table's parent to look the row up in.
merge_insert_key = (CurationV1 & curation_key).fetch("KEY", as_dict=True)
SpikeSortingOutput.insert(merge_insert_key, part_name="CurationV1")

# 6. Downstream: get spike times via the merge
merge_ids = SpikeSortingOutput().get_restricted_merge_ids(
    {"nwb_file_name": nwb_file, "interval_list_name": interval_name},
    sources=["v1"],
)
for mid in merge_ids:
    spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
```

## SpikeSortingOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `SpikeSortingOutput.CurationV1` | `CurationV1` | V1 curated spike sorting |
| `SpikeSortingOutput.ImportedSpikeSorting` | `ImportedSpikeSorting` | Pre-sorted spikes from NWB |
| `SpikeSortingOutput.CuratedSpikeSorting` | `CuratedSpikeSorting` | V0 legacy curated sorting |

### Key Methods on SpikeSortingOutput

| Method | Returns | Description |
| -------- | --------- | ------------- |
| `get_spike_times(key)` | list[np.array] | Spike times for each unit |
| `get_spike_indicator(key, time)` | np.array | Binary spike indicator matrix (n_time × n_units) |
| `get_firing_rate(key, time, multiunit, smoothing_sigma)` | np.array | Smoothed firing rate(s) |
| `get_recording(key)` | BaseRecording | SpikeInterface recording object |
| `get_sorting(key)` | BaseSorting | SpikeInterface sorting object |
| `get_sort_group_info(key)` | dj.Table | DataJoint query joining merge_id to electrode/brain region info (call `.fetch()` to materialize) |
| `get_restricted_merge_ids(key, sources, restrict_by_artifact, as_dict)` | list | Filter merge IDs by friendly keys |

## V1 Pipeline Flow

```text
Raw (common)
    ↓
SortGroup (electrode grouping)
    ↓
SpikeSortingRecordingSelection → SpikeSortingRecording (preprocessing)
    ↓                                    ↓
    ↓                          ArtifactDetectionSelection → ArtifactDetection
    ↓                                                          ↓
SpikeSortingSelection → SpikeSorting (run sorter)
    ↓
CurationV1 (labels + merge groups)
    ↓                          ↓
    ↓               MetricCurationSelection → MetricCuration (quality metrics)
    ↓                          │        ├─→ FigURLCurationSelection → FigURLCuration (manual curation UI)
    ↓                          │        └─→ BurstPairSelection → BurstPair (optional burst-pair analysis)
    ↓                          ↓
SpikeSortingOutput.CurationV1 (merge table)
    ↓
SortedSpikesGroup (analysis grouping)
```

## Step 1: Recording Preprocessing

```python
from spyglass.spikesorting.v1 import (
    SortGroup,
    SpikeSortingPreprocessingParameters,
    SpikeSortingRecordingSelection,
    SpikeSortingRecording,
)
```

**SortGroup** (Manual)

- Key: `nwb_file_name`, `sort_group_id`
- Part table: `SortGroup.SortGroupElectrode`
- Method: `set_group_by_shank()` — Auto-organizes electrodes by probe shank

**Parallel HDF5 reads can fail intermittently.** `SpikeSortingRecording.populate(...)`
may crash inside `write_binary_recording` with
`OSError: Can't read data (wrong B-tree signature)` when
SpikeInterface's default multi-worker `save_to_folder` opens the NWB
HDF5 file concurrently — h5py/HDF5 doesn't support concurrent reads
on one file handle on some NWB layouts.

**Fix.** Re-run with `n_jobs=1` (pass via preprocessing params or set
`recording.save(n_jobs=1, total_memory='10G')`). Upgrading
`h5py` / `pynwb` / `hdmf` also helps — older stacks are more exposed.

**Clusterless sorting requires one sort group per shank.** Sort groups
spanning multiple shanks produce duplicate `(x, y)` contact positions,
which SpikeInterface rejects at `SpikeSortingRecording.populate` with
`ValueError: contact positions are not unique`.

```python
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)
# ^ the single-shank grouper. Do not set_group_by_electrode for
#   clusterless / waveform-based pipelines.
```

Inspect `(SortGroup.SortGroupElectrode & key)` — if rows from more than
one shank appear per `sort_group_id`, regroup before inserting
selection rows.

**Whitening happens during sorting, NOT during
`SpikeSortingRecording` creation.** Preprocessing parameters like
`whitening=False` affect whether the **sorter** sees whitened data;
the `SpikeSortingRecording` stage stores unwhitened filtered data.
Saved waveforms from `MetricCuration` are unwhitened; the sorter's
internal decisions use the whitened view. Confirmed with maintainers.

**SpikeSortingPreprocessingParameters** (Lookup)

- Key: `preproc_param_name`
- Default: `"default"` with `frequency_min`, `frequency_max`, `margin_ms`

**SpikeSortingRecording** (Computed)

- Applies bandpass filter and referencing to raw data
- Methods: `get_recording(key)` — Returns SpikeInterface BaseRecording

### Running Recording Preprocessing

The v1 spike sorting pipeline uses `insert_selection()` class methods instead of raw `insert1()`:

```python
# Set up SortGroup (groups electrodes by probe shank)
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)

# Selection — insert_selection() generates a recording_id UUID on
# fresh insert. Note that on rerun, when a matching row already
# exists, it returns a list of dicts instead of a single dict
# (`spikesorting/v1/recording.py:176-182`); normalize before
# splatting downstream.
def _one(result):
    return result[0] if isinstance(result, list) else result

recording_key = _one(SpikeSortingRecordingSelection.insert_selection({
    "nwb_file_name": nwb_file, "sort_group_id": 0,
    "interval_list_name": interval_name, "preproc_param_name": "default",
    "team_name": "my_team",
}))

# Populate
SpikeSortingRecording.populate(recording_key)
```

The same `insert_selection()` + `populate()` pattern applies to `ArtifactDetection`, `SpikeSorting`, `MetricCuration`, and other v1 stages — each carries the same dict-vs-list return shape on rerun.

## Step 2: Artifact Detection (Optional)

```python
from spyglass.spikesorting.v1 import (
    ArtifactDetection,
    ArtifactDetectionParameters,
    ArtifactDetectionSelection,
)
```

**ArtifactDetectionParameters** (Lookup)

- Key: `artifact_param_name`
- Defaults: `"default"`, `"none"`
- Use `ArtifactDetectionParameters.describe()` for exact parameter fields

## Step 3: Spike Sorting

```python
from spyglass.spikesorting.v1 import (
    SpikeSorterParameters,
    SpikeSortingSelection,
    SpikeSorting,
)
```

**SpikeSorterParameters** (Lookup)

- Key: `sorter`, `sorter_param_name`
- Defaults include:
  - `mountainsort4` / `franklab_tetrode_hippocampus_30KHz`
  - `mountainsort4` / `franklab_probe_ctx_30KHz`
  - `clusterless_thresholder` / `default_clusterless`

**SpikeSorting** (Computed)

- Runs SpikeInterface sorter
- Methods: `get_sorting(key)` — Returns SpikeInterface BaseSorting

## Step 4: Curation

```python
from spyglass.spikesorting.v1 import CurationV1
```

**CurationV1** (Manual)

- Key: `sorting_id`, `curation_id`
- Valid labels: `"reject"`, `"noise"`, `"artifact"`, `"mua"`, `"accept"`
- Methods:
  - `insert_curation(sorting_id, parent_curation_id, labels, merge_groups, apply_merge, metrics, description)`
  - `get_recording(key)` — SpikeInterface BaseRecording
  - `get_sorting(key, as_dataframe)` — Sorting with curation labels
  - `get_merged_sorting(key)` — Sorting with merge groups applied
  - `get_sort_group_info(key)` — Electrode/brain region info

**Gotcha — `FigURLCurationSelection.generate_curation_uri` requires
metrics even if `insert_curation` didn't store them.**

`CurationV1.insert_curation(..., labels=None)` writes no
`curation_label` column to the analysis NWB. Downstream,
`FigURLCurationSelection.generate_curation_uri` reads that column
and — when it's absent — raises `ValueError: Sorting object must have
a 'curation_label' column ...` (`spikesorting/v1/figurl_curation.py:87-93`).

Workaround: pass explicit labels to `insert_curation` (an empty
labels dict per unit is enough to materialize the column), OR generate
figurl only from a curation that has metrics attached (i.e. one
inserted from `MetricCuration`).

## Step 5: Quality Metrics (Optional)

```python
from spyglass.spikesorting.v1 import (
    WaveformParameters,
    MetricParameters,
    MetricCurationParameters,
    MetricCurationSelection,
    MetricCuration,
)
```

**MetricParameters** (Lookup)

- Available metrics: `snr`, `isi_violation`, `nn_isolation`, `nn_noise_overlap`, `peak_offset`, `peak_channel`, `num_spikes`
- Method: `show_available_metrics()`

**MetricCuration** (Computed)

- Extracts waveforms, computes quality metrics, generates labels/merge groups
- Methods: `get_waveforms(key)`, internal metric computation

**Gotcha — "sorting has spikes exceeding the recording duration"**

`MetricCuration.populate` can raise `ValueError: The sorting object
has spikes exceeding the recording duration. You have to remove those
spikes with spikeinterface.curation.remove_excess_spikes()` when the
sorter placed a spike at or past the last recording timestamp.
Typically ~30% of units can be affected on a bad sort.

**Current Spyglass handles this automatically.** `CurationV1.get_sorting`
calls `spike_times_to_valid_samples` internally to trim excess spikes
at fetch time (see `src/spyglass/spikesorting/v1/curation.py:182-230`),
so `MetricCuration.populate` succeeds without any user action. If you
hit the error on current Spyglass, file a bug — the automatic
trimming should have caught it. On older installs that predate the
fix, there was no user-side workaround in the published API — upgrade
Spyglass (`git pull && pip install -e .`).

## Step 6: Burst-Pair Curation (Optional)

Identifies likely over-split unit pairs from the same neuron using waveform similarity, ISI violations, and cross-correlogram asymmetry. Downstream of `MetricCuration`; produces suggestions, not edits — you still decide whether to merge in a subsequent `CurationV1` entry. See `12_Burst_Merge_Curation.ipynb`.

```python
from spyglass.spikesorting.v1.burst_curation import (
    BurstPairParams,
    BurstPairSelection,
    BurstPair,
)
```

**BurstPairParams** (Lookup) — ships a `"default"` preset (`burst_curation.py:53`): `sorter="mountainsort4"`, `correl_window_ms=100`, `correl_bin_ms=5`, `correl_method="numba"`. For other sorters, insert a new params row with the matching `sorter` string.

**BurstPairSelection** (Manual) — FK to `MetricCuration` and `BurstPairParams`. Use the bulk-insert helper:

```python
BurstPairSelection().insert_by_curation_id(
    metric_curation_id=metric_curation_id,   # uuid of the MetricCuration row
    burst_params_name="default",
)
BurstPair.populate({"metric_curation_id": metric_curation_id})
```

**BurstPair** (Computed) — per-pair similarity/ISI/xcorrel scores in `BurstPair.BurstPairUnit`. Exposes plotting helpers (`plot_by_sort_group_ids`, `investigate_pair_xcorrel`, `investigate_pair_peaks`, `plot_peak_over_time`) for manual inspection before deciding to merge via a follow-up `CurationV1.insert_curation(..., merge_groups=...)`.

## Analysis: SortedSpikesGroup

Groups units across sort groups for downstream analysis (decoding, population analysis).

```python
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup, UnitSelectionParams
```

**UnitSelectionParams** (Manual)

- Key: `unit_filter_params_name`
- Defaults: `"all_units"`, `"exclude_noise"`, `"default_exclusion"`

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

## Analysis: Unit Annotations

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

```python
# Get recording (preprocessed)
recording = SpikeSortingOutput().get_recording({"merge_id": merge_id})

# Get sorting (with curation labels)
sorting = SpikeSortingOutput().get_sorting({"merge_id": merge_id})
```

## Imported Spike Sorting

```python
from spyglass.spikesorting.imported import ImportedSpikeSorting
```

For pre-sorted spikes stored in NWB Units table.

- `insert_from_nwbfile(nwb_file_name)` — Import units from NWB
- `add_annotation(key, id, label, annotations)` — Add unit annotations
- Auto-inserts into `SpikeSortingOutput.ImportedSpikeSorting`

## Recomputing Across Environments

Before re-running a sort from a different env (different lab, conda setup, or PyNWB pin), check NWB-namespace compatibility: `RecordingRecomputeVersions().this_env` (from `spyglass.spikesorting.v1.recompute`) is a cached property returning the subset of recordings whose stored `nwb_deps` match the currently installed stack. A mismatch means the stored analysis file won't load cleanly — pin the env or re-run from raw, don't assume.
