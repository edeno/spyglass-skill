# LFP Pipeline

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
from spyglass.lfp import LFPOutput, LFPElectrodeGroup
from spyglass.lfp.v1 import LFPSelection, LFPV1

# 1. Define which electrodes go into this LFP
LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name="my_lfp_group",
    electrode_list=[0, 1, 2, 3],
)

# 2. Insert selection + populate — target_interval_list_name must already
#    exist in IntervalList, otherwise LFPSelection.insert1 raises a
#    cryptic FK error. Use (IntervalList & {"nwb_file_name": nwb_file}) to
#    confirm the interval is there first.
key = {"nwb_file_name": nwb_file,
       "lfp_electrode_group_name": "my_lfp_group",
       "target_interval_list_name": "02_r1",
       "filter_name": "LFP 0-400 Hz",
       "filter_sampling_rate": 30000,
       "target_sampling_rate": 1000}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)

# 3. Fetch via the merge table
merge_key = LFPOutput.merge_get_part(key).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

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
    'filter_sampling_rate': 30000,
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

**LFPArtifactDetectionParameters** (Manual)

- Key: `artifact_params_name`
- Default presets:
  - `"default_difference"` — Amplitude threshold detection
  - `"default_difference_ref"` — With common-mode referencing
  - `"default_mad"` — Median absolute deviation method
  - `"none"` — No artifact detection

**LFPArtifactDetection** (Computed)

- Detects artifacts and creates clean interval lists
- Outputs: `artifact_times` (array), `artifact_removed_valid_times` (array), `artifact_removed_interval_list_name`

```python
# Get clean intervals after artifact removal
clean_times = (LFPArtifactDetection & key).fetch1('artifact_removed_valid_times')
```

## Step 4: Band Analysis (Phase/Power)

```python
from spyglass.lfp.analysis.v1 import LFPBandSelection, LFPBandV1
```

**LFPBandSelection** (Manual)

- Key: includes `nwb_file_name`, `lfp_merge_id`, `filter_name`, `filter_sampling_rate`, `target_interval_list_name`, `lfp_band_sampling_rate`
- Part table: `LFPBandSelection.LFPBandElectrode` — per-electrode reference configuration
- Method: `set_lfp_band_electrodes(nwb_file_name, lfp_merge_id, electrode_list, filter_name, interval_list_name, reference_electrode_list, lfp_band_sampling_rate)`

**LFPBandV1** (Computed)

- Applies band filter to already-filtered LFP
- Key methods:
  - `fetch1_dataframe()` — Returns band-filtered LFP
  - `compute_analytic_signal(electrode_list)` — Hilbert transform → complex amplitude
  - `compute_signal_phase(electrode_list)` — Extract phase (0 to 2π)
  - `compute_signal_power(electrode_list)` — Extract power (|analytic_signal|²)

### Example: Compute Theta Phase

```python
# Assuming LFPBandV1 is populated with theta filter
band_entry = LFPBandV1 & theta_key

# Get phase for specific electrodes
phase = band_entry.compute_signal_phase(electrode_list=[10, 20, 30])

# Get power
power = band_entry.compute_signal_power(electrode_list=[10, 20, 30])
```

## Common Filters

```python
from spyglass.common import FirFilterParameters

# See all available filters
FirFilterParameters.fetch('filter_name')

# Common ones:
# 'LFP 0-400 Hz' — Broadband LFP
# 'Theta 5-11 Hz' — Theta band
# 'Ripple 150-250 Hz' — Ripple band
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
