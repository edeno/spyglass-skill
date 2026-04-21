# Ripple Detection Pipeline

Detects sharp-wave ripple events from ripple-band-filtered LFP. No merge table — outputs directly from `RippleTimesV1`.

## Contents

- [Overview](#overview)
- [Pipeline Flow](#pipeline-flow)
- [Prerequisite: populate LFPBandV1 with a ripple-band filter](#prerequisite-populate-lfpbandv1-with-a-ripple-band-filter)
- [Key Tables](#key-tables)
- [Canonical Example](#canonical-example)
- [Dependency: ripple_detection](#dependency-ripple_detection)

## Overview

```python
from spyglass.ripple.v1 import RippleTimesV1, RippleParameters, RippleLFPSelection
```

**Gotcha — ripple detection quality depends on how much data you use to estimate ripple-band SD.** The detector thresholds events relative to the ripple-band standard deviation computed over the input interval. Running on a short segment produces bad SD estimates → bad thresholds → events that look valid but are wrong. Use an interval long enough to span representative behavior (typically at least one full epoch) when estimating, not just the segment you want to query.

## Pipeline Flow

```text
LFPOutput (merge)
    ↓
LFPBandV1 (ripple-band filter: e.g., "Ripple 150-250 Hz")  ← required prerequisite
    ↓
RippleLFPSelection  ← set_lfp_electrodes(lfp_band_key, electrode_list, group_name)
    +
    RippleLFPSelection.RippleLFPElectrode (part table)
    ↓
RippleTimesV1 ← populate(key)
    ↑
RippleParameters  (Lookup; use insert_default())
    ↑
PositionOutput.proj(pos_merge_id='merge_id')  (for speed filtering)
```

Source: [`src/spyglass/ripple/v1/ripple.py`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/ripple/v1/ripple.py). FK declaration `-> LFPBandV1` at ripple.py:35 — `RippleLFPSelection` takes a key from `LFPBandV1`, **not** from `LFPOutput` directly.

## Prerequisite: populate LFPBandV1 with a ripple-band filter

`RippleLFPSelection.validate_key` rejects any `LFPBandV1` key whose `filter_name` does not contain `"ripple"` (ripple.py:46–50). Populate `LFPBandV1` with a ripple-band filter first — see the Canonical Band Filtering example in [lfp_pipeline.md](lfp_pipeline.md), using `filter_name="Ripple 150-250 Hz"` and `band_edges=[140, 150, 250, 260]`.

## Key Tables

**RippleLFPSelection** (Manual) — FK to `LFPBandV1`.

- Primary key: LFPBandV1 PK + `group_name` (default `"CA1"`, ripple.py:36).
- Part table: `RippleLFPSelection.RippleLFPElectrode` — FK to `LFPBandSelection.LFPBandElectrode`.
- Entry method: `RippleLFPSelection.set_lfp_electrodes(key, electrode_list=None, group_name="CA1")` — staticmethod (ripple.py:53). Pass the `LFPBandV1` key as `key`, a subset of `electrode_id`s from `LFPBandSelection.LFPBandElectrode` as `electrode_list` (or `None` to use all). Inserts into both the main table and the part table.
- Raises `KeyError` if any `electrode_id` is not in the associated `LFPBandSelection.LFPBandElectrode` (ripple.py:88–93).

**RippleParameters** (Lookup)

- Primary key: `ripple_param_name`.
- Non-PK: `ripple_param_dict` (blob) with nested structure:

  ```python
  {
      "speed_name": "head_speed" | "speed",   # column in PositionOutput dataframe
      "ripple_detection_algorithm": "Kay_ripple_detector" | "Karlsson_ripple_detector",
      "ripple_detection_params": {
          "speed_threshold": 4.0,              # cm/s
          "minimum_duration": 0.015,           # sec
          "zscore_threshold": 2.0,             # std
          "smoothing_sigma": 0.004,            # sec
          "close_ripple_threshold": 0.0,       # sec
      },
  }
  ```

- `RippleParameters().insert_default()` (ripple.py:144) inserts two presets: `"default"` (uses `head_speed`) and `"default_trodes"` (uses `speed`).

**RippleTimesV1** (Computed) — outputs ripple start/end times.

- FK: `RippleLFPSelection`, `RippleParameters`, `PositionOutput.proj(pos_merge_id='merge_id')` (ripple.py:184–186). The position merge key arrives as `pos_merge_id` — projected FK rename pattern, see [merge_methods.md](merge_methods.md).
- Stored via `AnalysisNwbfile`, fetch with `fetch1_dataframe()`.

## Canonical Example

**Prerequisite steps not repeated below** — before running this example you must have: (a) populated `LFPV1` for the session/interval, and (b) registered a ripple-band filter via `FirFilterParameters().add_filter(filter_name="Ripple 150-250 Hz", band_edges=[140, 150, 250, 260], fs=1000.0, filter_type="bandpass")` and populated `LFPBandV1` against it. See the Canonical Band Filtering example in [lfp_pipeline.md](lfp_pipeline.md) — the same steps, swap the filter name. Mirrors `32_Ripple_Detection.ipynb`.

```python
import numpy as np
from spyglass.common import Electrode, BrainRegion
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1
from spyglass.position import PositionOutput
from spyglass.ripple.v1 import (
    RippleLFPSelection,
    RippleParameters,
    RippleTimesV1,
)

# Prerequisite: LFPBandV1 populated with a ripple-band filter — see section above.
lfp_band_key = (LFPBandV1 & {
    "nwb_file_name": nwb_file_name,
    "filter_name": "Ripple 150-250 Hz",
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")

# 1. Select ripple-detection electrodes (one good wire per tetrode, CA1 only).
electrode_list = sorted(np.unique((
    (Electrode & {"nwb_file_name": nwb_file_name})
    * (LFPBandSelection.LFPBandElectrode & lfp_band_key)
    * BrainRegion
).fetch("electrode_id")))  # filter further to CA1 + probe_electrode==0 in practice

RippleLFPSelection.set_lfp_electrodes(
    lfp_band_key,
    electrode_list=electrode_list,
    group_name="CA1",
)
rip_sel_key = (RippleLFPSelection & lfp_band_key).fetch1("KEY")

# 2. Parameters.
RippleParameters().insert_default()   # inserts "default" and "default_trodes"

# 3. Populate ripple times. The position merge key arrives as pos_merge_id.
pos_merge_id = (PositionOutput & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": interval_list_name,
}).fetch1("merge_id")
populate_key = {
    **rip_sel_key,
    "ripple_param_name": "default_trodes",
    "pos_merge_id": pos_merge_id,
}
RippleTimesV1.populate(populate_key, display_progress=True)

# 4. Fetch results.
ripple_df = (RippleTimesV1 & populate_key).fetch1_dataframe()
```

## Dependency: ripple_detection

Source algorithms imported at ripple.py:9:

- `ripple_detection.Kay_ripple_detector()` — Kay's algorithm.
- `ripple_detection.Karlsson_ripple_detector()` — Karlsson's algorithm.

Registry in `RIPPLE_DETECTION_ALGORITHMS` (ripple.py:23). To add an algorithm, extend this dict; `ripple_param_dict["ripple_detection_algorithm"]` must match a registered key.
