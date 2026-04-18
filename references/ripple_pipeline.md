# Ripple Detection Pipeline

Detects sharp-wave ripple events from LFP data. No merge table — outputs directly from `RippleTimesV1`.

## Contents

- [Overview](#overview)
- [Pipeline Flow](#pipeline-flow)
- [Key Tables](#key-tables)
- [Example](#example)
- [Dependency: ripple_detection](#dependency-ripple_detection)

## Overview

```python
from spyglass.ripple.v1 import RippleTimesV1, RippleParameters, RippleLFPSelection
```

**Gotcha — ripple detection quality depends on how much data you use to estimate ripple-band SD.** The detector thresholds events relative to the ripple-band standard deviation computed over the input interval. Running on a short segment produces bad SD estimates → bad thresholds → events that look valid but are wrong. Use an interval long enough to span representative behavior (typically at least one full epoch) when estimating, not just the segment you want to query.

## Pipeline Flow

```
LFPOutput (merge) → RippleLFPSelection → RippleTimesV1
    ↑                     ↑                    ↑
    ↑              RippleLFPSelection     RippleParameters
    ↑              .RippleLFPElectrode
PositionOutput (for speed filtering)
IntervalList (valid times)
```

## Key Tables

**RippleLFPSelection** (Manual)
- Key: includes nwb_file_name and LFP merge references
- Part table: `RippleLFPSelection.RippleLFPElectrode` — selects which electrodes to use

**RippleParameters** (Lookup)
- Key: `ripple_param_name`
- Configures detection algorithm and thresholds

**RippleTimesV1** (Computed)
- Detects ripples using Kay or Karlsson algorithms from `ripple_detection` package
- Uses position/speed to filter out movement artifacts
- Output: ripple start/end times

## Example

```python
# Find ripple results
RippleTimesV1 & {'nwb_file_name': nwb_file}

# Fetch ripple times
ripple_df = (RippleTimesV1 & key).fetch1_dataframe()
```

## Dependency: ripple_detection

- `ripple_detection.Kay_ripple_detector()` — Kay's algorithm
- `ripple_detection.Karlsson_ripple_detector()` — Karlsson's algorithm
