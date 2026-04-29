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
- [Post-pipeline analysis](#post-pipeline-analysis)
- [Imported Spike Sorting](#imported-spike-sorting)
- [Recomputing Across Environments](#recomputing-across-environments)

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

End-to-end v1 flow: recording → artifact detection → sorting → curation → publish to `SpikeSortingOutput`. Each step uses the `insert_selection()` classmethod convention to generate UUIDs and validate keys — calling `.insert1()` directly on a v1 Selection table skips that validation. Artifact detection is included because the merge layer's downstream lookup (`get_restricted_merge_ids`) defaults to `restrict_by_artifact=True` and routes the interval through the artifact-selection table (`spikesorting/spikesorting_merge.py:95`); skipping the artifact step makes that lookup return zero merge_ids unless the caller passes `restrict_by_artifact=False` explicitly.

**Return-value gotcha — several v1 `insert_*` methods are rerun-tolerant.**
`SpikeSortingRecordingSelection.insert_selection` (`recording.py:176-182`),
`SpikeSortingSelection.insert_selection` (`sorting.py:222-228`),
`ArtifactDetectionSelection.insert_selection` (`artifact.py:104`), and
`CurationV1.insert_curation` (`curation.py:88-93`, only on the
parent-rerun branch where `parent_curation_id == -1` already exists)
return a single key **dict** on fresh insert but a **list of dicts**
when a matching row is already present. `MetricCurationSelection.insert_selection`
is the exception: it returns `fetch1()` (a single dict) on duplicate
(`metric_curation.py:221-223`). Splatting with `**rec_key` blows up
when the rerun returns a list — normalize to a single dict for the
list-returning stages.

```python
from spyglass.spikesorting.v1 import (
    SortGroup,
    SpikeSortingRecordingSelection, SpikeSortingRecording,
    ArtifactDetectionParameters, ArtifactDetectionSelection, ArtifactDetection,
    SpikeSortingSelection, SpikeSorting,
    CurationV1,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

def _one(result):
    """Normalize the (dict | list[dict]) return of the rerun-tolerant
    insert helpers (insert_selection on Recording / Sorting / Artifact,
    and insert_curation's parent-rerun branch) to a single dict."""
    if not isinstance(result, list):
        return result
    if len(result) != 1:
        raise ValueError(f"Expected one matching selection row, got {len(result)}")
    return result[0]

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

# 3. Artifact detection. Required for the default merge-layer lookup
#    (see preamble). `ArtifactDetectionParameters` is `dj.Lookup`
#    (`spikesorting/v1/artifact.py:27`) but ships only via
#    `insert_default()` (`:88`); call it once before referencing
#    "default".
ArtifactDetectionParameters().insert_default()
artifact_key = _one(ArtifactDetectionSelection.insert_selection({
    **rec_key,                                  # carries recording_id
    "artifact_param_name": "default",
}))
ArtifactDetection.populate(artifact_key)

# 4. Sort. `sorter_params` is sorter-specific — mountainsort5 params do
#    NOT interchange with kilosort / ironclust. Use the paired defaults
#    in SpikeSorterParameters.
sort_key = _one(SpikeSortingSelection.insert_selection({
    **rec_key,                # carries interval_list_name already
    "sorter": "mountainsort4",
    "sorter_param_name": "franklab_tetrode_hippocampus_30KHz",
}))
SpikeSorting.populate(sort_key)

# 5. Register an initial curation (no edits — just anchors the sort_id).
#    `insert_curation` returns the FULL key dict on fresh insert
#    (`spikesorting/v1/curation.py:117-128`), but on rerun of an
#    initial curation (parent_curation_id == -1 already exists) it
#    returns a LIST of KEY dicts (`curation.py:88-93`). Normalize.
curation_key = _one(CurationV1.insert_curation(
    sorting_id=sort_key["sorting_id"], description="initial",
))

# 6. Publish to the merge table. `insert` takes a LIST of dicts (not a
#    bare dict — that raises TypeError). Use `part_name` to pick which
#    part table's parent to look the row up in.
merge_insert_key = (CurationV1 & curation_key).fetch("KEY", as_dict=True)
SpikeSortingOutput.insert(merge_insert_key, part_name="CurationV1")

# 7. Downstream: get spike times via the merge. With artifact
#    detection populated above, the default `restrict_by_artifact=True`
#    works: the interval restriction routes through
#    `ArtifactDetectionSelection` and returns the merge_id of the
#    artifact-paired curation. Pass `restrict_by_artifact=False` only
#    if you skipped Step 3.
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
| `get_recording(key)` | BaseRecording | SpikeInterface recording object. **Routes through the merge's part class — `ImportedSpikeSorting.get_recording` deliberately raises `NotImplementedError` (`spikesorting/imported.py:95-97`).** Use only on v0/v1 computed sortings; for imported NWB units, fetch the units table directly. |
| `get_sorting(key)` | BaseSorting | SpikeInterface sorting object. Same merge-routing: `ImportedSpikeSorting.get_sorting` raises `NotImplementedError` (`imported.py:102-104`). |
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

**Parallel HDF5 reads can fail intermittently.** Current v1
`SpikeSortingRecording.populate(...)` writes the processed recording
into an analysis NWB via `SpikeInterfaceRecordingDataChunkIterator`
(`spikesorting/v1/recording.py:844, 883`); the historical
`write_binary_recording` / `save_to_folder` path is no longer how v1
stores its output. On older installs (or when SpikeInterface's
multi-worker writers are still in the chain via custom params), the
underlying h5py/HDF5 stack can crash with `OSError: Can't read data
(wrong B-tree signature)` on concurrent reads of one NWB file.

**Fix.** If the install genuinely runs the legacy path, re-run with
`n_jobs=1` and upgrade `h5py` / `pynwb` / `hdmf`. The default v1
`SpikeSortingPreprocessingParameters` row (`recording.py:127`) does
not currently expose `n_jobs`; if you need it, define a custom
preprocessing-params row with the kwarg you need rather than
mutating the default.

**Clusterless sorting requires one sort group per shank.** Sort groups
spanning multiple shanks produce duplicate `(x, y)` contact positions,
which SpikeInterface rejects at `SpikeSortingRecording.populate` with
`ValueError: contact positions are not unique`.

```python
SortGroup().set_group_by_shank(nwb_file_name=nwb_file)
# ^ The only v1 grouper (`spikesorting/v1/recording.py:51`). v0's
#   `set_group_by_electrode_group` (`spikesorting/v0/spikesorting_recording.py:94`)
#   does NOT exist on v1's SortGroup — do not port that v0 pattern
#   into clusterless / waveform-based v1 workflows.
```

Inspect `(SortGroup.SortGroupElectrode & key)` — if rows from more than
one shank appear per `sort_group_id`, regroup before inserting
selection rows.

**Whitening happens during sorting / waveform extraction, NOT
during the recording stage.** The recording stage applies bandpass
filtering and referencing only — see `spyglass/spikesorting/v1/recording.py`
(the `bandpass_filter` block in the populate handler). The
whitening kwarg lives on the parameter tables instead:

- **`SpikeSorterParameters`** — kwarg name is `whiten`, default
  `True`. See `spyglass/spikesorting/v1/sorting.py` (the
  `mountain_default` dict). Controls whether the sorter sees whitened
  data; if your sorter applies its own whitening downstream, the
  populate handler can pop it from `sorter_params` before the call.
- **`WaveformParameters`** — same kwarg `whiten`. The default
  presets are `default_not_whitened` (`whiten: False`) and
  `default_whitened` (`whiten: True`); see
  `spyglass/spikesorting/v1/metric_curation.py` (the contents block
  near the top of the class). MetricCuration waveforms can be either;
  pick the preset deliberately if you care about scientific
  interpretation of the saved waveforms.

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
    if not isinstance(result, list):
        return result
    if len(result) != 1:
        raise ValueError(f"Expected one matching selection row, got {len(result)}")
    return result[0]

recording_key = _one(SpikeSortingRecordingSelection.insert_selection({
    "nwb_file_name": nwb_file, "sort_group_id": 0,
    "interval_list_name": interval_name, "preproc_param_name": "default",
    "team_name": "my_team",
}))

# Populate
SpikeSortingRecording.populate(recording_key)
```

The same `insert_selection()` + `populate()` pattern applies to `ArtifactDetection`, `SpikeSorting`, `MetricCuration`, and other v1 stages. The dict-vs-list rerun shape only applies to selection helpers that wrap `fetch()` (which returns a list of dicts). `MetricCurationSelection.insert_selection` is the exception — on a duplicate row it returns `fetch1()` directly (`spikesorting/v1/metric_curation.py:221`), so the value is already a single dict and you don't index into `[0]`.

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
  - `get_sorting(key, as_dataframe=False)` — `as_dataframe=False` (default) builds a `si.NumpySorting` from spike times and does NOT carry curation-label properties (`spikesorting/v1/curation.py:182-223`); the labels live on the analysis NWB units table. Pass `as_dataframe=True` to get a pandas dataframe whose rows include the `curation_label` column.
  - `get_merged_sorting(key)` — Sorting with merge groups applied
  - `get_sort_group_info(key)` — Electrode/brain region info

**Gotcha — `FigURLCurationSelection.generate_curation_uri` requires
the parent CurationV1 NWB to have a `curation_label` column.**

`CurationV1.insert_curation(..., labels=None)` writes no
`curation_label` column to the analysis NWB. Downstream,
`FigURLCurationSelection.generate_curation_uri` reads that column
and — when it's absent — raises `ValueError: Sorting object must have
a 'curation_label' column ...` (`spikesorting/v1/figurl_curation.py:87-93`).

The required condition is the **labels column**, not metrics.
`figurl_curation.py:87-93` checks for `curation_label` only; it does
not check whether metrics were stored. Pass explicit labels to
`insert_curation` (an empty labels dict per unit is enough to
materialize the column), OR generate figurl from a curation that
already has labels (e.g. one inserted from `MetricCuration` with a
labeling step). Metrics may improve the FigURL display but are not
the gate.

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
burst_params_name = "default"
BurstPairSelection().insert_by_curation_id(
    metric_curation_id=metric_curation_id,   # uuid of the MetricCuration row
    burst_params_name=burst_params_name,
)
# `BurstPair` inherits `BurstPairSelection`, which combines
# `MetricCuration` + `BurstPairParams` (`burst_curation.py:71-75`).
# Restricting populate to `metric_curation_id` alone leaves
# `burst_params_name` open and re-runs against every BurstPairParams
# row paired with this curation.
# Scope to the params name you just inserted:
BurstPair.populate({
    "metric_curation_id": metric_curation_id,
    "burst_params_name": burst_params_name,
})
```

**BurstPair** (Computed) — per-pair similarity/ISI/xcorrel scores in `BurstPair.BurstPairUnit`. Exposes plotting helpers (`plot_by_sort_group_ids`, `investigate_pair_xcorrel`, `investigate_pair_peaks`, `plot_peak_over_time`) for manual inspection before deciding to merge via a follow-up `CurationV1.insert_curation(..., merge_groups=...)`.

## Post-pipeline analysis

`SortedSpikesGroup` (aggregating units across sort groups for decoding / MUA / population analysis), `UnitAnnotation`, and the post-curation common patterns (spike-time fetch, firing-rate compute, SpikeInterface accessors) live in [spikesorting_v1_analysis.md](spikesorting_v1_analysis.md). That file mirrors `notebooks/11_Spike_Sorting_Analysis.ipynb`. This file stays focused on the pipeline itself (preprocessing → sorting → curation → metrics → burst-pair).

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

## See also

- For "what cascades if I re-run sorting with new params" or "how do I recover after editing a `SpikeSortingSelection` / `WaveformSelection` row" questions, see [destructive_operations.md → Counterfactual / recovery / parameter-swap cascade template](destructive_operations.md#counterfactual--recovery--parameter-swap-cascade-template).
