# Decoding Pipeline

State space position decoding from neural activity (clusterless and sorted-spikes) via `non_local_detector`. Covers `DecodingOutput`, the shared user-inputs-vs-`make()`-plumbing rule, and recovery patterns when `populate()` yields no work.

## Contents

- [Overview](#overview)
- [Canonical Example (Clusterless)](#canonical-example-clusterless)
- [DecodingOutput Merge Table](#decodingoutput-merge-table)
- [Results Structure (xarray.Dataset)](#results-structure-xarraydataset)
- [Shared Components](#shared-components)
- [User inputs vs `populate()` plumbing](#user-inputs-vs-populate-plumbing)
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
# created upstream; a DecodingParameters row whose name is the version-
# suffixed default (e.g. "contfrag_clusterless_v1.2.0"); encoding_interval_name
# and decoding_interval_name exist in IntervalList. Stock default names are
# defined in DecodingParameters.contents keyed on
# f"<shape>_<source>_{non_local_detector_version}" (`decoding/v1/core.py:48`),
# but they are NOT auto-inserted at module import — call
# `DecodingParameters().insert_default()` (`decoding/v1/core.py:68`) once,
# or query the table to confirm a matching row before insert.
# Don't hard-code a bare "contfrag_clusterless"; query DecodingParameters first
# (`(DecodingParameters & 'decoding_param_name LIKE "contfrag_clusterless%"').fetch1("decoding_param_name")`)
# or import the version constant alongside.

# 1. Selection + populate. `nwb_file_name` is REQUIRED — it is
#    inherited transitively through both `UnitWaveformFeaturesGroup`
#    and `PositionGroup` (`decoding/v1/clusterless.py:83`,
#    `decoding/v1/core.py:130`); without it the insert raises FK
#    failures. `estimate_decoding_params` defaults to 1 in the table
#    definition (`clusterless.py:90`); set it explicitly to 0 if you
#    want the fixed-parameter path.
from non_local_detector import __version__ as non_local_detector_version
selection_key = {
    "nwb_file_name": nwb_file,                # required — inherited via the groups
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,  # explicit; table default is 1.
                                     # Branches in the make() handler
                                     # (`clusterless.py:289` true branch
                                     # vs `:333` false branch) are very
                                     # different — see "estimate vs
                                     # fixed parameters" below.
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)

# 2. Fetch via DecodingOutput. These classmethods dispatch through
#    merge_restrict_class(key) internally (decoding_merge.py:74-111) — the
#    key must resolve to exactly one parent-table row, or you get
#    ValueError: "Ambiguous entry". A full selection_key (as built above)
#    usually does; a partial {"nwb_file_name": f} typically does not.
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
| `fetch_environments(key)` | list of `non_local_detector` Environment objects | Returns `classifier.environments` after `initialize_environments()` (`decoding/v1/clusterless.py:475-514`). These are non_local_detector `Environment` objects, NOT `TrackGraph` rows; access track-graph data via attributes (`environments[0].track_graph`, `.edge_order`, `.edge_spacing`). See `clusterless.py:757, 778` for downstream usage. |
| `fetch_position_info(key)` | (DataFrame, list) | Position data + variable names |
| `fetch_linear_position_info(key)` | DataFrame | Linearized position projected onto track graph |
| `fetch_spike_data(key, filter_by_interval)` | list | Spike times (+ features for clusterless) |
| `create_decoding_view(key, ...)` | FigURL view object (1D or 2D) | Returns a `create_1D_decode_view` / `create_2D_decode_view` view from `non_local_detector.visualization`; call `.url(label=...)` on the returned object to get the shareable string URL. See `decoding/decoding_merge.py:114`. |
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
# - state_bins: STACKED state-and-position index (NOT a plain position
#   coordinate). Each entry is a (state, position) pair. The non_local_detector
#   visualization unstacks it before extracting position
#   (`decoding/decoding_merge.py:148-153`):
#     posterior = (results.acausal_posterior
#         .unstack("state_bins")
#         .drop_sel(state=["Local", "No-Spike"], errors="ignore")
#         .sum("state"))
#   Treating state_bins directly as position-bin centers will cross-mix
#   discrete states (e.g. local vs continuous) and produce a misleading
#   MAP trace.
# - states: discrete state labels (e.g. "Continuous", "Fragmented",
#   "Local", "No-Spike", depending on the chosen DecodingParameters)
# - interval_labels: (time,) — interval index when
#   estimate_decoding_params=1 marks times outside intervals as -1; in
#   the fixed-parameter (=0) path the make() handler concatenates
#   per-interval results so this coordinate's shape depends on the
#   branch taken
```

### Working with Results

```python
# Filter to specific decoding interval
interval_0 = results.where(results.interval_labels == 0, drop=True)

# Get decoded position (MAP estimate). Unstack state_bins first, sum
# over discrete state, then idxmax over the resulting position index —
# DON'T idxmax over the raw stacked state_bins.
position_posterior = (
    results.acausal_posterior
    .unstack("state_bins")
    .drop_sel(state=["Local", "No-Spike"], errors="ignore")
    .sum("state")
)
decoded_pos = position_posterior.idxmax(dim="position")

# Get actual position for comparison
position_df, var_names = DecodingOutput.fetch_position_info(key)
```

## Shared Components

### DecodingParameters (Lookup)

```python
from spyglass.decoding import DecodingParameters
```

Schema (see `src/spyglass/decoding/v1/core.py:38-43`):

```text
decoding_param_name : varchar(80)
---
decoding_params  : LONGBLOB             # model initialization parameters
decoding_kwargs  = NULL : LONGBLOB      # additional keyword arguments
```

**`decoding_params` and `decoding_kwargs` are SIBLING top-level attributes**, not nested inside one another. This matters when inserting a custom param set — a common mistake is to nest `decoding_kwargs` inside `decoding_params`, which silently discards the runtime kwargs.

- `decoding_params` — classifier constructor kwargs (model architecture, state bins, transitions). Consumed as `ClusterlessDetector(**decoding_params)` inside `make_compute`.
- `decoding_kwargs` — runtime kwargs passed through to the classifier call. The `make()` handler has two branches gated on `estimate_decoding_params` (table default `1`; both `clusterless.py:90` and `sorted_spikes.py:55`):
  - **True branch (`clusterless.py:289`)** — Baum-Welch. Treats times outside decoding intervals as missing via an `is_missing` mask and assigns `interval_labels` from that mask; `decoding_kwargs` flow to `estimate_parameters`.
  - **False branch (`clusterless.py:333`)** — fixed-parameter. Predicts only on non-empty decoding intervals and concatenates those outputs; `decoding_kwargs` are split by `get_valid_kwargs` into fit and predict kwargs.

  Spyglass passes the dict through; the specific keyword names the installed `non_local_detector` recognizes (commonly `n_chunks`, `cache_likelihood`) are documented in that package — verify against the installed signatures if a kwarg appears to be ignored or rejected.

Canonical insert shape for an OOM-conscious clusterless variant:

```python
DecodingParameters.insert1({
    'decoding_param_name': 'clusterless_chunked',
    'decoding_params': {...},                        # model init — goes to the constructor
    'decoding_kwargs': {                             # runtime kwargs — reach predict() in the False branch
        'n_chunks': 10,
        'cache_likelihood': False,
    },
}, skip_duplicates=True)
```

- Key: `decoding_param_name`
- Stores model initialization parameters and optional fit/predict kwargs as separate blobs
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
`position_variables=['position_x', 'position_y']`. Both `TrodesPosV1.fetch1_dataframe()` and `DLCPosV1.fetch1_dataframe()` emit columns literally named `position_x` and `position_y` (see `src/spyglass/position/v1/position_dlc_selection.py:184-186` for DLC), so the **defaults match both upstream sources without modification**. Overriding `position_variables` with body-part-prefixed names like `['head_position_x', 'head_position_y']` is the typical mistake — those columns don't exist on the merge-fetched DataFrame, so when `upsample_rate` is non-NaN the `_upsample` helper raises `KeyError: 'head_position_x'` while iterating the requested variable names (`src/spyglass/decoding/v1/core.py:289-291`). When `upsample_rate` is NaN, the `KeyError` instead fires later, downstream of `fetch_position_info`, when the decoding `make()` body slices the returned DataFrame by `position_variable_names`. Distinct from `ValueError: No objects to concatenate`, which means the `PositionGroup.Position` part is empty for the key (no `pos_merge_id`s in the loop) — a different problem.

Check:

```python
cols = list((DLCPosV1 & key).fetch1_dataframe().columns)
# Pass matching names:
PositionGroup().create_group(..., position_variables=cols[:2])
```

## User inputs vs `populate()` plumbing

Applies to both clusterless and sorted-spikes decoding. The user-side surface is small; the rest is plumbing inside `*DecodingV1.make()`. Listing plumbing as a user input over-scopes the answer; missing a real input under-scopes it.

**User inputs** — must exist before `*DecodingSelection.insert1`: a **neural-data group** (`UnitWaveformFeaturesGroup` for clusterless, `SortedSpikesGroup` for sorted spikes; upstream features/spikes already populated); a **`PositionGroup`** row pointing at a populated `PositionOutput`; a **`DecodingParameters`** row (stock defaults are version-suffixed `f"<shape>_<source>_{non_local_detector_version}"` and are not auto-inserted on import; lab/custom rows may use any name, so query `DecodingParameters` rather than assuming the suffix); **`encoding_interval`** and **`decoding_interval`** `IntervalList` names (can be the same row); **`estimate_decoding_params`** (0 = fixed params from `DecodingParameters`, 1 = re-fit via Baum-Welch during populate). Reaching `UnitWaveformFeaturesGroup` from a fresh `SpikeSorting.populate` run requires a `CurationV1` row surfaced through `SpikeSortingOutput` (`SpikeSortingOutput.insert([curation_key], part_name="CurationV1")`, where `curation_key` is a `CurationV1` row key — *not* a `SpikeSortingSelection` or `SpikeSorting` key) — `UnitWaveformFeaturesSelection` FKs to `SpikeSortingOutput` (`decoding/v1/waveform_features.py:106`), and v1 feature computation reads `SpikeSortingOutput.CurationV1` to recover `sorting_id` (`decoding/v1/waveform_features.py:154`). The decoder consumes the waveform features, not the accept/reject curation labels.

**Plumbing inside `make()`** — not user-inserted rows: aligning spike (or feature) times to the position grid; building track graph / environment from `PositionGroup`; constructing the HMM transition matrix + observation model (clusterless mark intensity vs sorted-spikes place fields) from `DecodingParameters`; fitting on `encoding_interval` + forward-backward on `decoding_interval`; writing `results_path` (.nc) + `classifier_path` (.pkl) — populated outputs, not inputs. For "what do I need to run decoding?" answer with the user-input list. For "why is the decoder wrong?" debug user inputs first, then source-read the relevant `make()`.

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
# decoding_param_name is version-suffixed in DecodingParameters.contents
# (`decoding/v1/core.py:48`). Build it from the runtime version constant
# rather than hard-coding a bare prefix.
from non_local_detector import __version__ as non_local_detector_version
# `nwb_file_name` is REQUIRED — inherited transitively through both
# `UnitWaveformFeaturesGroup` and `PositionGroup`
# (`decoding/v1/clusterless.py:83`, `decoding/v1/core.py:130`).
# Omitting it under-specifies the FK and the insert raises.
selection_key = {
    "nwb_file_name": nwb_file_name,
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)

# Fetch via DecodingOutput — selection_key must resolve to exactly one
# parent-table row; see the Canonical Example above for why.
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

# `state_bins` is a stacked (state, position) coordinate — plotting
# `acausal_posterior.values` directly mixes state and position rows
# on one axis. Mirror the merge-table visualization helper
# (`decoding/decoding_merge.py:148`): unstack `state_bins`, drop the
# discrete states (`Local`, `No-Spike`) so only the continuous
# trajectory states remain, sum across remaining states, and
# renormalize over position. The result is a (time, position)
# posterior that is safe to imshow with a "Position" axis label.
posterior = (
    results.acausal_posterior.unstack("state_bins")
    .drop_sel(state=["Local", "No-Spike"], errors="ignore")
    .sum("state")
)
posterior = posterior / posterior.sum("position")
time = results.time.values
position_bins = posterior["position"].values

axes[0].imshow(
    posterior.values.T, aspect='auto',
    extent=[time[0], time[-1], position_bins[0], position_bins[-1]],
    origin='lower', cmap='hot'
)
axes[0].set_ylabel('Position')
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

# Get a specific decoding entry. Build the key from a real
# DecodingParameters row name — the stock defaults are version-
# suffixed (`decoding/v1/core.py:48`, e.g.
# f"contfrag_clusterless_{non_local_detector_version}") — and
# include enough fields to pick exactly one parent row, otherwise
# `merge_get_part` raises `ValueError: Ambiguous entry...` via
# `merge_restrict_class` (see § DecodingOutput Merge Table). A full
# selection_key (the one used at populate time) is the safest:
from non_local_detector import __version__ as non_local_detector_version
selection_key = {
    "nwb_file_name": nwb_file,
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,
}
merge_key = DecodingOutput.merge_get_part(selection_key).fetch1("KEY")
```

## JAX / XLA OOM on long sessions

Symptom: `RESOURCE_EXHAUSTED: Out of memory while trying to allocate N
bytes` from JAX during `ClusterlessDecodingV1.populate` /
`SortedSpikesDecodingV1.populate`, with f32 buffers of shape
`(n_time, n_state_bins)` (e.g. `(3384862, 1926)` = 24 GiB) on an 80 GB
A100.

**Tuning knobs** (set on `DecodingParameters`). Use the canonical insert shape from [§ DecodingParameters (Lookup)](#decodingparameters-lookup) — `decoding_params` and `decoding_kwargs` as sibling top-level attrs. For the OOM case, populate `decoding_kwargs` with `{'n_chunks': 10, 'cache_likelihood': False}`. These knobs reach the classifier via the False branch of `estimate_decoding_params` (table default is `1`; you must set this to `0` explicitly on the selection row to take the False branch); the installed `non_local_detector` is what ultimately consumes them, so verify against its signatures if either is ignored.

Also set the JAX memory fraction at the top of the populate script:

```python
import os
os.environ['XLA_PYTHON_CLIENT_MEM_FRACTION'] = '0.99'
```

**Workaround for `n_chunks` being ignored when
`estimate_decoding_params=False`:** set `estimate_decoding_params=True`
on the selection row; the kwarg reaches the decoder that way. **Caveat:**
the `True` branch calls `classifier.estimate_parameters(...)` (see
`src/spyglass/decoding/v1/clusterless.py:320`), which **re-runs EM
parameter estimation** — that is *not* the normal inference path the
user wants for routine decoding. Use this workaround only when you
genuinely need the parameter-estimation pass too (or as a one-off to
get past OOM); otherwise prefer fixing the kwarg-pass-through in the
`False` branch (e.g. by upgrading `non_local_detector` to a version
whose `predict()` accepts `n_chunks`). This behavior depends on the
installed `non_local_detector` version — if both branches accept
`n_chunks` in your installed copy, the workaround is unnecessary.
Verify with `inspect.signature` on the relevant classifier method to
confirm.

## Storage

Results are saved as files in `{SPYGLASS_ANALYSIS_DIR}/{stripped_nwb_file_name}/`, where `stripped_nwb_file_name` is `key["nwb_file_name"]` with the trailing `_.nwb` removed (`decoding/v1/clusterless.py:430`, `decoding/v1/sorted_spikes.py:373`):

- `.nc` files — xarray Dataset with posteriors
- `.pkl` files — Pickled classifier model

### Pickled decoder models are networkx-version-sensitive

`DecodingOutput.fetch_model(key)` unpickles a classifier that embeds a
`networkx.Graph`. If `networkx.__version__` differs from the save-time
version, unpickling raises
`AttributeError: 'Graph' object has no attribute '_adj'`.

Either match the networkx version used at save time (visible in
`environment.yml` or the stored `UserEnvironment` row) or re-train /
re-save the model in the current env.

`DecodingOutput().cleanup()` sweeps orphaned `.nc` / `.pkl` files. It's an instance method — note the `()` on `DecodingOutput`. Both modes return `None`; with `dry_run=True` it LOGS the paths it would remove (inspect the logs before rerunning). **Destructive when `dry_run=False`** — permanently deletes files from disk with no undo. See SKILL.md's destructive-ops list for the paired pattern.

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS paths; returns None
# After inspecting log output:
# DecodingOutput().cleanup(dry_run=False)
```

## See also

- For "what cascades if I re-run decoding with new params" or "how do I recover after editing a `DecodingParameters` / `*Selection` row" questions, see [destructive_operations.md → Counterfactual / recovery / parameter-swap cascade template](destructive_operations.md#counterfactual--recovery--parameter-swap-cascade-template).
