# External Dependencies Reference


## Contents

- [Core Dependencies](#core-dependencies)
- [Analysis Dependencies](#analysis-dependencies)
- [Optional Dependencies](#optional-dependencies)
- [Dependency Tiers](#dependency-tiers)

Spyglass depends on several external packages. This reference helps you understand what each package does and how Spyglass uses it, so you can write correct code that interacts with these libraries.

## Core Dependencies

### DataJoint (ORM & Database)

**What it does**: Object-relational mapper for MySQL databases, designed for scientific data pipelines.

**How Spyglass uses it**: All tables inherit from DataJoint table types (`dj.Manual`, `dj.Computed`, `dj.Lookup`, `dj.Imported`). DataJoint handles schema definition, data insertion, querying, and dependency tracking.

**Key imports**:
```python
import datajoint as dj
```

**Key concepts**:
- Tables are Python classes with `definition` strings
- Queries use restriction (`&`), join (`*`), projection (`.proj()`)
- `.fetch()` / `.fetch1()` materialize results
- Primary keys define table identity; foreign keys define relationships

### PyNWB + HDMF (NWB Data Format)

**What it does**: Python interfaces for reading/writing Neurodata Without Borders (NWB) files — the standard format for neurophysiology data.

**How Spyglass uses it**: All raw and analysis data is stored in NWB files (HDF5-based). Tables reference NWB objects by `object_id`. The `fetch_nwb()` method on all tables loads NWB data.

**Key imports**:
```python
import pynwb
from pynwb import NWBFile
from hdmf.common import DynamicTable
```

**Key patterns**:
```python
# Fetch NWB objects from a table
nwb_data = (Table & key).fetch_nwb()

# Access data from NWB object
lfp_series = nwb_data[0]['lfp']
data = lfp_series.data[:]
timestamps = lfp_series.timestamps[:]
```

**NWB extensions used**:
- `ndx-franklab-novela` — Franklab recording system metadata
- `ndx-pose` — Pose estimation data structures

### SpikeInterface (Electrophysiology Processing)

**What it does**: Comprehensive Python toolkit for electrophysiology signal processing, spike sorting, and post-processing.

**How Spyglass uses it**: The spike sorting pipeline uses SpikeInterface for recording preprocessing, running sorters, extracting waveforms, computing quality metrics, and curation.

**Key imports**:
```python
import spikeinterface as si
import spikeinterface.extractors as se
import spikeinterface.preprocessing as sip
import spikeinterface.sorters as sis
import spikeinterface.curation as sic
```

**Key objects returned by Spyglass**:
```python
# Get a SpikeInterface recording
recording = SpikeSortingOutput().get_recording({"merge_id": mid})
# Type: spikeinterface.core.BaseRecording

# Get a SpikeInterface sorting
sorting = SpikeSortingOutput().get_sorting({"merge_id": mid})
# Type: spikeinterface.core.BaseSorting

# Access data from recording
traces = recording.get_traces(start_frame=0, end_frame=1000)
sampling_rate = recording.get_sampling_frequency()

# Access data from sorting
unit_ids = sorting.get_unit_ids()
spike_train = sorting.get_unit_spike_train(unit_id=0)
```

**Available sorters**: mountainsort4, kilosort2, kilosort3, clusterless_thresholder, and others via SpikeInterface.

### NumPy, SciPy, Pandas

**Standard scientific Python stack**. Used throughout for array operations, signal processing, and DataFrames.

```python
import numpy as np
import scipy
from scipy import signal, stats
import pandas as pd
```

### Matplotlib

**Visualization**. Used for plotting position trajectories, LFP traces, spike rasters, and decoding results.

```python
import matplotlib.pyplot as plt
```

## Analysis Dependencies

### non_local_detector (Bayesian Decoding)

**What it does**: Bayesian decoding of animal position from neural activity. Implements state-space models with continuous and fragmented observation models.

**How Spyglass uses it**: The decoding pipeline uses non_local_detector classifiers to decode position from clusterless waveform features or sorted spike trains.

**Key classes**:
```python
from non_local_detector import (
    NonLocalClusterlessDetector,    # Clusterless decoder
    NonLocalSortedSpikesDetector,   # Sorted spikes decoder
    ContFragClusterlessClassifier,  # Continuous fragment (clusterless)
    ContFragSortedSpikesClassifier, # Continuous fragment (sorted)
)
```

**Spyglass integration**:
```python
# Fetch fitted model
model = DecodingOutput.fetch_model(key)
# Type: one of the above classes

# Fetch results (xarray Dataset)
results = DecodingOutput.fetch_results(key)
# Contains: acausal_posterior, causal_posterior, interval_labels, etc.
```

### track_linearization (Position Linearization)

**What it does**: Converts 2D animal position to 1D linearized position based on track geometry using HMM.

**How Spyglass uses it**: The linearization pipeline and decoding pipeline use it to project position onto track graphs.

**Key functions**:
```python
from track_linearization import (
    make_track_graph,           # Create networkx graph from coordinates
    get_linearized_position,    # Main linearization function
    plot_track_graph,           # Visualization
    plot_graph_as_1D,          # 1D visualization
)
```

### position_tools (Position Processing)

**What it does**: Signal processing utilities for animal position data.

**How Spyglass uses it**: Position pipelines (both Trodes and DLC) use these for smoothing, velocity computation, and distance calculations.

**Key functions**:
```python
from position_tools import (
    get_distance,       # Euclidean distance between positions
    get_velocity,       # Velocity from position
    get_speed,          # Speed magnitude
    get_angle,          # Angle calculation
    get_centroid,       # Centroid of multiple LEDs
    interpolate_nan,    # NaN interpolation
)
from position_tools.core import gaussian_smooth
```

### ripple_detection (Oscillation Detection)

**What it does**: Detects ripples and other oscillatory events in neural signals.

**How Spyglass uses it**: The ripple pipeline detects sharp-wave ripples; the MUA pipeline detects population bursts.

**Key functions**:
```python
from ripple_detection import (
    Kay_ripple_detector,        # Kay's ripple algorithm
    Karlsson_ripple_detector,   # Karlsson's ripple algorithm
    multiunit_HSE_detector,     # Multi-unit high synchrony events
)
from ripple_detection.core import gaussian_smooth, get_envelope
```

### xarray (Multi-dimensional Data)

**What it does**: N-dimensional labeled arrays and datasets.

**How Spyglass uses it**: Decoding results are stored as xarray Datasets with labeled dimensions (time, state_bins, states).

```python
import xarray as xr

# Decoding results are xarray Datasets
results = DecodingOutput.fetch_results(key)

# Access with dimension labels
posterior = results.acausal_posterior  # DataArray with dims (time, state_bins)
time = results.time.values           # Coordinate values

# Filter by coordinate
interval_0 = results.where(results.interval_labels == 0, drop=True)
```

### probeinterface (Electrode Configuration)

**What it does**: Handles probe/electrode geometry and properties.

**How Spyglass uses it**: Spike sorting recording pipeline uses it to define probe geometry for SpikeInterface.

```python
import probeinterface as pi
```

## Optional Dependencies

### DeepLabCut (Pose Estimation)

**What it does**: Deep learning-based pose estimation from video.

**How Spyglass uses it**: The DLC position pipeline wraps DeepLabCut for project management, training, and inference. Optional dependency — install with `pip install spyglass-neuro[dlc]`.

**Key functions** (called internally by Spyglass):
```python
import deeplabcut
deeplabcut.create_new_project()
deeplabcut.train_network()
deeplabcut.analyze_videos()
```

Users typically interact with DLC through Spyglass tables (`DLCProject`, `DLCModelTraining`, `DLCPoseEstimation`) rather than calling DLC directly.

### keypoint_moseq (Motion Sequencing)

**What it does**: Discovers behavioral syllables from keypoint tracking data using autoregressive HMMs.

**How Spyglass uses it**: The behavior pipeline's MoSeq module trains keypoint-moseq models on pose data. Optional dependency — install with `pip install spyglass-neuro[moseq-cpu]` or `[moseq-gpu]`.

```python
import keypoint_moseq as kpms
```

Used internally by `MoseqModel` computed table.

### pynapple (Time Series Analysis)

**What it does**: Python library for neurophysiology time series analysis with efficient interval-based operations.

**How Spyglass uses it**: Available via `fetch_pynapple()` method on all Spyglass tables.

```python
# Convert Spyglass data to pynapple objects
pynapple_obj = (Table & key).fetch_pynapple()
```

### sortingview + kachery_cloud (Web Visualization & Sharing)

**What it does**: Interactive web-based spike sorting visualization and cloud data sharing.

**How Spyglass uses it**: FigURL curation allows manual spike sorting curation via web interface. Kachery enables cloud-based NWB file sharing.

```python
# Generate curation URI for manual sorting review
from spyglass.spikesorting.v1 import FigURLCurationSelection
FigURLCurationSelection.generate_curation_uri(key)
```

## Dependency Tiers

| Tier | Packages | Required? |
|------|----------|-----------|
| **Core** | datajoint, pynwb, hdmf, numpy, scipy, pandas, matplotlib | Yes |
| **Signal Processing** | spikeinterface, probeinterface | Yes |
| **Analysis** | non_local_detector, track_linearization, position_tools, ripple_detection | Yes |
| **Multi-dim Data** | xarray, h5py | Yes |
| **Pose Estimation** | deeplabcut | Optional (`[dlc]`) |
| **Behavior** | keypoint_moseq | Optional (`[moseq-cpu/gpu]`) |
| **Visualization** | sortingview, kachery_cloud | Optional |
| **Time Series** | pynapple | Optional |
