# Position Tracking Pipeline

## Contents

- [Overview](#overview)
- [Canonical Example (Trodes)](#canonical-example-trodes)
- [PositionOutput Merge Table](#positionoutput-merge-table)
- [Pipeline 1: Trodes LED Tracking](#pipeline-1-trodes-led-tracking)
- [Pipeline 2: DeepLabCut (DLC)](#pipeline-2-deeplabcut-dlc)
- [Pipeline 3: Imported Pose](#pipeline-3-imported-pose)
- [Common Patterns](#common-patterns)

## Overview

The position pipeline tracks animal location using multiple methods, all consolidated through the `PositionOutput` merge table.

```python
from spyglass.position import PositionOutput
```

## Canonical Example (Trodes)

Minimal end-to-end flow for LED-based tracking. **DLC follows the same 3-step shape** (params → selection → populate → fetch via merge); the populate handlers for both `TrodesPosV1.make` and `DLCPosV1.make` insert the resulting row into `PositionOutput` via `PositionOutput._merge_insert(...)` automatically (`position/v1/position_trodes_position.py:241`, `position_dlc_selection.py:85`).

**Imported pose is the exception.** `ImportedPose` is a `dj.Manual` table (`position/v1/imported_pose.py:18`) populated by `ImportedPose().insert_from_nwbfile(nwb_file_name, ...)` (`imported_pose.py:47, 105`), which inserts the `IntervalList`, `ImportedPose`, and `ImportedPose.BodyPart` rows from the source NWB. There is **no params/selection step** and **no automatic `PositionOutput._merge_insert`** — to surface an imported-pose entry through the merge layer you have to insert into `PositionOutput.ImportedPose` yourself (or operate directly on `ImportedPose`). See "Imported Pose" below for the manual-import flow.

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

## PositionOutput Merge Table

**Primary Key**: `merge_id` (UUID)

### Part Tables (Sources)

| Part Table | Source Class | Description |
| ------------ | ------------- | ------------- |
| `PositionOutput.TrodesPosV1` | `TrodesPosV1` | LED-based tracking via SpikeGadgets/Trodes |
| `PositionOutput.DLCPosV1` | `DLCPosV1` | DeepLabCut pose estimation |
| `PositionOutput.CommonPos` | `IntervalPositionInfo` | Legacy common position |
| `PositionOutput.ImportedPose` | `ImportedPose` | Pre-computed pose from NWB |

### Key Methods on PositionOutput

`PositionOutput.fetch1_dataframe()` (defined at `position/position_merge.py:81`) and `PositionOutput.fetch_video_path()` (`position_merge.py:110`) are dispatchers — they delegate to the source class. What you get back depends on which part the merge entry resolves to:

| Method | TrodesPosV1 | DLCPosV1 | ImportedPose |
| --- | --- | --- | --- |
| `fetch1_dataframe()` | DataFrame: position_x, position_y, orientation, velocity_x, velocity_y, speed | same as Trodes | **not implemented** — `ImportedPose` exposes `fetch_pose_dataframe(key)` (`position/v1/imported_pose.py:110`) instead. Calling `PositionOutput.fetch1_dataframe()` against an imported-pose merge entry routes to a method that doesn't exist on the part. |
| `fetch_video_path(key=dict())` | video path (`position/v1/position_trodes_position.py:278`) | video path (`position/v1/position_dlc_selection.py:315`) | **not implemented** — `ImportedPose` has no `fetch_video_path`. |
| `fetch_pose_dataframe(key)` | not present | per-bodypart DLC pose | per-bodypart imported pose (`imported_pose.py:110`) |

In short: for Trodes/DLC, use the merge-level `fetch1_dataframe` / `fetch_video_path`. For imported pose, work through `ImportedPose.fetch_pose_dataframe(key)` directly (or via `PositionOutput.ImportedPose` part rows, if you've inserted them).

## Pipeline 1: Trodes LED Tracking

Simple pipeline: raw LED positions → smoothed/interpolated position.

```text
RawPosition (common) → TrodesPosSelection → TrodesPosV1 → PositionOutput.TrodesPosV1
                                ↑
                        TrodesPosParams
```

### Tables

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

### Running the Pipeline (Selection + Populate)

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

### Example: Fetch Trodes Position

```python
key = {
    'nwb_file_name': nwb_file,
    'interval_list_name': 'pos 1 valid times',
    'trodes_pos_params_name': 'default',
}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

## Pipeline 2: DeepLabCut (DLC)

Complex multi-stage pipeline for video-based pose estimation.

```text
DLCProject → DLCModelSource → DLCModelSelection → DLCModel
                                                       ↓
DLCPoseEstimationSelection → DLCPoseEstimation → DLCPoseEstimation.BodyPart
                                                       ↓
DLCSmoothInterpParams → DLCSmoothInterpSelection → DLCSmoothInterp (per bodypart)
                                                       ↓
DLCSmoothInterpCohortSelection → DLCSmoothInterpCohort (combines bodyparts)
        ↓                                    ↓
DLCCentroidParams → DLCCentroidSelection → DLCCentroid
DLCOrientationParams → DLCOrientationSelection → DLCOrientation
        ↓                                    ↓
                    DLCPosSelection → DLCPosV1 → PositionOutput.DLCPosV1
```

### Key DLC Tables

```python
from spyglass.position.v1 import (
    BodyPart, DLCProject,
    DLCModel, DLCModelParams, DLCModelSelection, DLCModelSource,
    DLCPoseEstimation, DLCPoseEstimationSelection,
    DLCSmoothInterp, DLCSmoothInterpParams, DLCSmoothInterpSelection,
    DLCSmoothInterpCohort, DLCSmoothInterpCohortSelection,
    DLCCentroid, DLCCentroidParams, DLCCentroidSelection,
    DLCOrientation, DLCOrientationParams, DLCOrientationSelection,
    DLCPosSelection, DLCPosV1,
)
```

(All four `*Selection` classes are exported from
`spyglass.position.v1`'s `__init__.py` — they appear in the pipeline
flow above and are required by their respective `populate` calls.)

### Key DLC invariants

For the full 7-step DLC inference workflow (`insert_estimation_task` → `DLCPoseEstimation` → `DLCSmoothInterp` per-bodypart → `DLCSmoothInterpCohort` → `DLCCentroid` + `DLCOrientation` → `DLCPosV1` → `PositionOutput`), see `21_DLC.ipynb`. Two things the notebook does not flag that will bite you:

- Each selection stage shares the `DLCPoseEstimation` foreign key but adds its own parameter name; build the key by extending `pose_estimation_key` one field at a time, not by reusing the previous stage's full key.
- **`DLCPosSelection` is the exception to that pattern.** It projects `dlc_si_cohort_selection_name` into two separate aliases (`dlc_si_cohort_centroid` and `dlc_si_cohort_orientation`), so those must be set explicitly — spreading `cohort_key` leaves the wrong field names and `populate()` silently produces no rows.

**Gotcha — pose estimation hangs silently if the target video file already exists.** `DLCPoseEstimationSelection.insert_estimation_task(...)` never completes (no error, no progress) when an `.mp4` with the same name already sits in the DLC target video directory. The path is whatever the install sets for `dlc_video_dir` (check `spyglass.settings` or `dj.config['custom']['dlc_dirs']`; this is a site/lab-specific path, not a Spyglass-shipped default). Manually delete the stale `.mp4` before re-running. If the call appears to hang, this is the first thing to check.

**Gotcha — empty `PositionIntervalMap` on old ingestions or DLC-only
sessions.** If DLC populate crashes with `IndexError: index 0 is out
of bounds for axis 0 with size 0` from
`convert_epoch_interval_name_to_position_interval_name`, the session
has no `PositionIntervalMap` rows. For each `TaskEpoch`, run:

```python
from spyglass.common import convert_epoch_interval_name_to_position_interval_name

convert_epoch_interval_name_to_position_interval_name(
    {'nwb_file_name': nwb_file, 'epoch': epoch_id},
    populate_missing=True,
)
```

**DLC-only sessions** (no Trodes-derived position). The mapping helper
`convert_epoch_interval_name_to_position_interval_name` only recognizes
interval names of the form `pos N valid times`
(`common/common_behav.py:944`); when none are present it inserts a
*null* map row rather than raising
(`common/common_behav.py:886`). Two paths exist:

- **Raw position is available for the session.** Populate
  `PositionSource` / `RawPosition` first so the `pos N valid times`
  intervals exist, then the mapper can resolve them.
- **Genuinely DLC-only.** Pose estimation can still proceed:
  `DLCPoseEstimation` falls back to the source video's timestamps when
  the mapper returns no position-interval name
  (`position/v1/position_dlc_pose_estimation.py:255`). You don't need
  to invent a `RawPosition` row to make DLC populate run.

**Gotcha — DLC env vars must be set in the kernel, not just
`~/.bashrc`.** IDEs / SSH sessions frequently don't source the login
profile, so `os.environ['DLC_OUTPUT_DIR']` returns `None` in the
Python kernel and paths like `None/<video>.mp4` or `Path(None)` cause
`TypeError` / `ffprobe` errors deep in the populate.

**Check.** The canonical names current Spyglass reads are
`DLC_PROJECT_DIR`, `DLC_VIDEO_DIR`, `DLC_OUTPUT_DIR` — `settings.py`
derives them as `f"{dir_type.upper()}_{dir.upper()}_DIR"` via
`dir_to_var()` (see `settings.py:335`). `DLC_PROJECT_PATH` is only a
legacy / base-dir fallback (`settings.py:207`); newer code paths
expect `_DIR`.

```python
import os
need = ['DLC_PROJECT_DIR', 'DLC_VIDEO_DIR', 'DLC_OUTPUT_DIR',
        'HDF5_USE_FILE_LOCKING']
missing = [k for k in need if not os.environ.get(k)]
if missing:
    raise RuntimeError(f'DLC env vars not set: {missing}')
```

**Fix.** Prefer routing DLC paths through `dj.config['custom']['dlc_dirs']`
(see `setup_config.md` "Per-Directory Overrides") and
`dj.config.save_global()` — `dj.config` is honored from any kernel,
unlike `~/.bashrc`. `HDF5_USE_FILE_LOCKING='FALSE'` is required on
shared filesystems.

### DLC Parameter Tables

| Table | Key |
| ------- | ----- |
| `DLCModelParams` | `dlc_model_params_name` |
| `DLCSmoothInterpParams` | `dlc_si_params_name` |
| `DLCCentroidParams` | `dlc_centroid_params_name` |
| `DLCOrientationParams` | `dlc_orientation_params_name` |

Use `TableName.describe()` to see exact parameter fields for each.

**Validating a proposed params dict before insert.** `spyglass.position.v1.dlc_utils` exposes `validate_option`, `validate_list`, and `validate_smooth_params` — the same validators the DLC pipeline uses internally. Call them before inserting a custom Params row to catch bad values at author time instead of `populate()` time. These are also the idiomatic validators to reuse when authoring a new params table for a custom pipeline downstream of DLC.

### DLC Data Access

```python
# Get pose data for all bodyparts
pose_df = (PositionOutput & merge_key).fetch_pose_dataframe()

# Get raw pose estimation for a bodypart (before smoothing)
(DLCPoseEstimation.BodyPart & key).fetch1_dataframe()
# Columns: video_frame_ind, x, y, likelihood

# Get smoothed pose for a bodypart
(DLCSmoothInterp & key).fetch1_dataframe()
# Columns: video_frame_ind, x, y
```

## DLC: `test_mode` string vs bool gotcha

Symptom: `DLCModelTraining.populate(...)` finishes in minutes with no
useful model; log says `max_iters=2`.

Root cause: `spyglass.settings.test_mode` was saved as the string
`'false'` (not the boolean `False`) in the user's `dj.config`. Python
evaluates `bool('false')` as `True`, so Spyglass's test-mode code path
— which shortens DLC training to 2 iterations — runs in production.

**Check.**

```python
from spyglass.settings import test_mode
print(test_mode, type(test_mode))   # must be <class 'bool'>
```

If the type is `str`, remove the entry from your DataJoint config file
(or overwrite with an actual Python `False`) and restart the kernel.

**Current Spyglass handles this.** `SpyglassConfig` applies
`str_to_bool` on load (`src/spyglass/settings.py:171`), so the type
check will always show `bool` on a current install. If you see
`type(test_mode) == str` on current Spyglass, something is overwriting
`test_mode` after load — investigate the import path.

Sanity check if the training keeps stopping early even with a proper
bool: look at the DLC project `config.yaml`'s `num_iterations` — DLC
itself may have a per-project cap independent of Spyglass.

## Pipeline 3: Imported Pose

For pre-computed pose data stored in NWB files. **This is a
manual-import path, not a populate path** — there is no parameters
table, no selection table, and no `make()` handler. The
`insert_from_nwbfile` method (defined at `position/v1/imported_pose.py:47`,
implementation at `:105`) inserts the IntervalList, the master row,
and the per-bodypart part rows from the source NWB.

```python
from spyglass.position.v1.imported_pose import ImportedPose

# 1. Pull pose rows from the source NWB.
ImportedPose().insert_from_nwbfile(nwb_file)

# 2. Fetch back the per-bodypart pose dataframe directly from
#    ImportedPose. PositionOutput.fetch1_dataframe / fetch_video_path
#    do NOT route through here — see the method-table above.
key = {"nwb_file_name": nwb_file, "interval_list_name": "<imported>"}
pose_df = ImportedPose().fetch_pose_dataframe(key)
```

**ImportedPose** (Manual; `position/v1/imported_pose.py:18`)

- Key: `nwb_file_name`, `interval_list_name`
- Part table: `ImportedPose.BodyPart` (key adds `part_name`)
- Methods:
  - `insert_from_nwbfile(nwb_file_name, ...)` — manual NWB import
    (inserts IntervalList + master + BodyPart rows)
  - `fetch_pose_dataframe(key=None)` — per-bodypart pose dataframe

**Surfacing through `PositionOutput`.** `insert_from_nwbfile` does NOT
auto-insert into the merge layer (contrast with `TrodesPosV1.make` /
`DLCPosV1.make` which call `PositionOutput._merge_insert(...)`
explicitly: `position/v1/position_trodes_position.py:241`,
`position_dlc_selection.py:85`). If a downstream consumer needs the
imported pose to appear under `PositionOutput.ImportedPose`, you have
to call `PositionOutput.insert([key], part_name="ImportedPose")`
yourself. Most analyses can read directly from `ImportedPose`; route
through the merge only when the consumer FKs to `PositionOutput`.

## Common Patterns

### Find all position data for a session

```python
# See all available sources
PositionOutput.merge_get_part(
    {'nwb_file_name': nwb_file},
    multi_source=True
)

# Or use merge_restrict for a quick view
PositionOutput.merge_restrict({'nwb_file_name': nwb_file})
```

### Plot position trajectory

```python
import matplotlib.pyplot as plt

position_df = (PositionOutput & merge_key).fetch1_dataframe()
plt.figure(figsize=(10, 8))
plt.plot(position_df['position_x'], position_df['position_y'],
         'b-', alpha=0.5, linewidth=0.5)
plt.xlabel('X Position (cm)')
plt.ylabel('Y Position (cm)')
plt.axis('equal')
plt.show()
```

### Check available parameters

```python
# Trodes defaults
TrodesPosParams & {'trodes_pos_params_name': 'default'}

# DLC smoothing defaults
DLCSmoothInterpParams.fetch('dlc_si_params_name')
```
