# Position Pipeline — DeepLabCut (DLC v1)

Multi-stage video-based pose estimation. The DLC pipeline lives
under `spyglass.position.v1`; the populate handler for `DLCPosV1.make`
auto-inserts the resulting row into `PositionOutput` via
`PositionOutput._merge_insert(...)` (`position/v1/position_dlc_selection.py:85`).

For the umbrella merge layer (`PositionOutput`, the per-source
method matrix, and the imported-pose path), see
[position_pipeline.md](position_pipeline.md). For Trodes LED
tracking, see [position_trodes_v1_pipeline.md](position_trodes_v1_pipeline.md).

## Contents

- [Pipeline Flow](#pipeline-flow)
- [Key DLC Tables](#key-dlc-tables)
- [Key DLC Invariants](#key-dlc-invariants)
- [Gotcha — pose estimation hangs on existing video](#gotcha--pose-estimation-hangs-on-existing-video)
- [Gotcha — empty PositionIntervalMap](#gotcha--empty-positionintervalmap-on-old-ingestions-or-dlc-only-sessions)
- [Gotcha — DLC env vars must be set in the kernel](#gotcha--dlc-env-vars-must-be-set-in-the-kernel)
- [Gotcha — `test_mode` string vs bool](#dlc-test_mode-string-vs-bool-gotcha)
- [DLC Parameter Tables](#dlc-parameter-tables)
- [DLC Data Access](#dlc-data-access)

## Pipeline Flow

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

## Key DLC Tables

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

(The downstream `*Selection` classes shown above are exported from
`spyglass.position.v1`'s `__init__.py` — `DLCModelSelection`,
`DLCPoseEstimationSelection`, `DLCSmoothInterpSelection`,
`DLCSmoothInterpCohortSelection`, `DLCCentroidSelection`,
`DLCOrientationSelection`, and `DLCPosSelection`, plus training /
video selections — and are required by their respective `populate`
calls. Verify the full export list against
`spyglass/position/v1/__init__.py:20, :43, :50` on your install.)

## Key DLC Invariants

For the full 7-step DLC inference workflow (`insert_estimation_task` → `DLCPoseEstimation` → `DLCSmoothInterp` per-bodypart → `DLCSmoothInterpCohort` → `DLCCentroid` + `DLCOrientation` → `DLCPosV1` → `PositionOutput`), see `21_DLC.ipynb`. Two things the notebook does not flag that will bite you:

- Each selection stage shares the `DLCPoseEstimation` foreign key but adds its own parameter name; build the key by extending `pose_estimation_key` one field at a time, not by reusing the previous stage's full key.
- **`DLCPosSelection` is the exception to that pattern.** It projects `dlc_si_cohort_selection_name` into two separate aliases (`dlc_si_cohort_centroid` and `dlc_si_cohort_orientation`), so those must be set explicitly — spreading `cohort_key` leaves the wrong field names and `populate()` silently produces no rows.

## Gotcha — pose estimation hangs on existing video

`DLCPoseEstimationSelection.insert_estimation_task(...)` can appear to hang (no error, no progress) when an `.mp4` with the same name already sits in the DLC target video directory — observed lab failure mode, not a documented Spyglass contract. The path is whatever the install sets for `dlc_video_dir` (check `spyglass.settings` or `dj.config['custom']['dlc_dirs']`; this is a site/lab-specific path, not a Spyglass-shipped default). Manually delete the stale `.mp4` before re-running. If the call appears to hang, this is the first thing to check.

## Gotcha — empty PositionIntervalMap on old ingestions or DLC-only sessions

If DLC populate crashes with `IndexError: index 0 is out of bounds for axis 0 with size 0` from `convert_epoch_interval_name_to_position_interval_name`, the session has no resolvable `PositionIntervalMap` row. Note that `DLCPoseEstimation`'s `make()` already calls `convert_epoch_interval_name_to_position_interval_name` internally with `populate_missing=True` (`position/v1/position_dlc_pose_estimation.py:255-263`), so re-running the converter manually rarely helps — the converter ran, didn't resolve, and `DLCPoseEstimation` continued by falling back to video timestamps. `DLCPoseEstimation` itself only reaches the `RawPosition` lookup at `position/v1/position_dlc_pose_estimation.py:264` when `interval_list_name` is truthy; otherwise it sets `spatial_series = None`. So if the IndexError appears, inspect *which stage* actually threw it — the converter returning `[]` is a clue that no Trodes-derived position interval exists, not proof that every downstream DLC stage requires one. The diagnostic is upstream:

```python
from spyglass.common import convert_epoch_interval_name_to_position_interval_name

# Check what the converter actually returned for this epoch — an
# EMPTY list ([]) means it inserted a null map row and there's no
# position interval to resolve (`common/common_behav.py:886, 955,
# 991`). Test `if not result:`, not `if result is None:`.
convert_epoch_interval_name_to_position_interval_name(
    {'nwb_file_name': nwb_file, 'epoch': epoch_id},
    populate_missing=True,
)
```

**DLC-only sessions** (no Trodes-derived position). The converter only accepts interval names that pass `PositionSource._is_valid_name()` (matches `pos N valid times`, `common/common_behav.py:955`); when none are present it inserts a *null* map row and the converter helper returns `[]` rather than `None` (`common/common_behav.py:991`) — diagnostic checks should test for an empty list, not `None`. Two paths exist:

- **Raw position is available for the session.** Populate `PositionSource` / `RawPosition` first so the `pos N valid times` intervals exist, then the mapper can resolve them.
- **Genuinely DLC-only.** `DLCPoseEstimation.make()` already falls back to the source video's timestamps when the mapper returns no position-interval name (`position/v1/position_dlc_pose_estimation.py:264`) — you don't need to invent a `RawPosition` row to make pose estimation run. `DLCCentroid` and `DLCOrientation` use `RawPosition` only if available and otherwise fall back to empty metadata (`position/v1/position_dlc_centroid.py:311`, `position/v1/position_dlc_orient.py:188`), so they don't strictly require a Trodes position interval either. If a downstream stage fails on a DLC-only session, verify whether the failure is actually missing bodypart / cohort data, parameter mismatch, or metadata lookup — not just absent Trodes position — before assuming you have to inject a fake `RawPosition` row.

## Gotcha — DLC env vars must be set in the kernel

IDEs / SSH sessions frequently don't source the login profile, so `os.environ['DLC_OUTPUT_DIR']` returns `None` in the Python kernel and paths like `None/<video>.mp4` or `Path(None)` cause `TypeError` / `ffprobe` errors deep in the populate.

**Check.** The canonical names current Spyglass reads are `DLC_PROJECT_DIR`, `DLC_VIDEO_DIR`, `DLC_OUTPUT_DIR` — `settings.py` derives them as `f"{dir_type.upper()}_{dir.upper()}_DIR"` via `dir_to_var()` (see `settings.py:335`). `DLC_PROJECT_PATH` is only a legacy / base-dir fallback (`settings.py:207`); newer code paths expect `_DIR`.

```python
import os
need = ['DLC_PROJECT_DIR', 'DLC_VIDEO_DIR', 'DLC_OUTPUT_DIR',
        'HDF5_USE_FILE_LOCKING']
missing = [k for k in need if not os.environ.get(k)]
if missing:
    raise RuntimeError(f'DLC env vars not set: {missing}')
```

**Fix.** Prefer routing DLC paths through `dj.config['custom']['dlc_dirs']` (see `setup_config.md` "Per-Directory Overrides") and `dj.config.save_global()` — `dj.config` is honored from any kernel, unlike `~/.bashrc`. `HDF5_USE_FILE_LOCKING='FALSE'` is required on shared filesystems.

## DLC: `test_mode` string vs bool gotcha

Symptom: `DLCModelTraining.populate(...)` finishes in minutes with no useful model; log says `max_iters=2`.

Root cause: `spyglass.settings.test_mode` was saved as the string `'false'` (not the boolean `False`) in the user's `dj.config`. Python evaluates `bool('false')` as `True`, so Spyglass's test-mode code path — which shortens DLC training to 2 iterations — runs in production.

**Check.**

```python
from spyglass.settings import test_mode
print(test_mode, type(test_mode))   # must be <class 'bool'>
```

If the type is `str`, remove the entry from your DataJoint config file (or overwrite with an actual Python `False`) and restart the kernel.

**Current Spyglass handles this.** `SpyglassConfig` applies `str_to_bool` on load (`src/spyglass/settings.py:171`), so the type check will always show `bool` on a current install. If you see `type(test_mode) == str` on current Spyglass, something is overwriting `test_mode` after load — investigate the import path.

Sanity check if the training keeps stopping early even with a proper bool: look at the DLC project `config.yaml`'s `num_iterations` — DLC itself may have a per-project cap independent of Spyglass.

## DLC Parameter Tables

| Table | Key |
| ------- | ----- |
| `DLCModelParams` | `dlc_model_params_name` |
| `DLCSmoothInterpParams` | `dlc_si_params_name` |
| `DLCCentroidParams` | `dlc_centroid_params_name` |
| `DLCOrientationParams` | `dlc_orientation_params_name` |

These tables store their tunables in a `params: longblob` column, so `TableName.describe()` only shows the outer `params` column — not the keys *inside* the blob. To inspect the actual blob-internal keys, fetch a populated row (`fetch1('params')`) or read the table's `insert_default()` source for the shipped defaults (e.g. `DLCSmoothInterpParams` defines `params: longblob` at `position/v1/position_dlc_position.py:55` and the default keys live in `insert_default` at `:67`). For top-level table fields, `describe()` is fine; for blob-internal parameter keys, treat it as insufficient.

**Validating a proposed params dict before insert.** `spyglass.position.v1.dlc_utils` exposes `validate_option`, `validate_list`, and `validate_smooth_params` — the same validators the DLC pipeline uses internally. Call them before inserting a custom Params row to catch bad values at author time instead of `populate()` time. These are also the idiomatic validators to reuse when authoring a new params table for a custom pipeline downstream of DLC.

Defaults check:

```python
DLCSmoothInterpParams.fetch('dlc_si_params_name')
```

## DLC Data Access

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

## Fetch via PositionOutput

```python
# Per-DLC video path (defined at position/v1/position_dlc_selection.py:315):
video_path = (PositionOutput & merge_key).fetch_video_path()

# Per-DLC position dataframe (same columns as Trodes):
position_df = (PositionOutput & merge_key).fetch1_dataframe()
```
