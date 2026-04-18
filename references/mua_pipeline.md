# Multi-Unit Activity (MUA) Pipeline

Detects multi-unit high synchrony events (population bursts) from spike data. No merge table — outputs directly from `MuaEventsV1`.

## Contents

- [Overview](#overview)
- [Pipeline Flow](#pipeline-flow)
- [Key Tables](#key-tables)
- [Example](#example)

## Overview

```python
from spyglass.mua.v1 import MuaEventsV1, MuaEventsParameters
```

MUA detection uses the same `ripple_detection` library as ripple detection (`multiunit_HSE_detector`), so the caveat about estimating the detection baseline on enough data applies here too — see [ripple_pipeline.md](ripple_pipeline.md) for the same shape of gotcha.

## Pipeline Flow

```text
SortedSpikesGroup (spikesorting) → MuaEventsV1
PositionOutput (for speed)              ↑
IntervalList (valid times)        MuaEventsParameters
```

## Key Tables

**MuaEventsParameters** (Manual)

- Key: `mua_param_name`
- Parameters for the `multiunit_HSE_detector` algorithm

**MuaEventsV1** (Computed)

- Uses `ripple_detection.multiunit_HSE_detector()` to detect high synchrony events
- Depends on SortedSpikesGroup for spike data and PositionOutput for speed filtering

## Example

```python
# Find MUA results
MuaEventsV1 & {'nwb_file_name': nwb_file}

# Fetch MUA event times
mua_df = (MuaEventsV1 & key).fetch1_dataframe()
```
