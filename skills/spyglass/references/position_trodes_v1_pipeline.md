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
- `TrodesPosParams` has only `trodes_pos_params_name` plus a `params: longblob` column (`position/v1/position_trodes_position.py:54`), so `.describe()` / `.heading` only confirms the outer table shape — they cannot reveal blob-internal keys like `speed_smoothing_std_dev` or `position_smoothing_duration`. For blob-internal field names: read `(TrodesPosParams & key).fetch1("params")` on an existing row, `TrodesPosParams().default_params`, `get_accepted_params()`, or source — `src/spyglass/common/common_position.py` is what consumes them. `.describe()` is fine as a preliminary check that the table has a `params` column, just not as the primary discovery mechanism for parameter semantics.

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
# — plus video_frame_ind by default (`fetch1_dataframe(add_frame_ind=True)`
# at position/v1/position_trodes_position.py:255; column inserted by
# _data_to_df at common/common_position.py:531). Omitted when the params
# row is upsampled.
```

## Running the Pipeline (Selection + Populate)

The Trodes v1 pipeline follows the canonical 3-step Spyglass pattern: insert a params row, insert a selection row, then populate. Fetching via `PositionOutput` comes after. Other pipelines may have more (DLC is a multi-stage chain) or fewer (`ImportedPose` has no params or selection table) — verify per pipeline.

```python
# 1. Params. For custom params, build the dict by merging overrides
#    into the shipped defaults — don't construct `params` from scratch
#    (you'll miss required keys). The default_params property exposes
#    them; modify a copy and insert under a new name.
defaults = TrodesPosParams().default_params           # source-shipped dict
custom = {**defaults, "speed_smoothing_std_dev": 0.5}  # override one key
TrodesPosParams.insert1(
    {"trodes_pos_params_name": "my_params", "params": custom},
    skip_duplicates=True,
)

# 2. Selection — picks the input to run on. For the canonical
#    "use defaults, optionally tweak a few keys" path, prefer the
#    convenience helper TrodesPosSelection.insert_with_default(...)
#    (`position/v1/position_trodes_position.py:118`); it inserts the
#    selection row and (optionally) creates a new params entry from
#    `edit_defaults={...}` + `edit_name="..."` in one call. Use the
#    explicit two-step (Params.insert1 then Selection.insert1) only
#    when you're authoring more than a handful of overrides.
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
# — plus video_frame_ind by default; omitted for upsampled params.

# Per-Trodes video path (defined at position/v1/position_trodes_position.py:278):
video_path = (PositionOutput & merge_key).fetch_video_path()
```

Defaults check:

```python
TrodesPosParams & {'trodes_pos_params_name': 'default'}
```
