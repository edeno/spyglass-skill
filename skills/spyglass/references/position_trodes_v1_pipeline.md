# Position Pipeline — Trodes (LED tracking)

LED-based position tracking via SpikeGadgets/Trodes. Simple
3-step shape (params → selection → populate); the populate handler
auto-inserts the resulting row into `PositionOutput` via
`PositionOutput._merge_insert(...)` (`position/v1/position_trodes_position.py:241`).

For the umbrella merge layer (`PositionOutput`, the per-source
method matrix, and the imported-pose path), see
[position_pipeline.md](position_pipeline.md). For DeepLabCut, see
[position_dlc_v1_pipeline.md](position_dlc_v1_pipeline.md).

## Contents

- [Pipeline Flow](#pipeline-flow)
- [Tables](#tables)
- [Canonical Example](#canonical-example)
- [Running the Pipeline (Selection + Populate)](#running-the-pipeline-selection--populate)
- [Fetch via PositionOutput](#fetch-via-positionoutput)

## Pipeline Flow

```text
RawPosition (common) → TrodesPosSelection → TrodesPosV1 → PositionOutput.TrodesPosV1
                                ↑
                        TrodesPosParams
```

## Tables

```python
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1
```

**TrodesPosParams** (Manual, parameter table)

- Key: `trodes_pos_params_name`
- Methods: `insert_default()`, `get_default()`
- Use `TrodesPosParams.describe()` or `TrodesPosParams.heading` for exact parameter names

**TrodesPosSelection** (Manual)

- Key: `nwb_file_name`, `interval_list_name`, `trodes_pos_params_name`

**TrodesPosV1** (Computed)

- Key: inherits from TrodesPosSelection
- Methods: `fetch1_dataframe(add_frame_ind=True)`, `fetch_video_path()`

## Canonical Example

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1

# 1. Params — insert once; reuse for many sessions
TrodesPosParams().insert_default()

# 2. Selection — pick the input (session + interval + params)
key = {"nwb_file_name": nwb_file,
       "interval_list_name": "pos 1 valid times",
       "trodes_pos_params_name": "default"}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 3. Populate — runs computation, writes to PositionOutput merge
TrodesPosV1.populate(key)

# Fetch via the merge table
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

## Running the Pipeline (Selection + Populate)

Every Spyglass pipeline follows the same 3-step pattern: insert a params row, insert a selection row, then populate. Fetching via `PositionOutput` comes after.

```python
# 1. Params (skip if default already inserted)
TrodesPosParams.insert1({"trodes_pos_params_name": "my_params", "params": {...}},
                         skip_duplicates=True)

# 2. Selection — picks the input to run on
key = {"nwb_file_name": nwb_file, "interval_list_name": interval_name,
       "trodes_pos_params_name": "my_params"}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 3. Populate — runs computation, writes to PositionOutput merge
TrodesPosV1.populate(key)
```

Warning: `skip_duplicates=True` silently ignores conflicting rows. Use it for idempotent pipeline reruns. Do not use it when inserting raw data — it masks real errors.

## Fetch via PositionOutput

```python
key = {
    'nwb_file_name': nwb_file,
    'interval_list_name': 'pos 1 valid times',
    'trodes_pos_params_name': 'default',
}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed

# Per-Trodes video path (defined at position/v1/position_trodes_position.py:278):
video_path = (PositionOutput & merge_key).fetch_video_path()
```

Defaults check:

```python
TrodesPosParams & {'trodes_pos_params_name': 'default'}
```
