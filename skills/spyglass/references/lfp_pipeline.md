<!-- pipeline-version: v1 -->
# LFP Pipeline

LFP at any band — wideband via `LFPV1` / `LFPOutput` and bandpass via `LFPBandV1` / `LFPBandSelection` (theta, ripple-band, gamma, custom). `LFPV1.make()` reads `Raw` at runtime, so static FK walks alone understate the inputs needed to reproduce filtered output.

## Contents

- [Overview](#overview)
- [Canonical Example](#canonical-example)
- [LFPOutput Merge Table](#lfpoutput-merge-table)
- [Pipeline Flow](#pipeline-flow)
- [Step 1: Define Electrode Groups](#step-1-define-electrode-groups)
- [Step 2: Filter Raw Data](#step-2-filter-raw-data)
- [Step 3: Artifact Detection (Optional)](#step-3-artifact-detection-optional)
- [Step 4: Band Analysis (Phase/Power)](#step-4-band-analysis-phasepower)
- [Common Filters](#common-filters)
- [Plotting LFP](#plotting-lfp)

## Overview

The LFP pipeline filters raw electrophysiology data, detects artifacts, and computes frequency band analyses (phase, power, amplitude).

```python
from spyglass.lfp import LFPOutput, LFPElectrodeGroup
```

## Canonical Example

Minimal end-to-end flow: define an electrode group, run FIR filtering via `LFPV1`, fetch the filtered LFP as a DataFrame. Everything below expands on pieces of this.

```python
import numpy as np
from spyglass.common import FirFilterParameters, Raw
from spyglass.lfp import LFPOutput, LFPElectrodeGroup
from spyglass.lfp.v1 import LFPSelection, LFPV1

# 0. Make sure the standard FIR filter rows exist. The canonical
#    "LFP 0-400 Hz" filter ships at both 20 kHz and 30 kHz sampling
#    rates and is inserted by this helper (`common/common_filter.py:577`).
#    The notebook 30_LFP.py:67 calls this before any LFPSelection.insert1.
FirFilterParameters().create_standard_filters()

# 1. Define which electrodes go into this LFP
LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name="my_lfp_group",
    electrode_list=[0, 1, 2, 3],
)

# 2. Insert selection + populate. Two correctness gates here:
#    (a) target_interval_list_name must already exist in IntervalList,
#        otherwise LFPSelection.insert1 raises a cryptic FK error. Use
#        `(IntervalList & {"nwb_file_name": nwb_file})` to confirm
#        first.
#    (b) `filter_sampling_rate` must match the raw recording's
#        sampling rate — `LFPV1.make()` fetches it from `Raw` and
#        looks up `FirFilterParameters` by that rate
#        (`lfp/v1/lfp.py:72-75, 107-109`). 30000 below is correct
#        only when Raw rounds to 30 kHz; for a 20 kHz recording use
#        20000. Derive it instead of hard-coding.
raw_sampling_rate = int(np.round(
    (Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")
))
key = {"nwb_file_name": nwb_file,
       "lfp_electrode_group_name": "my_lfp_group",
       "target_interval_list_name": "02_r1",
       "filter_name": "LFP 0-400 Hz",
       "filter_sampling_rate": raw_sampling_rate,
       "target_sampling_rate": 1000}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)

# 3. Fetch via the merge table
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

> `Raw` is a runtime-fetch handle, not a stored pipeline output: a `Raw` row carries the NWB-object pointer + sampling rate, and the actual ephys array is read from the underlying NWB file at fetch time (`(Raw & key).fetch_nwb()[0]["raw"]`). So restricting `Raw` is cheap, but materializing the signal hits disk — and "is the raw data in Spyglass?" really means "is there a `Raw` row pointing at the NWB file the user expects?" For LFP recreation specifically, `LFPV1.make()` reads `Raw` at runtime, so static FK walks alone understate the inputs needed to reproduce the filtered output (general principle in [feedback_loops.md → Static graph vs runtime use](feedback_loops.md#tool-routing-for-relationship-and-lookup-questions)).

## LFPOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `LFPOutput.LFPV1` | `LFPV1` | FIR-filtered LFP from raw data |
| `LFPOutput.ImportedLFP` | `ImportedLFP` | Pre-computed LFP from NWB |
| `LFPOutput.CommonLFP` | `CommonLFP` | Legacy common LFP |

### Key Methods

- `fetch1_dataframe()` — Returns DataFrame with electrode columns, timestamps as index

## Pipeline Flow

```text
ElectrodeGroup (common) → LFPElectrodeGroup → LFPSelection → LFPV1
    ↑                                              ↑              ↓
Electrode (common)                          FirFilterParameters   ↓
                                            IntervalList          ↓
                                                                  ↓
                    LFPArtifactDetectionParameters → LFPArtifactDetectionSelection → LFPArtifactDetection
                                                                                          ↓
                                                              LFPArtifactRemovedIntervalList
                                                                                          ↓
                    FirFilterParameters → LFPBandSelection → LFPBandV1
                                              ↑                  ↓
                                    LFPBandSelection.LFPBandElectrode
```

## Step 1: Define Electrode Groups

```python
from spyglass.lfp import LFPElectrodeGroup

# View available electrode groups
LFPElectrodeGroup & {'nwb_file_name': nwb_file}

# Create a new electrode group
LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name='my_lfp_group',
    electrode_list=[0, 1, 2, 3]
)
```

**LFPElectrodeGroup** (Manual)

- Key: `nwb_file_name`, `lfp_electrode_group_name`
- Part table: `LFPElectrodeGroup.LFPElectrode` (adds `electrode_id`)

## Step 2: Filter Raw Data

```python
from spyglass.lfp.v1 import LFPSelection, LFPV1
```

**LFPSelection** (Manual)

- Key: `nwb_file_name`, `lfp_electrode_group_name`, `target_interval_list_name`, `filter_name`, `filter_sampling_rate`
- Also stores: `target_sampling_rate`

**Nyquist note on filter/sampling-rate fields.** The three sampling-rate fields interact strictly; mis-setting any one aliases real signal into the passband. The rules: `filter_sampling_rate` must match the actual sampling rate of the input the filter will be applied to (typically 20–30 kHz for raw neural recordings), `target_sampling_rate` must strictly exceed 2× the filter's high cutoff (e.g., `LFP 0-400 Hz` → target > 800; Spyglass's 1000 Hz LFP default is the canonical choice), and a downstream `LFPBandSelection` picking a band filter must choose a `filter_sampling_rate` that matches LFPV1's `target_sampling_rate` (1000 Hz), with the band's high cutoff strictly below 500 Hz (Nyquist of the LFP stream). `FirFilterParameters` keys on `(filter_name, filter_sampling_rate)` — a filter named for one rate won't apply to a stream at another rate. Picking an arbitrary `target_sampling_rate` without checking it against the filter passband is the most common mis-configuration.

**LFPV1** (Computed)

- Applies FIR filter from `FirFilterParameters` to raw data
- Stores filtered data in analysis NWB file
- Methods: `fetch1_dataframe()` — Returns filtered LFP as DataFrame

### Running the Pipeline (Selection + Populate)

```python
# `filter_sampling_rate` must match the actual raw rate. 30000 below
# is correct ONLY for 30 kHz raw recordings — derive it from Raw if
# you don't already know the rate:
#   from spyglass.common import Raw
#   raw_rate = int((Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate"))
key = {"nwb_file_name": nwb_file, "lfp_electrode_group_name": group_name,
       "target_interval_list_name": interval_name, "filter_name": "LFP 0-400 Hz",
       "filter_sampling_rate": 30000, "target_sampling_rate": 1000}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)
```

### Example: Fetch LFP Data

```python
key = {
    'nwb_file_name': nwb_file,
    'lfp_electrode_group_name': 'lfp_tets_j16',
    'target_interval_list_name': '02_r1',
    'filter_name': 'LFP 0-400 Hz',
    'filter_sampling_rate': 30000,  # only correct for 30 kHz raw — see note above
}
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()

print(f"Shape: {lfp_df.shape}")
print(f"Sampling rate: {1/(lfp_df.index[1] - lfp_df.index[0]):.1f} Hz")
```

## Step 3: Artifact Detection (Optional)

```python
from spyglass.lfp.v1 import (
    LFPArtifactDetection,
    LFPArtifactDetectionParameters,
    LFPArtifactDetectionSelection,
    LFPArtifactRemovedIntervalList,
)
```

**LFPArtifactDetectionParameters** (Manual; `lfp/v1/lfp_artifact.py:26`)

- Key: `artifact_params_name`
- Default presets exist as data on the class but are NOT auto-inserted at schema creation. Call `LFPArtifactDetectionParameters().insert_default()` (`lfp_artifact.py:73`) before referencing any of them. Available presets:
  - `"default_difference"` — Amplitude threshold detection
  - `"default_difference_ref"` — With common-mode referencing
  - `"default_mad"` — Median absolute deviation method
  - `"none"` — No artifact detection

**LFPArtifactDetectionSelection** (Manual; `lfp_artifact.py:145`)

- FKs `LFPV1` directly (NOT `LFPOutput`) plus `LFPArtifactDetectionParameters` (`lfp_artifact.py:145`). The selection key is the LFPV1 / LFPSelection primary key (`nwb_file_name`, `lfp_electrode_group_name`, `target_interval_list_name`, `filter_name`, `filter_sampling_rate`) plus `artifact_params_name` — not a merge key. Required step before `LFPArtifactDetection.populate()`.

**LFPArtifactDetection** (Computed; defined in `lfp/v1/lfp_artifact.py`)

- Detects artifacts and creates clean interval lists
- Outputs: `artifact_times` (array), `artifact_removed_valid_times` (array), `artifact_removed_interval_list_name`

```python
# 0. Make sure the default preset rows exist.
LFPArtifactDetectionParameters().insert_default()

# 1. Pick which LFP entry to scan. The selection FKs LFPV1 (NOT
#    LFPOutput) — reuse the LFPSelection/LFPV1 primary-key fields
#    from Step 2 above, do not pass a merge key here.
artifact_sel_key = {
    "nwb_file_name": key["nwb_file_name"],
    "lfp_electrode_group_name": key["lfp_electrode_group_name"],
    "target_interval_list_name": key["target_interval_list_name"],
    "filter_name": key["filter_name"],
    "filter_sampling_rate": key["filter_sampling_rate"],
    "artifact_params_name": "default_difference",
}
LFPArtifactDetectionSelection.insert1(artifact_sel_key, skip_duplicates=True)

# 2. Populate.
LFPArtifactDetection.populate(artifact_sel_key)

# 3. Fetch the clean interval times.
clean_times = (LFPArtifactDetection & artifact_sel_key).fetch1(
    "artifact_removed_valid_times"
)
```

## Step 4: Band Analysis (Phase/Power)

Required prerequisite for ripple detection (`RippleLFPSelection` FKs to `LFPBandV1`, not `LFPOutput` — see [ripple_pipeline.md](ripple_pipeline.md)) and for theta phase/power.

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1
```

**LFPBandSelection** (Manual)

- FKs `LFPOutput.proj(lfp_merge_id='merge_id')` (`lfp/analysis/v1/lfp_band.py:25-26`), NOT `LFPV1` directly. Any merge entry pointing at any concrete LFP source (commonly an `LFPV1` part, but also `ImportedLFP` / `CommonLFP`) is a valid input — that's the point of the merge layer.
- Key: includes `nwb_file_name`, `lfp_merge_id`, `filter_name`, `filter_sampling_rate`, `target_interval_list_name`, `lfp_band_sampling_rate`.
- Part table: `LFPBandSelection.LFPBandElectrode` (`lfp_band.py:34`) — per-electrode reference configuration.
- Entry method (preferred over manual `insert1`): `set_lfp_band_electrodes(nwb_file_name, lfp_merge_id, electrode_list, filter_name, interval_list_name, reference_electrode_list, lfp_band_sampling_rate)`. Populates both the main table and the part table.

**LFPBandV1** (Computed)

- Applies a band filter to an `LFPOutput` merge entry (commonly one produced by `LFPV1`).
- Key methods:
  - `fetch1_dataframe()` — band-filtered LFP
  - `compute_analytic_signal(electrode_list)` — Hilbert transform → complex amplitude
  - `compute_signal_phase(electrode_list)` — phase (0 to 2π)
  - `compute_signal_power(electrode_list)` — power (|analytic_signal|²)

### Canonical Example: Band Filtering (Theta / Ripple)

Assumes `LFPV1` is already populated for this session and interval (see the broadband canonical example at the top of this file).

```python
from spyglass.common import FirFilterParameters
from spyglass.lfp import LFPOutput
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1

# 1. Register the band filter (once per filter_name, site-wide).
FirFilterParameters().add_filter(
    filter_name="Theta 5-11 Hz",
    fs=1000.0,                       # must match the LFPV1 target_sampling_rate
    filter_type="bandpass",
    band_edges=[4, 5, 11, 12],
    comments="theta band for 1 kHz LFP",
)

# 2. Resolve the upstream LFPV1 entry's merge_id.
lfp_selection_key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "my_lfp_group",
    "target_interval_list_name": "02_r1",
    "filter_name": "LFP 0-400 Hz",
    "filter_sampling_rate": 30000,
    "target_sampling_rate": 1000,
}
lfp_merge_id = LFPOutput.merge_get_part(lfp_selection_key).fetch1("merge_id")

# 3. Register band-filter electrodes. electrode_list is a subset of the LFPV1
#    electrodes. reference_electrode_list=[-1] = no reference per channel.
LFPBandSelection().set_lfp_band_electrodes(
    nwb_file_name=nwb_file,
    lfp_merge_id=lfp_merge_id,
    electrode_list=[0, 1, 2, 3],
    filter_name="Theta 5-11 Hz",
    interval_list_name="02_r1",
    reference_electrode_list=[-1],
    lfp_band_sampling_rate=1000,
)

# 4. Populate. `LFPBandSelection`'s PK is wider than (lfp_merge_id,
#    filter_name) — it also keys on `filter_sampling_rate`,
#    `target_interval_list_name`, and `lfp_band_sampling_rate`
#    (`lfp/analysis/v1/lfp_band.py:22-30`). Restricting populate /
#    fetch by only the first two would silently grab any matching
#    selection row across other sampling rates / intervals — exactly
#    the partial-key footgun this skill warns about. Pull the FULL
#    selection key after `set_lfp_band_electrodes()` and use it.
#
#    Note on filter_sampling_rate: the helper derives it from the
#    parent LFP's sampling rate (`lfp_band.py:116, 216`) — passing it
#    in the restriction is therefore optional in the common single-
#    LFP-source case, but `fetch1("KEY")` requires the restriction to
#    match exactly one row, so include the four keys below (which
#    uniquely identify the just-inserted selection) and let
#    `fetch1("KEY")` expand the result to the full PK.
band_sel_key = (LFPBandSelection & {
    "nwb_file_name": nwb_file,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Theta 5-11 Hz",
    "target_interval_list_name": "02_r1",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")  # expands to include filter_sampling_rate
LFPBandV1.populate(band_sel_key, display_progress=True)

# 5. Fetch + derived quantities — reuse the same full key.
theta_df = (LFPBandV1 & band_sel_key).fetch1_dataframe()
phase = (LFPBandV1 & band_sel_key).compute_signal_phase(electrode_list=[0, 1, 2, 3])
power = (LFPBandV1 & band_sel_key).compute_signal_power(electrode_list=[0, 1, 2, 3])
```

For ripple band, swap `"Theta 5-11 Hz"` for `"Ripple 150-250 Hz"` (band_edges `[140, 150, 250, 260]`). `RippleLFPSelection.validate_key` rejects `LFPBandV1` rows whose `filter_name` does not contain `"ripple"` — name the filter accordingly if you want to use it downstream.

## Common Filters

`FirFilterParameters` has one built-in helper — `create_standard_filters()` — that inserts the broadband `'LFP 0-400 Hz'` preset (`common_filter.py:577`). Everything else is user/lab-created via `add_filter(...)`; register once (site-wide) before any downstream `LFPSelection` or `LFPBandSelection` references the name.

```python
from spyglass.common import FirFilterParameters

# See what your site already has
FirFilterParameters.fetch('filter_name')

# 'LFP 0-400 Hz' — broadband LFP; insert the shipped default once per site:
FirFilterParameters().create_standard_filters()

# Band filters are NOT shipped; register via add_filter (see Step 4 above).
# Conventional names used across Frank Lab scripts:
#   'Theta 5-11 Hz'    — theta band    (1 kHz LFP → 1 kHz band)
#   'Ripple 150-250 Hz'— ripple band   (1 kHz LFP → 1 kHz band)
```

## Plotting LFP

```python
import matplotlib.pyplot as plt

# Plot first 2 seconds of first 4 channels
duration = 2.0
channels = lfp_df.columns[:4]

fig, axes = plt.subplots(len(channels), 1, figsize=(12, 8), sharex=True)
for ax, channel in zip(axes, channels):
    mask = lfp_df.index < lfp_df.index[0] + duration
    ax.plot(lfp_df.index[mask], lfp_df[channel][mask])
    ax.set_ylabel(f'{channel}\n(μV)')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
axes[-1].set_xlabel('Time (s)')
plt.tight_layout()
plt.show()
```

## See also

- For "what cascades if I re-run LFP with new params" or "how do I recover after editing an `LFPSelection` row in place" questions, see [destructive_operations.md → Counterfactual / recovery / parameter-swap cascade template](destructive_operations.md#counterfactual--recovery--parameter-swap-cascade-template).
