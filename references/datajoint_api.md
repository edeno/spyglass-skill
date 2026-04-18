# DataJoint & Spyglass API Reference


## Contents

- [DataJoint Core Operators](#datajoint-core-operators)
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

**Footgun — too-loose restriction.** `fetch1()` (and anything that wraps it — `merge_get_part`, `fetch_nwb`, `fetch_results`, `fetch1_dataframe`) raises "expected one row, got N" when the restriction matches multiple rows. The usual cause is under-specifying the key: `{"nwb_file_name": nwb_file}` alone typically matches every interval, every parameter set, and every pipeline version for that session. Fix: include enough primary-key fields to pick exactly one row. When unsure what fields exist, print the loose-restriction result first and use it to build a fully-specified key:

```python
# Discover
(SomeTable & {"nwb_file_name": nwb_file})   # shows all matching rows
# Specify (include every primary-key field needed for uniqueness)
key = {"nwb_file_name": nwb_file, "interval_list_name": "02_r1",
       "trodes_pos_params_name": "default"}
(SomeTable & key).fetch1()                   # now safe
```

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
