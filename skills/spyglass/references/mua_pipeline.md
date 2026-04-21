# Multi-Unit Activity (MUA) Pipeline

Detects multi-unit high-synchrony events (population bursts) from sorted spike data. No merge table — outputs directly from `MuaEventsV1`.

## Contents

- [Overview](#overview)
- [Pipeline Flow](#pipeline-flow)
- [Key Tables](#key-tables)
- [Canonical Example](#canonical-example)
- [Dependency: ripple_detection](#dependency-ripple_detection)

## Overview

```python
from spyglass.mua.v1 import MuaEventsV1, MuaEventsParameters
```

MUA detection uses the same `ripple_detection` library as ripple detection (`multiunit_HSE_detector`), so the caveat about estimating the detection baseline on enough data applies here too — see [ripple_pipeline.md](ripple_pipeline.md) for the same shape of gotcha.

**Prerequisites** — `MuaEventsV1` depends on three populated upstream tables, plus a named detection interval:

- `SortedSpikesGroup` — sorted spikes aggregated into a group, see [spikesorting_pipeline.md](spikesorting_pipeline.md).
- `PositionOutput` — per-session position merge key, see [position_pipeline.md](position_pipeline.md).
- `IntervalList` — a named interval (passed as `detection_interval`, FK-renamed from `interval_list_name`).

## Pipeline Flow

```text
SortedSpikesGroup (spikesorting) ─┐
PositionOutput.proj(              │
    pos_merge_id='merge_id') ─────┼─→ MuaEventsV1
IntervalList.proj(                │        ↑
    detection_interval=           │   MuaEventsParameters
    'interval_list_name') ────────┘
```

Source: [`src/spyglass/mua/v1/mua.py`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/mua/v1/mua.py). The two upstream FKs are renamed to `pos_merge_id` and `detection_interval` via `.proj()` (mua.py:67–68) — projected FK rename pattern, see [merge_and_mixin_methods.md](merge_and_mixin_methods.md).

## Key Tables

**MuaEventsParameters** (Manual)

- Primary key: `mua_param_name`.
- Non-PK: `mua_param_dict` (blob) — for MUA the dict is flat (no nested `*_params`):

  ```python
  {
      "minimum_duration": 0.015,        # sec
      "zscore_threshold": 2.0,          # std
      "close_event_threshold": 0.0,     # sec
      "speed_threshold": 4.0,           # cm/s
  }
  ```

- `MuaEventsParameters.insert_default()` (classmethod, mua.py:56) inserts the single preset `"default"` shown above.

**MuaEventsV1** (Computed) — outputs MUA event start/end times.

- FK (mua.py:64–68): `MuaEventsParameters`, `SortedSpikesGroup`, `PositionOutput.proj(pos_merge_id='merge_id')`, `IntervalList.proj(detection_interval='interval_list_name')`.
- Stored via `AnalysisNwbfile`; fetch with `fetch1_dataframe()` (mua.py:129).

## Canonical Example

Mirrors `50_MUA_Detection.ipynb`. Assumes `SortedSpikesGroup` and `PositionOutput` (via Trodes or DLC) are already populated.

```python
from spyglass.mua.v1 import MuaEventsV1, MuaEventsParameters
from spyglass.position import PositionOutput
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup

nwb_copy_file_name = "mediumnwb20230802_.nwb"

# 1. Resolve the position merge_id (must uniquely identify one source + params).
trodes_s_key = {
    "nwb_file_name": nwb_copy_file_name,
    "interval_list_name": "pos 0 valid times",
    "trodes_pos_params_name": "single_led_upsampled",
}
pos_merge_id = (PositionOutput.TrodesPosV1 & trodes_s_key).fetch1("merge_id")

# 2. Identify the SortedSpikesGroup you want.
sorted_spikes_group_key = {
    "nwb_file_name": nwb_copy_file_name,
    "sorted_spikes_group_name": "test_group",
    "unit_filter_params_name": "default_exclusion",
}

# 3. Parameters — the default preset is inserted by the `contents` class attribute
#    at schema creation; insert_default() is idempotent if you want to be explicit.
MuaEventsParameters.insert_default()

# 4. Populate. Note the renamed FKs: pos_merge_id (not merge_id) and
#    detection_interval (not interval_list_name).
mua_key = {
    "mua_param_name": "default",
    **sorted_spikes_group_key,
    "pos_merge_id": pos_merge_id,
    "detection_interval": "pos 0 valid times",
}
MuaEventsV1().populate(mua_key)

# 5. Fetch results.
mua_times = (MuaEventsV1 & mua_key).fetch1_dataframe()   # start_time, end_time columns
```

`MuaEventsV1` also exposes `get_speed`, `get_firing_rate`, and `create_figurl` for post-populate plotting and interactive visualization — see [figurl.md](figurl.md) for the FigURL workflow; introspect the rest with `help(MuaEventsV1)` or `dir(MuaEventsV1)`.

## Dependency: ripple_detection

`multiunit_HSE_detector` from the `ripple_detection` package (imported at mua.py:5). The four `mua_param_dict` keys (`minimum_duration`, `zscore_threshold`, `close_event_threshold`, `speed_threshold`) flow through the detector as `mua_params` at mua.py:111-112. To change detector behavior, either update the params dict (still using `multiunit_HSE_detector`) or swap in a different detector by subclassing and overriding `make()`.
