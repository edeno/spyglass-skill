# Spike Sorting Pipeline


## Contents

- [Overview](#overview)
- [v0 vs v1 (Read First)](#v0-vs-v1-read-first)
- [Canonical Example (v1)](#canonical-example-v1)
- [SpikeSortingOutput Merge Table](#spikesortingoutput-merge-table)
- [V1 Pipeline Flow](#v1-pipeline-flow)
- [Step 1: Recording Preprocessing](#step-1-recording-preprocessing)
- [Step 2: Artifact Detection (Optional)](#step-2-artifact-detection-optional)
- [Step 3: Spike Sorting](#step-3-spike-sorting)
- [Step 4: Curation](#step-4-curation)
- [Step 5: Quality Metrics (Optional)](#step-5-quality-metrics-optional)
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

## v0 vs v1 (Read First)

**Use v1 for new work.** v0 remains in the codebase so existing sortings stay queryable through `SpikeSortingOutput`, but all new sorting, curation, and analysis should go through the v1 tables.

Concrete divergences to watch for when reading examples:

- **Imports**: `spyglass.spikesorting.v1.*` (current) vs `spyglass.spikesorting.v0.*` (legacy). Module names also differ — `v1/recording.py`, `v1/sorting.py`, `v1/curation.py`, `v1/metric_curation.py` vs a different v0 layout.
- **Selection inserts**: v1 uses the `insert_selection(...)` classmethod convention (`SpikeSortingSelection.insert_selection(key)`). v0 uses plain `.insert1(key)` on the selection table. Using `insert1` on a v1 table skips the validation/UUID generation `insert_selection` performs.
- **Curation**: v1 has a dedicated `CurationV1` table with `insert_curation(...)`, linking back to a specific `SpikeSorting` row via `sorting_id`. v0 threads curation through separate tables.
- **Class-name collisions**: several names (`SpikeSortingRecordingSelection`, `SpikeSortingRecording`, `SpikeSortingSelection`, `ArtifactDetectionSelection`, etc.) exist in both v0 and v1 modules. When reading code, confirm which module is imported at the top of the file.

If you see a v0 import in someone's code and they're *asking how to do something new*, answer in v1 and note that v0 still works for querying existing data.

## Canonical Example (v1)

End-to-end v1 flow: recording → artifact detection (optional) → sorting → curation → publish to `SpikeSortingOutput`. Each step uses the `insert_selection()` classmethod convention to generate UUIDs and validate keys — calling `.insert1()` directly on a v1 Selection table skips that validation.

```python
from spyglass.spikesorting.v1 import (
    SortGroup,
    SpikeSortingRecordingSelection, SpikeSortingRecording,
    SpikeSortingSelection, SpikeSorting,
    CurationV1,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# 1. Group electrodes by shank (warning: overwrites existing groups for
#    this session — cascades to downstream sorts; see doc #11 gotcha).
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)

# 2. Recording preprocessing
rec_key = SpikeSortingRecordingSelection.insert_selection({
    "nwb_file_name": nwb_file, "sort_group_id": 0,
    "interval_list_name": interval_name,
    "preproc_param_name": "default", "team_name": "my_team",
})
SpikeSortingRecording.populate(rec_key)

# 3. Sort. `sorter_params` is sorter-specific — mountainsort5 params do
#    NOT interchange with kilosort / ironclust. Use the paired defaults
#    in SpikeSorterParameters.
sort_key = SpikeSortingSelection.insert_selection({
    **rec_key, "sorter": "mountainsort4",
    "sorter_param_name": "franklab_tetrode_hippocampus_30KHz",
    "interval_list_name": interval_name,
})
SpikeSorting.populate(sort_key)

# 4. Register an initial curation (no edits — just anchors the sort_id)
curation_id = CurationV1.insert_curation(
    sorting_id=sort_key["sorting_id"], description="initial"
)

# 5. Publish to the merge table. `insert` takes a LIST of dicts (not a
#    bare dict — that raises TypeError). Use `part_name` to pick which
#    part table's parent to look the row up in.
merge_insert_key = (CurationV1 & {"sorting_id": sort_key["sorting_id"],
                                   "curation_id": curation_id}).fetch(
    "KEY", as_dict=True
)
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
|------------|-------------|-------------|
| `SpikeSortingOutput.CurationV1` | `CurationV1` | V1 curated spike sorting |
| `SpikeSortingOutput.ImportedSpikeSorting` | `ImportedSpikeSorting` | Pre-sorted spikes from NWB |
| `SpikeSortingOutput.CuratedSpikeSorting` | `CuratedSpikeSorting` | V0 legacy curated sorting |

### Key Methods on SpikeSortingOutput

| Method | Returns | Description |
|--------|---------|-------------|
| `get_spike_times(key)` | list[np.array] | Spike times for each unit |
| `get_spike_indicator(key, time)` | np.array | Binary spike indicator matrix (n_time × n_units) |
| `get_firing_rate(key, time, multiunit, smoothing_sigma)` | np.array | Smoothed firing rate(s) |
| `get_recording(key)` | BaseRecording | SpikeInterface recording object |
| `get_sorting(key)` | BaseSorting | SpikeInterface sorting object |
| `get_sort_group_info(key)` | dj.Table | DataJoint query joining merge_id to electrode/brain region info (call `.fetch()` to materialize) |
| `get_restricted_merge_ids(key, sources, restrict_by_artifact, as_dict)` | list | Filter merge IDs by friendly keys |

## V1 Pipeline Flow

```
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
    ↓                          ↓
    ↓               FigURLCurationSelection → FigURLCuration (manual curation UI)
    ↓
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

# Selection — insert_selection() generates a recording_id UUID
recording_key = SpikeSortingRecordingSelection.insert_selection({
    "nwb_file_name": nwb_file, "sort_group_id": 0,
    "interval_list_name": interval_name, "preproc_param_name": "default",
    "team_name": "my_team",
})

# Populate
SpikeSortingRecording.populate(recording_key)
```

The same `insert_selection()` + `populate()` pattern applies to `ArtifactDetection`, `SpikeSorting`, `MetricCuration`, and other v1 stages.

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
# Create a group
SortedSpikesGroup().create_group(
    group_name='HPC_02_r1',
    nwb_file_name=nwb_file,
    unit_filter_params_name='all_units',
    keys=merge_keys  # list of SpikeSortingOutput merge_ids
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
