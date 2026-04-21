# Spyglass Common Tables Reference

## Contents

- [Session and File Management](#session-and-file-management)
- [Time Intervals](#time-intervals)
- [Subject and Lab](#subject-and-lab)
- [Hardware and Devices](#hardware-and-devices)
- [Electrophysiology](#electrophysiology)
- [Filtering](#filtering)
- [Position Tracking](#position-tracking)
- [Behavior and Task](#behavior-and-task)
- [Brain Regions](#brain-regions)
- [Table Relationship Summary](#table-relationship-summary)
- [Discovery Patterns](#discovery-patterns)

Tables in the `spyglass.common` schema. These are the root tables all pipelines depend on.

**Important**: Always verify table structure with `Table.describe()` or `Table.heading` before writing queries that depend on specific column names. This reference provides an overview of table purposes and relationships, not an exhaustive schema copy.

```python
from spyglass.common import (
    Session, Nwbfile, AnalysisNwbfile, IntervalList,
    Subject, LabMember, LabTeam, Institution, Lab,
    ElectrodeGroup, Electrode, Raw,
    DataAcquisitionDevice, CameraDevice, Probe, ProbeType,
    RawPosition, VideoFile, DIOEvents,
    Task, TaskEpoch, BrainRegion, SensorData,
    FirFilterParameters,
)
```

## Session and File Management

### `Nwbfile`

- **Primary Key**: `nwb_file_name`
- Registry of every raw NWB file. All pipelines trace back here.

### `AnalysisNwbfile`

- **Primary Key**: `analysis_file_name`
- Tracks derived NWB files created by pipeline computations.

### `Session`

- **Primary Key**: `nwb_file_name` (FK to Nwbfile)
- One row per recording session. The most common starting point for queries.
- Links to `Subject`, `Institution`, `Lab`
- **Part Tables**: `Session.Experimenter` (maps sessions to lab members), `Session.DataAcquisitionDevice`

```python
# List all sessions
Session.fetch(limit=20)

# Sessions for a specific subject
Session & {'subject_id': 'J16'}

# Check exact schema
Session.describe()
```

## Time Intervals

### `IntervalList`

- **Primary Key**: `nwb_file_name`, `interval_list_name`
- Time windows that gate every analysis. Every pipeline uses intervals.
- `valid_times` attribute: array of [start, stop] timestamps

```python
# All intervals for a session
IntervalList & {'nwb_file_name': nwb_file}

# Get interval times
times = (IntervalList & {
    'nwb_file_name': nwb_file,
    'interval_list_name': '02_r1'
}).fetch1('valid_times')
```

**Interval utility functions** (from `spyglass.common`):

- `interval_list_intersect(interval1, interval2)` — Intersection
- `interval_list_union(interval1, interval2)` — Union
- `interval_list_contains(intervals, timestamps)` — Which timestamps fall within
- `interval_list_excludes(intervals, timestamps)` — Which timestamps fall outside
- `intervals_by_length(intervals, min_length)` — Filter by minimum duration

## Subject and Lab

### `Subject`

- **Primary Key**: `subject_id`
- Animal metadata: sex, species, genotype, description

### `LabMember`

- **Primary Key**: `lab_member_name`
- Used in `Session.Experimenter` and for permissions.

### `LabTeam`

- **Primary Key**: `team_name`
- Groups members for data access control. Part table: `LabTeam.LabTeamMember`.

### `Institution` / `Lab`

Simple lookup tables referenced by Session.

## Hardware and Devices

### `DataAcquisitionDevice`

- **Primary Key**: `data_acquisition_device_name`
- Amplifier/digitizer catalog.

### `CameraDevice`

- **Primary Key**: `camera_name`
- Camera hardware referenced by TaskEpoch.

### `ProbeType`

- **Primary Key**: `probe_type`
- Defines probe category, manufacturer, shank count.
- Use `ProbeType.describe()` for exact fields.

### `Probe`

- **Primary Key**: `probe_id`
- Physical probe instances linked to ProbeType.

## Electrophysiology

### `ElectrodeGroup`

- **Primary Key**: `nwb_file_name`, `electrode_group_name`
- Groups channels on a probe. Links to `BrainRegion` and optionally `Probe`.
- Use `ElectrodeGroup.describe()` for exact fields — includes region, hemisphere, description.

### `Electrode`

- **Primary Key**: `nwb_file_name`, `electrode_id`
- Channel-level metadata (coordinates, region, probe position).
- Use `Electrode.heading` to see all available fields.

### `Raw`

- **Primary Key**: `nwb_file_name` (via Session), plus `interval_list_name` (via IntervalList)
- Entry point for raw ElectricalSeries. Upstream of LFP and spike sorting.
- Use `Raw.describe()` for exact schema.

## Filtering

### `FirFilterParameters`

- **Primary Key**: `filter_name`, `filter_sampling_rate`
- Library of FIR filter kernels used by LFP pipeline.

```python
# See available filters
FirFilterParameters.fetch('filter_name')

# Theta filters
FirFilterParameters & 'filter_name LIKE "Theta%"'
```

## Position Tracking

### `PositionSource`

- **Primary Key**: `nwb_file_name`, `interval_list_name` (FKs to `Session` and `IntervalList`; `common_behav.py:34`).
- Non-PK: `source` (e.g. `"trodes"`, `"dlc"`, `"imported"`), `import_file_name`.
- Part table: `PositionSource.SpatialSeries` — one row per spatial series in the NWB file.
- **Populated by the ingest path, not `populate_all_common`.** `PositionSource.populate()` is a thin wrapper that warns and delegates to `PositionSource.make()`, which calls `insert_from_nwbfile(nwb_file_name)` per unique session. DLC-only sessions that lack a Trodes `'pos N valid times'` interval may skip insertion — see the DLC gotchas in [position_pipeline.md](position_pipeline.md).

### `RawPosition`

- Raw position data from hardware (LEDs, sensors). Upstream of position pipelines.

### `IntervalPositionInfoSelection` / `IntervalPositionInfo`

- `IntervalPositionInfoSelection` (Lookup, `common_position.py:87`) — FK to `PositionInfoParameters` + `IntervalList`. Insert here before `IntervalPositionInfo.populate()`; this is the selection-table step — `IntervalPositionInfo` will not populate without it.
- `IntervalPositionInfo` (Computed, `common_position.py:99`) — FK to `IntervalPositionInfoSelection`. Stores smoothed head position, orientation, and velocity (`head_position_object_id`, `head_orientation_object_id`, `head_velocity_object_id`).

## Behavior and Task

### `Task`

- **Primary Key**: `task_name`
- Lookup of behavioral task definitions.

### `TaskEpoch`

- **Primary Key**: `nwb_file_name`, `epoch`
- Maps each epoch to its task, environment, and camera.

### `VideoFile` / `DIOEvents`

- Video file registry and digital I/O events (TTL pulses, sync lines).

## Brain Regions

### `BrainRegion`

- **Primary Key**: `region_id`
- Standardized anatomical labels (region_name, subregion_name).

## Table Relationship Summary

```text
Nwbfile
└── Session (1:1)
    ├── Subject (many:1)
    ├── Session.Experimenter → LabMember
    ├── IntervalList (1:many)
    ├── ElectrodeGroup (1:many) → BrainRegion
    │   └── Electrode (1:many)
    ├── Raw (1:1)
    ├── TaskEpoch (1:many) → Task, CameraDevice
    ├── RawPosition (1:many)
    ├── VideoFile (1:many)
    └── DIOEvents (1:many)
```

## Discovery Patterns

When you need exact column names or key structure, always check the table directly:

```python
# View full schema definition
Session.describe()

# View all columns
Session.heading

# Primary key fields only
Session.heading.primary_key

# Find common keys between tables for joining
common = set(Table1.heading.names) & set(Table2.heading.names)

# Find relationship path
Table1.parents()
Table2.children()
```

### Common Query Patterns

```python
# Find sessions by experimenter
sessions = (Session.Experimenter & {'lab_member_name': 'Name'}).fetch('nwb_file_name')

# Find electrodes in a brain region
electrodes = Electrode & (BrainRegion & {'region_name': 'CA1'})

# Find electrode groups for a session
ElectrodeGroup & {'nwb_file_name': nwb_file}

# Get valid time intervals matching a pattern
IntervalList & {'nwb_file_name': nwb_file} & 'interval_list_name LIKE "%r1%"'
```

## Writing a custom analysis table backed by an analysis NWB

Any user-defined `dj.Computed` that stores data in `AnalysisNwbfile`
must:

1. **Inherit `SpyglassMixin` first, then `dj.Computed`:**

   ```python
   from spyglass.utils.dj_mixin import SpyglassMixin
   import datajoint as dj

   @schema
   class MyAnalysis(SpyglassMixin, dj.Computed):
       definition = '''
       -> UpstreamTable
       -> AnalysisNwbfile          # literal FK string; do not alias
       ---
       my_object_id: varchar(40)   # or _object_id
       '''
   ```

2. **Use the literal `-> AnalysisNwbfile` FK string** — `FetchMixin`
   recognizes that exact string to wire up `fetch_nwb`. Aliased
   imports work only if you also set
   `_nwb_table = AnalysisNwbfile()` as a class attribute.

3. **Store an `object_id` column** per referenced NWB object; `_object_id`
   is the convention Spyglass's helpers look for.

Without these, `fetch_nwb` raises:

- `NotImplementedError: <Table> does not have a (Analysis)Nwbfile foreign key or _nwb_table attribute`
- `TypeError: proj() missing 1 required positional argument: 'self'` (passing the class instead of an instance)
- `TypeError: join() got an unexpected keyword argument 'log_export'` (missing SpyglassMixin)

Also required for export logging — custom tables without `SpyglassMixin`
are **silently excluded** from `ExportSelection` (see `export.md`
Pitfall #2).
