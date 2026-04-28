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

MUA detection uses the same `ripple_detection` library as ripple detection (`multiunit_HSE_detector`). `MuaEventsV1.make()` runs the detector only over samples inside `detection_interval` (`mua/v1/mua.py:100, 111`); the z-score baseline and event-rate threshold are estimated on those samples. Too-short, sparse-spike, or otherwise unrepresentative `detection_interval` choices skew the z-scoring and the resulting event set — pick an interval long enough that the baseline statistics are stable, and don't reuse one that overlaps poorly with the spike data. Same shape of gotcha as ripple detection — see [ripple_pipeline.md](ripple_pipeline.md).

**Prerequisites** — `MuaEventsV1` depends on three populated upstream tables, plus a named detection interval:

- `SortedSpikesGroup` — sorted spikes aggregated into a group, see [spikesorting_v1_pipeline.md](spikesorting_v1_pipeline.md).
- A populated `PositionOutput` row (the FK is renamed to `pos_merge_id` — see "renamed FKs" below). `pos_merge_id` identifies one specific computed position row, including its **source / interval / params**, not just the session — restrict by the full upstream key (e.g. `nwb_file_name + interval_list_name + trodes_pos_params_name` for Trodes, or the equivalent DLC tuple) when fetching the merge_id, not by `nwb_file_name` alone. The source must also be one whose `fetch1_dataframe()` returns a `speed` or `head_speed` column — `MuaEventsV1.get_speed()` reads `"speed" if "speed" in position_info.columns else "head_speed"` (`mua/v1/mua.py:144-150`). `TrodesPosV1` and `DLCPosV1` qualify; `ImportedPose` does not (it exposes `fetch_pose_dataframe()` instead). See [position_pipeline.md](position_pipeline.md).
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

Source: [`src/spyglass/mua/v1/mua.py`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/mua/v1/mua.py). The two upstream FKs are renamed to `pos_merge_id` and `detection_interval` via `.proj()` (mua.py:67–68) — projected FK rename pattern, see [merge_methods.md](merge_methods.md).

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

Mirrors `50_MUA_Detection.ipynb`. Assumes `SortedSpikesGroup` and `PositionOutput` are already populated. The PositionOutput source must be one whose `fetch1_dataframe()` returns a `speed` or `head_speed` column — `TrodesPosV1` or `DLCPosV1` (see prerequisites above for why `ImportedPose` doesn't qualify).

```python
from spyglass.mua.v1 import MuaEventsV1, MuaEventsParameters
from spyglass.position import PositionOutput
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup

nwb_copy_file_name = "mediumnwb20230802_.nwb"

# 1. Resolve the position merge_id. The restriction MUST uniquely
#    identify one source + params row — discover what's actually
#    populated for this session rather than guessing the params
#    name. `"single_led_upsampled"` is a tutorial-specific name from
#    `50_MUA_Detection.ipynb`'s mediumnwb fixture, NOT a Spyglass
#    default; copying it verbatim against an unrelated session will
#    `fetch1` zero rows.
candidate_pos = (PositionOutput.TrodesPosV1 & {
    "nwb_file_name": nwb_copy_file_name,
}).fetch("KEY", as_dict=True)
# Pick the row whose (interval_list_name, trodes_pos_params_name)
# tuple matches the run epoch + processing variant you want. For the
# tutorial fixture, that tuple is:
trodes_s_key = next(
    k for k in candidate_pos
    if k["interval_list_name"] == "pos 0 valid times"
    and k["trodes_pos_params_name"] == "single_led_upsampled"
)
pos_merge_id = (PositionOutput.TrodesPosV1 & trodes_s_key).fetch1("merge_id")

# 2. Identify the SortedSpikesGroup you want. Group name + filter
#    params name are user-chosen at create_group time; discover via
#    `(SortedSpikesGroup & {"nwb_file_name": ...}).fetch("KEY", as_dict=True)`
#    rather than guessing. The values below are the tutorial defaults.
sorted_spikes_group_key = {
    "nwb_file_name": nwb_copy_file_name,
    "sorted_spikes_group_name": "test_group",
    "unit_filter_params_name": "default_exclusion",
}

# 3. Parameters. `MuaEventsParameters` is `dj.Manual` (`mua/v1/mua.py:20`) —
#    its class-level `contents` (`mua/v1/mua.py:44`) is just data for
#    `insert_default` (`mua/v1/mua.py:57`) to consume; it is NOT
#    auto-inserted at schema creation the way `dj.Lookup.contents` is.
#    Call this explicitly before populate. Idempotent (uses `skip_duplicates`).
MuaEventsParameters().insert_default()

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
