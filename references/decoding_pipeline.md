# Decoding Pipeline

## Contents

- [Overview](#overview)
- [Canonical Example (Clusterless)](#canonical-example-clusterless)
- [DecodingOutput Merge Table](#decodingoutput-merge-table)
- [Results Structure (xarray.Dataset)](#results-structure-xarraydataset)
- [Shared Components](#shared-components)
- [Clusterless Decoding Flow](#clusterless-decoding-flow)
- [Sorted Spikes Decoding Flow](#sorted-spikes-decoding-flow)
- [Common Patterns](#common-patterns)
- [Storage](#storage)

## Overview

The decoding pipeline performs Bayesian position decoding from neural activity using the `non_local_detector` package. It supports two approaches: **clusterless** (from waveform features) and **sorted spikes** (from clustered spike times).

```python
from spyglass.decoding import DecodingOutput
```

## Canonical Example (Clusterless)

Minimal end-to-end flow. Sorted-spikes decoding uses the same shape with `SortedSpikesDecodingSelection` / `SortedSpikesDecodingV1` and a `SortedSpikesGroup` in place of the waveform-features group. Everything below expands on pieces.

```python
from spyglass.decoding import DecodingOutput
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection, ClusterlessDecodingV1,
)

# Prereqs (not shown here): UnitWaveformFeaturesGroup + PositionGroup rows
# created upstream; DecodingParameters row with name "contfrag_clusterless";
# encoding_interval_name and decoding_interval_name exist in IntervalList.

# 1. Selection + populate
selection_key = {
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": "contfrag_clusterless",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,  # 1 lets the decoder estimate params
                                     # from the encoding interval; times
                                     # outside intervals are marked -1
                                     # and excluded from fit/output (see
                                     # src/spyglass/decoding/v1/
                                     # clusterless.py:266-289).
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)

# 2. Fetch via DecodingOutput (friendly key resolves internally — no
#    merge_get_part needed for this merge table)
results = DecodingOutput.fetch_results(selection_key)
model = DecodingOutput.fetch_model(selection_key)
```

## DecodingOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `DecodingOutput.ClusterlessDecodingV1` | `ClusterlessDecodingV1` | Decode from waveform features |
| `DecodingOutput.SortedSpikesDecodingV1` | `SortedSpikesDecodingV1` | Decode from sorted spike times |

### Key Methods on DecodingOutput

| Method | Returns | Description |
| -------- | --------- | ------------- |
| `fetch_results(key)` | xarray.Dataset | Posterior probabilities and metadata |
| `fetch_model(key)` | Classifier | Fitted non_local_detector model |
| `fetch_environments(key)` | list[TrackGraph] | Track graph environments |
| `fetch_position_info(key)` | (DataFrame, list) | Position data + variable names |
| `fetch_linear_position_info(key)` | DataFrame | Linearized position projected onto track graph |
| `fetch_spike_data(key, filter_by_interval)` | list | Spike times (+ features for clusterless) |
| `create_decoding_view(key, ...)` | str | FigURL visualization URI |
| `cleanup(dry_run)` | None | Remove orphaned .nc/.pkl files |

## Results Structure (xarray.Dataset)

```python
results = DecodingOutput.fetch_results(key)

# Key data variables:
# - acausal_posterior: (time, state_bins) — smoothed posterior P(position|spikes)
# - causal_posterior: (time, state_bins) — causal (online) posterior
# - initial_conditions: (state_bins,)
# - discrete_state_transitions: (states_from, states_to)

# Key coordinates:
# - time: timestamps
# - state_bins: position bin centers
# - states: discrete state labels
# - interval_labels: (time,) — 0,1,2,... for intervals; -1 outside intervals
```

### Working with Results

```python
# Filter to specific decoding interval
interval_0 = results.where(results.interval_labels == 0, drop=True)

# Get decoded position (MAP estimate)
import numpy as np
decoded_pos = results.acausal_posterior.idxmax(dim='state_bins')

# Get actual position for comparison
position_df, var_names = DecodingOutput.fetch_position_info(key)
```

## Shared Components

### DecodingParameters (Lookup)

```python
from spyglass.decoding import DecodingParameters
```

- Key: `decoding_param_name`
- Stores model initialization parameters and optional fit/predict kwargs
- Default presets:
  - `contfrag_clusterless_{version}` — ContFragClusterlessClassifier
  - `nonlocal_clusterless_{version}` — NonLocalClusterlessDetector
  - `contfrag_sorted_{version}` — ContFragSortedSpikesClassifier
  - `nonlocal_sorted_{version}` — NonLocalSortedSpikesDetector

### PositionGroup (Manual)

```python
from spyglass.decoding import PositionGroup
```

- Key: `nwb_file_name`, `position_group_name`
- Attributes: `position_variables` (list, e.g., `["position_x", "position_y"]`), `upsample_rate` (float, Hz)
- Part table: `PositionGroup.Position` — links to PositionOutput entries
- Methods:
  - `create_group(nwb_file_name, group_name, keys, position_variables, upsample_rate)`
  - `fetch_position_info(key, min_time, max_time)` — Returns (DataFrame, variable_names)

**Gotcha — `position_variables` must match the upstream DataFrame's
column names.** `PositionGroup.create_group` defaults
`position_variables=['position_x','position_y']`. DLC-derived positions
expose columns named after the tracked body part
(`'head_position_x'`, `'head_position_y'`, etc.). With default
variables on a DLC source, `fetch_position_info` returns empty frames
and downstream decoding raises
`ValueError: No objects to concatenate`.

Check:

```python
cols = list((DLCPosV1 & key).fetch1_dataframe().columns)
# Pass matching names:
PositionGroup().create_group(..., position_variables=cols[:2])
```

## Clusterless Decoding Flow

Decodes from spike waveform features (amplitude, location) without explicit unit clustering.

```text
SpikeSortingOutput → UnitWaveformFeaturesSelection → UnitWaveformFeatures
                                                            ↓
UnitWaveformFeaturesGroup (groups features)
        ↓
ClusterlessDecodingSelection (+ PositionGroup + DecodingParameters + IntervalList)
        ↓
ClusterlessDecodingV1 (Computed)
        ↓
DecodingOutput.ClusterlessDecodingV1
```

### Key Tables

```python
from spyglass.decoding import (
    ClusterlessDecodingSelection,
    ClusterlessDecodingV1,
    UnitWaveformFeaturesGroup,
)
from spyglass.decoding.v1.waveform_features import (
    UnitWaveformFeatures,
    WaveformFeaturesParams,
    UnitWaveformFeaturesSelection,
)
```

**WaveformFeaturesParams** (Lookup)

- Key: `features_param_name`
- Defaults: `"amplitude"`, `"amplitude, spike_location"`

**UnitWaveformFeatures** (Computed)

- Methods: `fetch_data()` — Returns (spike_times, features) tuples per unit

**UnitWaveformFeaturesGroup** (Manual)

- Key: `nwb_file_name`, `waveform_features_group_name`
- Part table: `UnitWaveformFeaturesGroup.UnitFeatures`
- Method: `create_group(nwb_file_name, group_name, keys)`

**ClusterlessDecodingSelection** (Manual)

- Foreign keys to: UnitWaveformFeaturesGroup, PositionGroup, DecodingParameters
- Plus: `encoding_interval` and `decoding_interval` (from IntervalList)
- Flag: `estimate_decoding_params` (bool) — use Baum-Welch vs fixed params

**ClusterlessDecodingV1** (Computed)

- Outputs: `results_path` (.nc file), `classifier_path` (.pkl file)
- Key methods:
  - `fetch_results()` — xarray Dataset
  - `fetch_model()` — non_local_detector classifier
  - `fetch_spike_data(key, filter_by_interval)` — spike times + waveform features
  - `get_ahead_behind_distance(track_graph, time_slice)` — decoded vs actual position

### Running Clusterless Decoding

```python
selection_key = {
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": "contfrag_clusterless",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)

# Fetch via DecodingOutput (friendly key → results)
results = DecodingOutput.fetch_results(selection_key)
```

## Sorted Spikes Decoding Flow

Decodes from explicitly sorted spike times.

```text
SpikeSortingOutput → SortedSpikesGroup (analysis grouping)
        ↓
SortedSpikesDecodingSelection (+ PositionGroup + DecodingParameters + IntervalList)
        ↓
SortedSpikesDecodingV1 (Computed)
        ↓
DecodingOutput.SortedSpikesDecodingV1
```

### Key Tables (Sorted Spikes)

```python
from spyglass.decoding import (
    SortedSpikesDecodingSelection,
    SortedSpikesDecodingV1,
)
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
```

**SortedSpikesDecodingSelection** (Manual)

- Foreign keys to: SortedSpikesGroup, PositionGroup, DecodingParameters
- Plus: encoding/decoding intervals, `estimate_decoding_params` flag

**SortedSpikesDecodingV1** (Computed)

- Same output structure as ClusterlessDecodingV1
- Additional method: `spike_times_sorted_by_place_field_peak(time_slice)` — neurons ordered by place field

## Common Patterns

### Fetch and visualize decoding results

```python
import matplotlib.pyplot as plt
import numpy as np

results = DecodingOutput.fetch_results(key)
position_df, var_names = DecodingOutput.fetch_position_info(key)

# Plot posterior
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

posterior = results.acausal_posterior.values
time = results.time.values

axes[0].imshow(
    posterior.T, aspect='auto',
    extent=[time[0], time[-1], 0, posterior.shape[1]],
    origin='lower', cmap='hot'
)
axes[0].set_ylabel('Position Bin')
axes[0].set_title('Posterior Probability')

# Plot actual position
axes[1].plot(position_df.index, position_df[var_names[0]], 'b-', alpha=0.7)
axes[1].set_xlabel('Time (s)')
axes[1].set_ylabel('Position')
plt.tight_layout()
plt.show()
```

### Query decoding results for a session

```python
# See all decoding for a session
DecodingOutput.merge_restrict({'nwb_file_name': nwb_file})

# Get specific decoding
merge_key = DecodingOutput.merge_get_part({
    'nwb_file_name': nwb_file,
    'decoding_param_name': 'default_decoding',
}).fetch1("KEY")
```

## JAX / XLA OOM on long sessions

Symptom: `RESOURCE_EXHAUSTED: Out of memory while trying to allocate N
bytes` from JAX during `ClusterlessDecodingV1.populate` /
`SortedSpikesDecodingV1.populate`, with f32 buffers of shape
`(n_time, n_state_bins)` (e.g. `(3384862, 1926)` = 24 GiB) on an 80 GB
A100.

**Tuning knobs** (set on `DecodingParameters`):

```python
DecodingParameters.insert1({
    'decoding_param_name': 'clusterless_chunked',
    'decoding_params': {
        'classifier_params': {...},
        'decoding_kwargs': {
            'n_chunks': 10,              # split the decoding dimension
            'cache_likelihood': False,   # don't hold the likelihood buffer
        },
        'sorted_spikes_algorithm_params': {
            'block_size': 500,           # coarser block = less memory
        },
    },
}, skip_duplicates=True)
```

Also set the JAX memory fraction at the top of the populate script:

```python
import os
os.environ['XLA_PYTHON_CLIENT_MEM_FRACTION'] = '0.99'
```

**Workaround for `n_chunks` being ignored when
`estimate_decoding_params=False`:** set `estimate_decoding_params=True`
on the selection row; the kwarg reaches the decoder that way.
Tracked with `non_local_detector 0.6.9`.

## Storage

Results are saved as files in `{SPYGLASS_ANALYSIS_DIR}/{nwb_file_name}/`:

- `.nc` files — xarray Dataset with posteriors
- `.pkl` files — Pickled classifier model

`DecodingOutput().cleanup()` sweeps orphaned `.nc` / `.pkl` files. It's an instance method — note the `()` on `DecodingOutput`. Both modes return `None`; with `dry_run=True` it LOGS the paths it would remove (inspect the logs before rerunning). **Destructive when `dry_run=False`** — permanently deletes files from disk with no undo. See SKILL.md's destructive-ops list for the paired pattern.

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS paths; returns None
# After inspecting log output:
# DecodingOutput().cleanup(dry_run=False)
```
