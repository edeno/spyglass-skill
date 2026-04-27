<!-- pipeline-version: v1 -->
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
- **Parameter semantics — `speed_threshold` (default 4.0 cm/s).** Movement-exclusion cutoff passed into `ripple_detection` (`ripple.py:146, 219`). Candidate ripple events are kept only when the animal's **immobility** condition holds at start AND end — i.e. `speed <= speed_threshold` at both bounds. **Direction:** raising the threshold (e.g. 4 → 10 cm/s) **loosens** the immobility filter and keeps **more** candidate events (those at speeds up to the new threshold are no longer rejected). Quality tradeoff: a higher threshold lets in more peri-movement events that may not be true sharp-wave ripples (looser immobility conditioning); to get **fewer / cleaner** SWRs, **lower** the threshold.

**RippleTimesV1** (Computed) — outputs ripple start/end times.

- FK: `RippleLFPSelection`, `RippleParameters`, `PositionOutput.proj(pos_merge_id='merge_id')` (ripple.py:184–186). The position merge key arrives as `pos_merge_id` — projected FK rename pattern, see [merge_methods.md](merge_methods.md).
- Stored via `AnalysisNwbfile`, fetch with `fetch1_dataframe()`.

## Canonical Example

**Prerequisite steps not repeated below** — before running this example you must have: (a) populated `LFPV1` for the session/interval, and (b) registered a ripple-band filter via `FirFilterParameters().add_filter(filter_name="Ripple 150-250 Hz", band_edges=[140, 150, 250, 260], fs=1000.0, filter_type="bandpass")` and populated `LFPBandV1` against it. See the Canonical Band Filtering example in [lfp_pipeline.md](lfp_pipeline.md) — the same steps, swap the filter name. Mirrors `32_Ripple_Detection.ipynb`.

```python
import numpy as np
from spyglass.common import Electrode, BrainRegion
from spyglass.lfp import LFPOutput
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1
from spyglass.position import PositionOutput
from spyglass.ripple.v1 import (
    RippleLFPSelection,
    RippleParameters,
    RippleTimesV1,
)

# IMPORTANT — distinguish the two intervals these pipelines run on.
# `ripple_target_interval` is the time window the LFP/band filter and
# RippleTimesV1 operate over (e.g. "02_r1_ripple_demo"). The Trodes
# position row was inserted with its own `position_interval_list_name`
# (e.g. "pos 0 valid times"). RippleTimesV1.make() intersects the two
# at run time (`ripple/v1/ripple.py:288`), so reusing one name for
# both is a silent-wrong-count risk. Define them as separate
# variables.
ripple_target_interval = "02_r1_ripple_demo"
position_interval_list_name = "pos 0 valid times"
trodes_pos_params_name = "default"

# Prerequisite: LFPBandV1 populated with a ripple-band filter — see
# section above. `LFPBandSelection`'s PK includes `nwb_file_name`,
# `lfp_merge_id`, `filter_name`, `filter_sampling_rate`,
# `target_interval_list_name`, and `lfp_band_sampling_rate`
# (`lfp/analysis/v1/lfp_band.py:22-30`). Restricting by only a
# subset can match multiple bands across different intervals or LFP
# sources and make `fetch1` raise. Resolve `lfp_merge_id` from the
# concrete LFP source (typically `LFPOutput.LFPV1`) and include
# `target_interval_list_name` so the band is unambiguous.
lfp_merge_id = (LFPOutput.LFPV1 & {
    "nwb_file_name": nwb_file_name,
    "target_interval_list_name": ripple_target_interval,
}).fetch1("merge_id")
lfp_band_key = (LFPBandV1 & {
    "nwb_file_name": nwb_file_name,
    "lfp_merge_id": lfp_merge_id,
    "filter_name": "Ripple 150-250 Hz",
    "target_interval_list_name": ripple_target_interval,
    "lfp_band_sampling_rate": 1000,
}).fetch1("KEY")  # expands to the full PK including filter_sampling_rate

# 1. Select ripple-detection electrodes — one good wire per tetrode
#    in CA1. The notebook (32_Ripple_Detection) restricts to
#    `region_name LIKE '%CA1%'` and `probe_electrode = 0` before
#    building electrode_list. Filter explicitly so the comment and
#    the code agree.
electrode_list = sorted(np.unique((
    (Electrode & {"nwb_file_name": nwb_file_name, "probe_electrode": 0})
    * (LFPBandSelection.LFPBandElectrode & lfp_band_key)
    * (BrainRegion & 'region_name LIKE "%CA1%"')
).fetch("electrode_id")))

RippleLFPSelection.set_lfp_electrodes(
    lfp_band_key,
    electrode_list=electrode_list,
    group_name="CA1",
)
# `RippleLFPSelection.group_name` is part of the PK
# (`ripple/v1/ripple.py:35`); restrict on it so `fetch1("KEY")` is
# unambiguous when multiple groups exist for this band.
rip_sel_key = (RippleLFPSelection & lfp_band_key & {
    "group_name": "CA1",
}).fetch1("KEY")

# 2. Parameters.
RippleParameters().insert_default()   # inserts "default" and "default_trodes"

# 3. Populate ripple times. The position merge key arrives as pos_merge_id.
# Two correctness gates here:
#   (a) `PositionOutput` is a merge master — its declaration at
#       `position/position_merge.py:32` is `merge_id: uuid` +
#       `source: varchar(32)`. Restricting it directly by
#       `nwb_file_name` / `interval_list_name` silently returns the
#       whole table (those fields aren't on the master heading; see
#       SKILL.md + common_mistakes.md #1). Resolve through the
#       appropriate part instead — `PositionOutput.TrodesPosV1` for
#       Trodes, `PositionOutput.DLCPosV1` for DLC.
#   (b) `TrodesPosV1` inherits `TrodesPosSelection` which inherits
#       `RawPosition` and `TrodesPosParams`
#       (`position/v1/position_trodes_position.py:113`). A
#       (nwb_file_name, interval_list_name) pair can match multiple
#       `trodes_pos_params_name` rows. Include the params name to
#       resolve to a single merge_id.
pos_merge_id = (PositionOutput.TrodesPosV1 & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": position_interval_list_name,
    "trodes_pos_params_name": trodes_pos_params_name,
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
