# Spyglass Common Tables Reference

Spyglass-managed common-ingest tables — sessions/files, intervals, electrodes/devices, brain regions, and task/lab metadata. For DataJoint operators on these tables, see [datajoint_api.md](datajoint_api.md).

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

**Important**: Always verify table structure before writing queries that
depend on specific column names. Use `code_graph.py describe` for
source-declared structure, `db_graph.py describe` for the connected
database, or `Table.describe()` / `Table.heading` inside the user's Python
session. This reference is an overview, not an exhaustive schema copy.

**Adjacent concepts.** Group tables (`SortedSpikesGroup`, `PositionGroup`, `UnitSelectionParams`) live in pipeline-specific schemas, not in `common`, but the shape recurs across pipelines — see [group_tables.md](group_tables.md). Merge tables similarly live in pipeline schemas — see [merge_methods.md](merge_methods.md).

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
- **Part tables**: `Probe.Shank`, `Probe.Electrode` (channel-level metadata, populated by ingestion).

## Electrophysiology

### `ElectrodeGroup`

- **Primary Key**: `nwb_file_name`, `electrode_group_name`
- Groups channels on a probe. Links to `BrainRegion` and optionally `Probe`.
- Use `ElectrodeGroup.describe()` for exact fields — includes region, hemisphere, description.

### `Electrode`

- **Primary Key**: `nwb_file_name`, `electrode_group_name`, `electrode_id` (inherits `nwb_file_name`, `electrode_group_name` from `ElectrodeGroup`; adds own `electrode_id`).
- Channel-level metadata (coordinates, region, probe position).
- Use `Electrode.heading` to see all available fields.

### `Raw`

- **Primary Key**: `nwb_file_name` (inherited from Session). `interval_list_name` is a **dependent FK** to `IntervalList` (declared below the `---` divider), not part of the PK — see `common_ephys.py:276`. Verify with `code_graph.py describe Raw` (each attribute carries `in_pk: true|false`).
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
- **Populated during `insert_sessions()` via `populate_all_common()`.** `insert_sessions` writes the `Nwbfile` row, then calls `populate_all_common()` (`spyglass/data_import/insert_sessions.py:90`); `populate_all_common` lists `PositionSource` in its table sequence at line 227 and special-cases its key source down to just `nwb_file_name` (line 137) because the per-session insert is idempotent across `interval_list_name`. You can also call `PositionSource().insert_from_nwbfile(nwb_file_name)` directly. DLC-only sessions that lack a Trodes `'pos N valid times'` interval may skip insertion — see the DLC gotchas in [position_dlc_v1_pipeline.md](position_dlc_v1_pipeline.md).

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
- **`VideoFile` field-ownership trap.** `VideoFile` is PK-keyed by `-> TaskEpoch` + `video_file_num`. `camera_name: varchar(80)` is a **secondary attribute** — *not* a declared `-> CameraDevice` FK (`common_behav.py:470`). The string match is enforced at ingest, not by the relational layer: `VideoFile._prepare_video_entry()` checks `CameraDevice & {"camera_name": camera_name}` and raises `KeyError` if no row matches (`common_behav.py:506`). FK propagation does *not* carry the camera identity from `VideoFile` to `CameraDevice` — to resolve cameras for a session, restrict `VideoFile` by `nwb_file_name`, fetch distinct `camera_name`, then restrict or join `CameraDevice` on that shared name (a natural join works because both tables expose `camera_name`; it just is not FK-driven). Do not write `CameraDevice & {"nwb_file_name": ...}` (no such field) and do not assume a declared FK path from `VideoFile` to `CameraDevice`. Distinct from `TaskEpoch`, which has both `-> [nullable] CameraDevice` and a separate `camera_names: blob` (plural list per epoch, `common_task.py:124`).

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

When you need exact column names or key structure, use the bundled scripts
first when answering outside the user's live notebook: `code_graph.py
describe <Class> --json` for source-declared keys/FKs, or `db_graph.py
describe <Class> --count --json` for the connected database's runtime
heading and row count. Inside a Python session, the equivalent direct
DataJoint checks are:

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
       -> AnalysisNwbfile          # adds the analysis_nwbfile FK
       ---
       my_object_id: varchar(80)   # match the width used by your source
       '''
   ```

2. **Make sure the table has exactly one analysis-NWB parent.**
   `FetchMixin._nwb_table_tuple` (`spyglass/utils/mixins/fetch.py:48-72`)
   detects analysis files by walking `self.parents()` and matching
   any parent whose table name ends in `` `analysis_nwbfile` ``.
   Common-vs-custom analysis tables are then disambiguated through
   `AnalysisRegistry().get_class(...)`. More than one analysis-NWB
   parent raises (multiple-parents check at `fetch.py:53-57`); zero
   analysis-NWB parents falls back to an explicit `_nwb_table` class
   attribute, then to a literal `-> Nwbfile` FK for raw files
   (`fetch.py:72-76`). Practically: declare ONE
   `-> AnalysisNwbfile` (or one `-> CustomAnalysisNwbfile`) on the
   table, OR set `_nwb_table = AnalysisNwbfile()` deliberately as a
   class attribute. Don't do both, and don't declare two
   analysis-NWB FKs.

3. **Store an `object_id` column** per referenced NWB object; the
   `_object_id` suffix is the convention Spyglass's helpers look for.
   Match the `varchar` width used by your source / sibling tables —
   common-tier tables often use `varchar(40)` (e.g.
   `common_position.py:109`); newer tables often use `varchar(80)`
   (e.g. `position/v1/position_dlc_selection.py:49`). Pick the wider
   form when in doubt.

Without these, `fetch_nwb` raises:

- `NotImplementedError: <Table> does not have a (Analysis)Nwbfile foreign key or _nwb_table attribute`
- `TypeError: proj() missing 1 required positional argument: 'self'` (passing the class instead of an instance)
- `TypeError: join() got an unexpected keyword argument 'log_export'` (missing SpyglassMixin)

Also required for export logging — custom tables without `SpyglassMixin`
are **silently excluded** from `ExportSelection` (see `export.md`
Pitfall #2).
