# External Dependencies Reference

## Contents

- [Core Dependencies](#core-dependencies)
- [Analysis Dependencies](#analysis-dependencies)
- [Optional Dependencies](#optional-dependencies)
- [Dependency Tiers](#dependency-tiers)

How Spyglass uses its key external packages — DataJoint, PyNWB / HDMF, SpikeInterface, `non_local_detector`, `track_linearization`, `position_tools`, `ripple_detection`, DLC / DeepLabCut, MoSeq / `keypoint_moseq`, Kachery. Only Spyglass-specific integration patterns are documented here; generic package usage (NumPy, pandas, matplotlib) is omitted.

## Core Dependencies

### DataJoint

All Spyglass tables inherit from DataJoint table types (`dj.Manual`, `dj.Computed`, `dj.Lookup`, `dj.Imported`). See [datajoint_api.md](datajoint_api.md) for query syntax.

### PyNWB + HDMF

Most raw and analysis data is stored in NWB files (HDF5-based) — tables reference NWB objects by `object_id`. The `fetch_nwb()` method is inherited via `SpyglassMixin` (from `FetchMixin`) but only resolves on **NWB-backed tables** — those that FK to `Nwbfile` / `AnalysisNwbfile` or set `_nwb_table = ...`. Calling it elsewhere raises `NotImplementedError` from `FetchMixin._nwb_table_tuple` (see `src/spyglass/utils/mixins/fetch.py`). Selection / parameter / interval / config tables that don't carry an NWB FK do not support it.

**Exception — decoding output is not NWB.** `ClusterlessDecodingV1` and the SortedSpikes decoding equivalents store results as `xarray` netCDF (`.nc`) at a `filepath@analysis` external store, with the classifier pickled alongside (`.pkl`). They expose dedicated fetchers: `fetch_results()` (`xr.Dataset`) at `decoding/v1/clusterless.py:453`, `fetch_model()` at `:470`, `fetch_environments()` at `:475` — not `fetch_nwb()`. The storage declaration is at `decoding/v1/clusterless.py:99` (`results_path: filepath@analysis`).

```python
# Fetch NWB objects from an NWB-backed table (e.g. LFPV1, TrodesPosV1, Raw).
# `fetch_nwb()` returns a list and does not enforce one-row cardinality.
rel = Table & key
n_rows = len(rel)
if n_rows != 1:
    raise ValueError(f"key matched {n_rows} rows; tighten before fetch_nwb")
nwb_data = rel.fetch_nwb()

# Access data from NWB object
lfp_series = nwb_data[0]['lfp']
data = lfp_series.data[:]
timestamps = lfp_series.timestamps[:]
```

NWB extensions used (current `pyproject.toml:53-56`): `ndx-franklab-novela>=0.2.4` (Franklab metadata), `ndx-optogenetics==0.3.0`, `ndx-ophys-devices`, `ndx-pose` (pose estimation data).

### SpikeInterface

The spike sorting pipeline uses SpikeInterface for recording preprocessing, running sorters, extracting waveforms, computing quality metrics, and curation.

```python
import spikeinterface as si

# Objects returned by Spyglass:
recording = SpikeSortingOutput().get_recording({"merge_id": mid})  # BaseRecording
sorting = SpikeSortingOutput().get_sorting({"merge_id": mid})      # BaseSorting

# Access data
traces = recording.get_traces(start_frame=0, end_frame=1000)
unit_ids = sorting.get_unit_ids()
spike_train = sorting.get_unit_spike_train(unit_id=0)
```

Available sorters in current Spyglass `SpikeSorterParameters` defaults: `mountainsort4`, `mountainsort5`, `kilosort2_5`, `kilosort3`, `ironclust`, `clusterless_thresholder` (`spikesorting/v1/sorting.py:158-168, 446`). Note `kilosort2_5` (with the underscore-5), not `kilosort2`. Other sorters may be reachable through SpikeInterface but require their own per-sorter wrappers / params rows.

### SpikeInterface / Spyglass version coupling

Spyglass's spike sorting pipeline pins a specific SpikeInterface range.
Installing a different upstream version breaks every stage (recording,
sorter, waveforms, metrics, curation) because SpikeInterface changes its
public API across minor releases.

**Check pinning before debugging sorter/metric errors.**

```bash
python -c 'import spikeinterface; print(spikeinterface.__version__)'
grep -E 'spikeinterface' environment.yml pyproject.toml
```

Common symptom → upstream version that changed it:

| Error fragment | SpikeInterface version that introduced/removed it |
|---|---|
| `module 'spikeinterface' has no attribute 'WaveformExtractor'` | removed after 0.99.x (replaced by `SortingAnalyzer`) |
| `NumpySorting' has no attribute 'from_unit_dict'` | renamed post-0.99 |
| `For recording with dtype=int you must set dtype=float32 OR set a int_scale` | required from 0.97+ |
| `compute_snrs() got an unexpected keyword argument 'num_chunks_per_segment'` | moved under `random_chunk_kwargs_dict` |
| `extract_waveforms() got multiple values for keyword argument 'sparse'` | 0.99+ signature |
| `check_params() got an unexpected keyword argument 'outputs'` | dropped from `detect_peaks` |
| `AttributeError: module 'spikeinterface.core' has no attribute 'BinaryRecordingExtractor'` | renamed to `BinaryFolderRecording` in 0.96; v0 spike-sorting code paths only — v1 does not hit this |

**Fix.** Reinstall SpikeInterface at the pinned version (e.g.
`pip install 'spikeinterface==0.99.1'`) rather than patching the Spyglass
parameter dict. For `MetricParameters`, wrap `num_chunks_per_segment` /
`chunk_size` / `seed` under `random_chunk_kwargs_dict`. For whitening,
use `spikeinterface.preprocessing.whiten(rec, dtype='float32')` or pass
`int_scale=256` — never `float16`. v0 pipeline code paths are not kept
in sync with modern SpikeInterface; migrate to v1.

## Analysis Dependencies

### non_local_detector (Bayesian Decoding)

The decoding pipeline uses non_local_detector classifiers to decode position from clusterless waveform features or sorted spike trains.

```python
from non_local_detector import (
    NonLocalClusterlessDetector,    # Clusterless decoder
    NonLocalSortedSpikesDetector,   # Sorted spikes decoder
    ContFragClusterlessClassifier,  # Continuous fragment (clusterless)
    ContFragSortedSpikesClassifier, # Continuous fragment (sorted)
)

# Spyglass integration (decoding-only convenience; not available on other *Output tables):
model = DecodingOutput.fetch_model(key)      # Returns one of the above classes
results = DecodingOutput.fetch_results(key)  # Returns xarray Dataset
```

### track_linearization

Converts 2D position to 1D linearized position. Used by linearization and decoding pipelines.

```python
from track_linearization import (
    make_track_graph,           # Create networkx graph from coordinates
    get_linearized_position,    # Main linearization function
    plot_track_graph,           # Visualization
)
```

### position_tools

Position pipelines (Trodes and DLC) use these for smoothing, velocity, and distance calculations.

```python
from position_tools import (
    get_distance, get_velocity, get_speed, get_angle,
    get_centroid, interpolate_nan,
)
from position_tools.core import gaussian_smooth
```

### ripple_detection

Ripple pipeline detects sharp-wave ripples; MUA pipeline detects population bursts.

```python
from ripple_detection import (
    Kay_ripple_detector, Karlsson_ripple_detector,
    multiunit_HSE_detector,
)
```

### xarray

Decoding results are stored as xarray Datasets with labeled dimensions.

```python
results = DecodingOutput.fetch_results(key)
posterior = results.acausal_posterior  # DataArray with dims (time, state_bins)
interval_0 = results.where(results.interval_labels == 0, drop=True)
```

## Optional Dependencies

| Package | Install extra | Spyglass integration |
| --------- | -------------- | --------------------- |
| DeepLabCut | `[dlc]` | DLC position pipeline wraps it for pose estimation. Interact via Spyglass tables, not DLC directly |
| keypoint_moseq | `[moseq-cpu]` or `[moseq-gpu]` | Behavior pipeline's MoSeq module for behavioral syllable discovery |
| pynapple | NOT in `pyproject.toml` | `fetch_pynapple()` is wired through `FetchMixin` on NWB-backed tables (same gate as `fetch_nwb()`), but the `pynapple` package itself is not listed as a Spyglass install requirement. Install it explicitly (`pip install pynapple`) if you need this method. |
| sortingview + kachery-cloud | core (`pyproject.toml:51, 68`) | FigURL curation UI for spike sorting; Kachery for NWB file sharing. Installed by Spyglass core, NOT optional. |

## Dependency Tiers

The boundary between "installed by Spyglass core" and "optional / extra-required" comes from `pyproject.toml`. Verify on your install with `pip show <package>` or by reading `pyproject.toml` directly — that file is the source of truth, this table is a routing aid.

| Tier | Packages | Source |
| ------ | ---------- | ----------- |
| **Core** (always installed) | datajoint, pynwb, hdmf, spikeinterface, probeinterface, **sortingview, kachery-cloud, kachery-client, kachery, non_local_detector, track_linearization, position_tools, ripple_detection, xarray, ndx-franklab-novela, ndx-optogenetics, ndx-ophys-devices, ndx-pose** | `pyproject.toml` `dependencies = [...]` |
| **Pose Estimation** | deeplabcut | Optional install extra `[dlc]` |
| **Behavior** | keypoint_moseq | Optional install extras `[moseq-cpu]` / `[moseq-gpu]` |
| **Not installed by Spyglass** | pynapple | Required separately (`pip install pynapple`) when calling `fetch_pynapple()` |
