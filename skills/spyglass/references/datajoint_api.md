# DataJoint & Spyglass API Reference

## Contents

- [DataJoint Core Operators](#datajoint-core-operators)
- [Computed Tables: `make()` and tri-part make](#computed-tables-make-and-tri-part-make)
- [Spyglass-Specific Operators](#spyglass-specific-operators)
- [Table Inspection Commands](#table-inspection-commands)
- [NWB File Commands](#nwb-file-commands)
- [DataFrame Commands](#dataframe-commands)
- [Best Practices](#best-practices)

Complete reference for querying and analyzing neural data with DataJoint operators and Spyglass extensions.

## DataJoint Core Operators

### Restriction (`&`)

Filter rows by key dictionary, SQL string, or another table.

```python
# By key dictionary
Session & {'nwb_file_name': 'j1620210710_.nwb'}

# By SQL condition
Session & 'session_start_time > "2021-07-01"'

# Multiple conditions (AND)
Session & {'subject_id': 'J16'} & 'session_start_time > "2021-07-01"'

# By another table (natural join restriction)
Session & (IntervalList & 'interval_list_name LIKE "%r1%"')
```

### Negative Restriction (`-`)

Exclude rows matching a condition.

```python
# Exclude specific session
Session - {'nwb_file_name': 'bad_file.nwb'}

# Exclude sessions with specific intervals
Session - (IntervalList & 'interval_list_name = "sleep"')
```

### Join (`*`)

Combine tables on matching primary/foreign keys.

```python
# Simple join
Session * Subject

# With projection to avoid key conflicts
(Session * Subject).proj(session_date='session_start_time')
```

**Footgun — dependent-attribute refusal.** `A * B` raises `DataJointError: Cannot join query expressions on dependent attribute '<name>'` when a shared attribute is secondary on *both* sides. Fires at query-build time, not at fetch. Most common Spyglass trigger: `SpikeSortingSelection * SpikeSortingRecordingSelection` (both carry `nwb_file_name` as secondary via different FK paths). Fix with `.proj(pk_or_kept_secondary)` on one side, or split into two restrictions. Full mechanism and worked example: [common_mistakes.md § 9](common_mistakes.md#9--refuses-to-join-on-a-dependent-attribute).

### Projection (`.proj()`)

Rename, compute, or select specific attributes.

```python
# Select specific columns only
Session.proj('nwb_file_name', 'subject_id')

# Rename attribute
Session.proj(session_date='session_start_time')

# Compute new attribute (MySQL expressions)
Session.proj(month='MONTH(session_start_time)')

# Empty projection (primary key only)
Session.proj()
```

### Fetch (`.fetch()` / `.fetch1()`)

Materialize query results.

```python
# Fetch all rows as recarray
(Session & key).fetch()

# Fetch specific attributes as arrays
names, times = (Session & key).fetch('nwb_file_name', 'session_start_time')

# Fetch as list of dicts
(Session & key).fetch(as_dict=True)

# Fetch as pandas DataFrame
(Session & key).fetch(format='frame')

# Fetch with limit
(IntervalList & key).fetch('valid_times', limit=10)

# Fetch single row (errors if not exactly one)
(Session & key).fetch1()

# Fetch single row as dict
(Session & key).fetch1(as_dict=True)

# Fetch primary key only
(Session & key).fetch('KEY')
# Returns list of dicts with only primary key fields
```

**Footgun — too-loose restriction.** `fetch1()` (and universal wrappers like `merge_get_part` and `fetch1_dataframe`) raises "expected one row, got N" when the restriction matches multiple rows. The decoding-only `DecodingOutput.fetch_results` wraps `fetch1()` and shares this behavior — no other `*Output` merge table ships a `fetch_results` method. The usual cause is under-specifying the key: `{"nwb_file_name": nwb_file}` alone typically matches every interval, every parameter set, and every pipeline version for that session. `fetch_nwb()` is a SEPARATE footgun — it silently returns a list across all matching rows, so `[0]`-indexing on an under-specified restriction quietly picks an arbitrary row instead of raising. Fix for both shapes: include enough primary-key fields to pick exactly one row. When unsure what fields exist, print the loose-restriction result first and use it to build a fully-specified key:

```python
# Discover
(SomeTable & {"nwb_file_name": nwb_file})   # shows all matching rows
# Specify (include every primary-key field needed for uniqueness)
key = {"nwb_file_name": nwb_file, "interval_list_name": "02_r1",
       "trodes_pos_params_name": "default"}
```

### DB reads vs. disk reads — know which one you're doing

Spyglass fetch methods split into two categories. Plain DataJoint fetches read metadata from the MySQL DataJoint tables; Spyglass's NWB-aware fetches additionally read files from disk (AnalysisNwbfile in the filestore, `.nc` files for decoding outputs, sometimes Kachery/DANDI pulls). This matters for performance, failure modes, and debugging.

**DB-only reads** (SQL rows from MySQL — fast, ~ms, fail only on connection/cardinality):

- `.fetch()` / `.fetch1()` / `.fetch(as_dict=True)` — returns table rows
- `.fetch('KEY')` — primary-key dicts only
- `.fetch('some_attr')` — a single attribute column
- Restrictions and joins (`&`, `*`, `proj`, `aggr`) — build query, no I/O until you fetch

Use these freely when exploring or finding the right `merge_id`. They are what the inspect phase of merge-table workflows (see SKILL.md) should rely on.

**Disk reads** (opens a file; slower, variable latency; can fail independently of the DB):

- `.fetch_nwb()` — loads an NWB object from the filestore. `SpyglassMixin.fetch_nwb` calls `_download_missing_files` internally (`src/spyglass/utils/mixins/fetch.py:330`), so it will trigger Kachery/DANDI pulls if the file isn't local.
- `.fetch1_dataframe()` — loads a DataFrame from an AnalysisNwbfile. Defined on many tables that store time series, including the `PositionOutput`, `LFPOutput`, and `LinearizedPositionOutput` merge tables and V1 tables like `LFPV1`, `LFPBandV1`, `TrodesPosV1`, `RippleTimesV1`. **Not** on `SpikeSortingOutput` or `DecodingOutput` — those use different data-loading paths.
- `DecodingOutput.fetch_results(key)` — loads an xarray Dataset from an `.nc` file on disk (`src/spyglass/decoding/decoding_merge.py:74`). Decoding-only.
- `DecodingOutput.fetch_model(key)` — loads the trained decoder model from disk (`src/spyglass/decoding/decoding_merge.py:79`). Decoding-only.

Implications for writing Spyglass code:

1. **Confirm cardinality before committing to a disk fetch.** The cardinality check (see `len(rel)` pattern above) is cheap — it's a DB read. A wrong-key `fetch1_dataframe()` wastes disk I/O *and* raises after the slow operation.
2. **Different failure modes.** A `fetch1_dataframe()` can raise `FileNotFoundError` or time out on Kachery even when the table row exists and the restriction is correct — that means the file wasn't synced, not that the query is wrong. Don't debug the restriction; check the filestore.
3. **Prefer one disk fetch over many.** `for k in keys: (T & k).fetch_nwb()` hits the filestore N times. If you need all of them, look for a pipeline-specific batched accessor before rolling your own; HDF5 read concurrency across files generally works but within a single file requires care.
4. **`fetch_nwb()` returns a list, not a scalar.** On a single-row restriction it returns `[nwb_obj]` — a separate gotcha from the disk-vs-DB distinction, covered in SKILL.md Common Mistake #4.

### Aggregation (`.aggr()`)

On-the-fly aggregation across joined tables.

```python
# Count entries per group
Session.aggr(IntervalList, n='count(*)')

# Multiple aggregates
Session.aggr(IntervalList, n='count(*)', max_name='MAX(interval_list_name)')
```

### Universal Set (`dj.U()`)

Create virtual table with unique values.

```python
# Get unique values of an attribute
dj.U('subject_id') & Session

# Count unique values
dj.U().aggr(Session, n='count(*)')
```

### OR-Restriction

Restrict with list of dicts (OR logic).

```python
# Match any of these files
files = Session & [
    {'nwb_file_name': 'fileA.nwb'},
    {'nwb_file_name': 'fileB.nwb'},
]
```

## Computed Tables: `make()` and tri-part make

`dj.Computed` tables populate by defining either:

**Single-method `make(self, key)`** — one monolithic method that fetches upstream data, computes, and inserts, all inside one transaction. This is the classic DataJoint pattern.

**Tri-part `make` — `make_fetch` + `make_compute` + `make_insert`** — DataJoint's newer split-phase pattern. See `autopopulate.py` `make()` docstring in the `datajoint` package for the canonical description. The three methods run in sequence:

```python
class MyComputedTable(SpyglassMixin, dj.Computed):
    definition = """
    -> UpstreamSelection
    ---
    result : blob
    """

    def make_fetch(self, key):
        # All DB reads happen here. Return a tuple of fetched values.
        return [(UpstreamSelection & key).fetch1(...)]

    def make_compute(self, key, upstream_data):
        # Pure computation — no DB access. Return a tuple consumed by make_insert.
        result = do_the_math(upstream_data)
        return [result]

    def make_insert(self, key, result):
        # All DB writes happen here.
        self.insert1({**key, "result": result})
```

**Why the split exists.** Long computations shouldn't hold a DB transaction open — the split lets DataJoint release the DB between `make_fetch` (which reads under a snapshot) and `make_insert` (which writes under its own transaction), with `make_compute` running outside any transaction. Before writing, DataJoint re-runs `make_fetch` and checks the result is unchanged — catching cases where an upstream row was deleted/repopulated mid-compute.

**Which pattern a given Spyglass table uses.** Most v1 tables (e.g., `LFPV1`, `TrodesPosV1`, `SortedSpikesDecodingV1`) still use single-method `make()`. Newer tables with expensive pure-compute stages — e.g., `ClusterlessDecodingV1` — use tri-part make. Check the class body: if you see `make_fetch`/`make_compute`/`make_insert`, it's tri-part; in that case `.make()` won't exist as a direct callable — referring to it as `Table.make()` in code or documentation will mislead.

**Consequence for debugging.** When tracing a populate failure inside a tri-part-make table, identify which of the three phases raised:

- Error in `make_fetch` → upstream data issue (missing row, interval mismatch — Signature F in [runtime_debugging.md](runtime_debugging.md)).
- Error in `make_compute` → bug in the pure function (no DB state matters).
- Error in `make_insert` → schema mismatch, FK violation, or concurrent modification caught by the re-fetch check.

**Consequence for authoring.** If your custom Computed table has a heavy pure-compute step (GPU inference, large numerical work), prefer tri-part — you'll avoid holding a DB transaction for the duration. See [custom_pipeline_authoring.md](custom_pipeline_authoring.md).

## Spyglass-Specific Operators

### Upstream Restriction (`<<`)

Restrict by ancestor attribute — searches **up** the dependency chain. Use when the field you want to filter on belongs to a table upstream of the current table.

```python
# Find all PositionOutput entries for a specific session
PositionOutput() << "nwb_file_name = 'j1620210710_.nwb'"

# Find all SpikeSortingOutput entries for a subject
SpikeSortingOutput() << "subject_id = 'J16'"
```

### Downstream Restriction (`>>`)

Restrict by descendant attribute — searches **down** the dependency chain. Use when the field belongs to a table downstream of the current table.

```python
# Find sessions that have specific position parameters
Session() >> 'trodes_pos_params_name="default"'

# Find sessions that have decoding results
Session() >> 'decoding_param_name="default_decoding"'
```

### Explicit Restriction (`.restrict_by()`)

Same as `<<`/`>>` but with explicit direction parameter.

```python
# Upstream (equivalent to <<)
PositionOutput().restrict_by(
    "nwb_file_name = 'j1620210710_.nwb'",
    direction="up"
)

# Downstream (equivalent to >>)
Session().restrict_by(
    'trodes_pos_params_name="default"',
    direction="down"
)
```

## Table Inspection Commands

```python
# View schema definition with primary/foreign keys
Table.describe()

# View all columns as heading object
Table.heading

# View column names
Table.heading.names
Table.heading.primary_key
Table.heading.secondary_attributes

# View parent/child relationships
Table.parents()
Table.children()

# Find common keys between tables
set(Table1.heading.names) & set(Table2.heading.names)

# Check table size
len(Table & restriction)
```

## NWB File Commands

### Fetch NWB Objects (`.fetch_nwb()`)

Available on all Spyglass tables via SpyglassMixin. Loads NWB data objects.

```python
# Fetch NWB objects for a table entry
nwb_objs = (LFPV1 & key).fetch_nwb()

# Access data from NWB object
lfp_data = nwb_objs[0]['lfp']
```

### Fetch as Pynapple (`.fetch_pynapple()`)

Convert NWB data to pynapple objects for time series analysis.

```python
pynapple_obj = (Table & key).fetch_pynapple()
```

## DataFrame Commands

### Basic DataFrame (`.fetch1_dataframe()`)

Fetch a single entry as pandas DataFrame. Available on merge tables and computed tables that store time series.

```python
position_df = (PositionOutput & merge_key).fetch1_dataframe()
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

### Pose DataFrame (`.fetch_pose_dataframe()`)

Fetch pose keypoint data as DataFrame (position pipeline only).

```python
# All bodyparts (only works for DLC/imported pose sources)
pose_df = (PositionOutput & merge_key).fetch_pose_dataframe()
```

## Best Practices

1. **Always limit large queries**: Use `limit=` to avoid memory issues
2. **Use friendly keys first**: Start with `nwb_file_name`, then get `merge_id`
3. **Preview before fetching**: Use `.fetch(limit=1)` or `.merge_view()` to check structure
4. **Check table relationships**: Use `.describe()`, `.parents()`, `.children()` when joining
5. **Prefer DataJoint over SQL**: Use restriction operators instead of raw SQL queries
6. **Use `as_dict=True`**: When you need to inspect key structure
7. **Use `fetch('KEY')`**: To get only primary key fields for downstream use
