# SpikeSortingRecording truncated to ~15 s of last sleep session

## Symptom

After running `SpikeSortingRecording.populate(...)` for `SC10420250616_.nwb`,
sort group 20, interval `all_sleep_run_valid_times`, the populated analysis
NWB ends ~15 s into the last sleep session. Spikes from the original NWB
extend through the entire session, so the data is present upstream — it is
being clipped at the recording-preprocessing step. Already ruled out:

- Artifact removal (separately confirmed).
- Acquisition / silent units (raw NWB has spikes through the full session).

## Where the truncation can happen

Walking [`SpikeSortingRecording._get_preprocessed_recording`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L475):

1. [`recording.py:551-554`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L551-L554) loads the raw NWB as a SpikeInterface
   recording with `load_time_vector=True`, then calls `recording.get_times()`
   for the full timestamp vector.
2. [`recording.py:557`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L557) computes
   `valid_sort_times = self._get_sort_interval_valid_times(key).times`, which
   is the **intersection of your `interval_list_name` with `"raw data valid
   times"`**, gated by `params["min_segment_length"]`
   ([recording.py:471-473](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L471-L473)).
3. [`_consolidate_intervals`](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L715)
   converts those times to frame indices via `np.searchsorted` against the
   recording's full timestamp vector.
4. `recording.frame_slice(...)` ([recording.py:567, 577](https://github.com/LorenFrankLab/spyglass/blob/master/src/spyglass/spikesorting/v1/recording.py#L567))
   slices the data; the matching `timestamps` slice is what gets written into
   the analysis NWB and read back as `obj.timestamps[:]`.

So the analysis NWB can only end at +15 s if **one of these is also clipped**
for the final sleep epoch:

1. **`"raw data valid times"` for that NWB ends early.** Most likely culprit
   — it is a per-NWB derived interval list, regenerated at ingest from the
   raw `ElectricalSeries` timestamp vector. A brief gap or early-end during
   the last sleep session silently clips the analysis NWB without producing
   any artifact rows.
2. **The raw recording's `get_times()[-1]` ends early.** Less likely if the
   original NWB visibly has spikes through the whole session, but spike
   extraction can read past gaps in the ElectricalSeries timestamps that
   `read_nwb_recording` does expose in `get_times()`.
3. **Your sort interval (`all_sleep_run_valid_times`) itself is truncated**
   for that epoch.
4. **`min_segment_length`** in `franklab_tetrode_hippocampus`'s preproc
   params clipped a fragmented tail. This would *drop* short segments, not
   truncate a long one — but worth checking.

## Diagnostic snippet

Run the same NWB through each layer and report whichever ends first.

```python
import numpy as np
import spikeinterface.extractors as se
from spyglass.common import IntervalList, Nwbfile
from spyglass.spikesorting.v1.recording import (
    SpikeSortingRecordingSelection,
    SpikeSortingPreprocessingParameters,
    SpikeSortingRecording,
    _consolidate_intervals,
)

nwb = "SC10420250616_.nwb"
sort_interval_name = "all_sleep_run_valid_times"

# 1. The user-supplied sort interval
sort_iv = (IntervalList & {
    "nwb_file_name": nwb,
    "interval_list_name": sort_interval_name,
}).fetch1("valid_times")
print("sort interval last segment:", sort_iv[-1])

# 2. "raw data valid times" — the prime suspect
raw_iv = (IntervalList & {
    "nwb_file_name": nwb,
    "interval_list_name": "raw data valid times",
}).fetch1("valid_times")
print("raw valid_times last segment:", raw_iv[-1])
print("raw valid_times count:", len(raw_iv))

last_sleep_start = float(sort_iv[-1, 0])
print("raw segments overlapping last sleep:",
      raw_iv[(raw_iv[:, 1] >= last_sleep_start)])

# 3. Raw recording timestamps
rec = se.read_nwb_recording(Nwbfile().get_abs_path(nwb), load_time_vector=True)
ts = rec.get_times()
print("recording.get_times()[-1]:", ts[-1], "n_samples:", len(ts))

# 4. Reproduce the exact intersection Spyglass used
key = (SpikeSortingRecordingSelection & {
    "nwb_file_name": nwb,
    "sort_group_id": 20,
    "interval_list_name": sort_interval_name,
    "preproc_param_name": "franklab_tetrode_hippocampus",
    "team_name": "sc4712",
}).fetch1("KEY")
ssr = SpikeSortingRecording()
intersected = ssr._get_sort_interval_valid_times(key).times
print("intersected last segment:", intersected[-1])
print("min_segment_length:",
      (SpikeSortingPreprocessingParameters & key)
      .fetch1("preproc_params")["min_segment_length"])

# 5. Frame-slice indices that get cut into the analysis NWB
idx = _consolidate_intervals(intersected, ts)
print("frame indices (last 3):", idx[-3:])
print("last frame index → time:", ts[idx[-1, 1]])
```

Whichever of (1) → (2) → (3) → (intersected) drops first identifies the
source.

## Caveat in the original reproduction

The bottom `IntervalList` query in the bug report uses `nwb_file_name`
(unqualified) instead of `nwb_file_name2`. If that's the actual variable in
the live session and `nwb_file_name` points to a different file, the printed
`interval_list_stop` is for the wrong session. Re-check with `nwb_file_name2`
before drawing further conclusions.

## Recovery

Pick the path that matches whichever layer is truncated.

- **`"raw data valid times"` is wrong but the raw NWB
  `ElectricalSeries.timestamps` are intact**: regenerate the interval row
  through the ingest path (re-run the ingest helper that populates valid
  times) so downstream selections stay consistent. Do **not** `super_delete()`
  or hand-edit `IntervalList`. The destructive teardown is team-gated through
  `cautious_delete`; coordinate with whoever ingested the session before
  removing rows.
- **The raw NWB `ElectricalSeries.timestamps` end early**: the data is gone
  from this analysis path. Recover by re-exporting from the Trodes `.rec`
  file and re-ingesting.
- **`min_segment_length` is clipping fragmented tails**: insert a custom
  preproc params row with a smaller `min_segment_length` rather than
  mutating the `franklab_tetrode_hippocampus` default — that default is
  shared across the lab and other sorts depend on its current value.

## Open follow-ups

- Confirm the installed Spyglass commit:
  `git -C "$SPYGLASS_SRC" log -p src/spyglass/spikesorting/v1/recording.py`
  to check whether `_get_sort_interval_valid_times` or
  `_consolidate_intervals` has had relevant fixes since the install.
- If (1) is confirmed, check the ingest code that builds
  `"raw data valid times"` for this NWB to see whether the early-end
  reflects a real Trodes packet drop or an off-by-one when the session
  boundary lands at the very end of the recording.
