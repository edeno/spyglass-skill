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

**Footgun — too-loose restriction.** `fetch1()` (and universal wrappers like `merge_get_part` and `fetch1_dataframe`) raises `DataJointError: expected one row, got N` when the restriction matches multiple rows. The decoding-only `DecodingOutput.fetch_results` is **NOT** a `fetch1()` wrapper — it routes through `merge_restrict_class` (`utils/dj_merge_tables.py:770`), which raises a different error shape: `ValueError: Ambiguous entry. Data has mult rows in parent: ...` when the restriction matches multiple parent rows. Same diagnostic outcome (under-specified key), distinct error class — pattern-match on `ValueError` for the decoding case. The usual cause is under-specifying the key: `{"nwb_file_name": nwb_file}` alone typically matches every interval, every parameter set, and every pipeline version for that session. `fetch_nwb()` is a SEPARATE footgun — it silently returns a list across all matching rows, so `[0]`-indexing on an under-specified restriction quietly picks an arbitrary row instead of raising. Fix for all shapes: include enough primary-key fields to pick exactly one row. When unsure what fields exist, print the loose-restriction result first and use it to build a fully-specified key:

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
4. **`fetch_nwb()` returns a list of dicts.** Each dict carries the row's fetched fields plus the loaded NWB object(s) keyed by attribute name (`utils/mixins/fetch.py:284, 319`); a single-row restriction still returns a 1-element list — index `[0]` and read the NWB by key (e.g. `nwb_objs[0]["lfp"]`). Separate gotcha from the disk-vs-DB distinction; also covered in SKILL.md Common Mistake #4.

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
        return [(UpstreamSelection & key).fetch1(...)]

    def make_compute(self, key, upstream_data):
        result = do_the_math(upstream_data)
        return [result]

    def make_insert(self, key, result):
        self.insert1({**key, "result": result})
```

**Why the split exists.** Long computations shouldn't hold a DB transaction open — the split lets DataJoint release the DB between `make_fetch` (which reads under a snapshot) and `make_insert` (which writes under its own transaction), with `make_compute` running outside any transaction. Before writing, DataJoint re-runs `make_fetch` and checks the result is unchanged — catching cases where an upstream row was deleted/repopulated mid-compute.

**Which pattern a given Spyglass table uses.** Most v1 tables (e.g., `LFPV1`, `TrodesPosV1`, `SortedSpikesDecodingV1`) still use single-method `make()`. Newer tables with expensive pure-compute stages — e.g., `ClusterlessDecodingV1` — use tri-part make. Check the class body: if you see `make_fetch`/`make_compute`/`make_insert`, it's tri-part; the class doesn't define its own monolithic `make()` (DataJoint's inherited `AutoPopulate.make` orchestrates the three phases — `datajoint/autopopulate.py:96, 399`), so when reasoning about behavior or stack traces, inspect the three phase methods on the class instead of looking for a single `make()` body.

**Consequence for debugging.** When tracing a populate failure inside a tri-part-make table, identify which of the three phases raised:

- Error in `make_fetch` → upstream data issue (missing row, interval mismatch — Signature F in [runtime_debugging.md](runtime_debugging.md)).
- Error in `make_compute` → bug in the pure function (no DB state matters).
- Error in `make_insert` → schema mismatch, FK violation, or concurrent modification caught by the re-fetch check.

**Consequence for authoring.** If your custom Computed table has a heavy pure-compute step (GPU inference, large numerical work), prefer tri-part — you'll avoid holding a DB transaction for the duration. See [custom_pipeline_authoring.md](custom_pipeline_authoring.md).

## Spyglass-Specific Operators

These graph-search helpers are useful for interactive exploration. They are
not the preferred way to build production keys for merge masters: for
`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, etc.,
prefer `merge_restrict(...)` / `merge_get_part(...)` when the next step is
`fetch1`, `populate`, deletion, or generated code.

### Upstream Restriction (`<<`)

Restrict by ancestor attribute — searches **up** the dependency chain. Use when the field you want to filter on belongs to a table upstream of the current table.

```python
# Exploratory: find all PositionOutput entries for a specific session.
# For copyable merge-table code, prefer PositionOutput.merge_restrict(...).
PositionOutput() << "nwb_file_name = 'j1620210710_.nwb'"

# Exploratory: find all SpikeSortingOutput entries for a subject.
# For copyable merge-table code, prefer SpikeSortingOutput.merge_restrict(...).
SpikeSortingOutput() << "subject_id = 'J16'"
```

### Downstream Restriction (`>>`)

Restrict by descendant attribute — searches **down** the dependency chain. Use when the field belongs to a table downstream of the current table.

```python
# Find sessions that have specific position parameters
Session() >> 'trodes_pos_params_name="default"'

# Find sessions that have decoding results. `DecodingParameters`
# ships defaults at module-import time keyed on
# f"<shape>_<source>_{non_local_detector_version}"
# (e.g. "contfrag_clusterless_v1.2.0"; see decoding/v1/core.py:48).
# There is no "default_decoding" row — pick a real param-name
# value (or use a LIKE pattern) for this restriction.
Session() >> 'decoding_param_name LIKE "contfrag_clusterless%"'
```

### Explicit Restriction (`.restrict_by()`)

Same as `<<`/`>>` but with explicit direction parameter.

```python
# Upstream (equivalent to <<; exploratory on merge masters)
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

For LLM answers, prefer the bundled scripts when they can answer the
question: `code_graph.py describe/path/find-method` for source facts, and
`db_graph.py describe/find-instance/path` for runtime headings, counts,
rows, and DB adjacency. Use the interactive DataJoint forms below inside
the user's Python session or when a script cannot see the needed context.

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

# Full transitive walk (every upstream prerequisite / downstream consumer).
# Both return table NAMES by default (`datajoint/table.py:220`); pass
# `as_objects=True` for FreeTable objects you can introspect, but they
# are NOT a restrictable relation — `Table.descendants() & {key: ...}`
# silently does the wrong thing. Loop over `as_objects=True` and
# restrict each table individually, or use `db_graph.py path`.
Table.ancestors()    # all tables this one depends on, recursively
Table.descendants()  # all tables that depend on this one, recursively

# Find common keys between tables
set(Table1.heading.names) & set(Table2.heading.names)

# Check table size
len(Table & restriction)
```

## NWB File Commands

### Fetch NWB Objects (`.fetch_nwb()`)

Inherited via `SpyglassMixin` (from `FetchMixin`), but only resolves on **NWB-backed tables** — those that FK to `Nwbfile` / `AnalysisNwbfile` or set `_nwb_table = ...`. Calling it on a table without that FK (selection / parameter / interval / config tables) raises `NotImplementedError` from `FetchMixin._nwb_table_tuple`. Loads NWB data objects when available.

**Exception — decoding tables.** `ClusterlessDecodingV1` (and the SortedSpikes decoding equivalents) store results as xarray netCDF (`.nc`) + a pickled classifier, not NWB. They expose dedicated `fetch_results()` / `fetch_model()` / `fetch_environments()` methods instead of `fetch_nwb()`. See `decoding/v1/clusterless.py:99` (results_path declaration) and the `fetch_results` method nearby.

```python
# Fetch NWB objects for a table entry (NWB-backed: LFPV1, TrodesPosV1, Raw, ...).
# `fetch_nwb()` returns a list and does not enforce one-row cardinality.
rel = LFPV1 & key
n_rows = len(rel)
if n_rows != 1:
    raise ValueError(f"key matched {n_rows} rows; tighten before fetch_nwb")
nwb_objs = rel.fetch_nwb()

# Access data from NWB object
lfp_data = nwb_objs[0]['lfp']
```

### Fetch as Pynapple (`.fetch_pynapple()`)

Same NWB-backed-table gate as `fetch_nwb()`: resolves only on tables with an (Analysis)Nwbfile FK or `_nwb_table` attribute. Converts NWB data to pynapple objects for time series analysis.

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
2. **Use evidence before code**: For source facts, run `code_graph.py`; for runtime headings, row counts, merge IDs, or custom tables, run `db_graph.py`. For merge discovery, start with friendly keys like `nwb_file_name`, then resolve candidate `merge_id` values with merge-aware helpers.
3. **Preview before fetching**: Use `.fetch(limit=1)` or `.merge_view()` to check structure
4. **Check table relationships**: Use `.describe()`, `.parents()`, `.children()` when joining
5. **Prefer DataJoint over SQL**: Use restriction operators instead of raw SQL queries
6. **Use `as_dict=True`**: When you need to inspect key structure
7. **Use `fetch('KEY')`**: To get only primary key fields for downstream use
