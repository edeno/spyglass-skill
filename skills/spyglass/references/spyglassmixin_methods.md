# SpyglassMixin Method Reference

All Spyglass tables inherit from `SpyglassMixin`. These methods are
available on every table in the database. For merge-table-specific
methods (`merge_get_part`, `merge_restrict`, `merge_delete`, etc.)
see [merge_methods.md](merge_methods.md); this file covers the
methods that live on the mixin itself and therefore apply to any
Spyglass table — merge master, merge part, selection, computed, or
manual.

## Contents

- [NWB Data Access](#nwb-data-access)
- [Upstream/Downstream Restriction](#upstreamdownstream-restriction)
- [Deletion (Mixin)](#deletion-mixin)
- [Helper Methods](#helper-methods)
- [Population (Mixin)](#population-mixin)
- [Table Inspection](#table-inspection)
- [Storage](#storage)
- [Parameters](#parameters)
- [Thread Safety](#thread-safety)

## NWB Data Access

### `fetch_nwb(*attrs, **kwargs) -> list[dict]`
Fetch NWB file objects for table entries. Automatically handles both raw `Nwbfile` and analysis `AnalysisNwbfile` sources. Downloads missing files from Dandi/Kachery if needed.

```python
nwb_data = (LFPV1 & key).fetch_nwb()
# Returns list of dicts with NWB object fields
```

### `fetch_pynapple(*attrs, **kwargs)`
Convert NWB data to pynapple objects for time series analysis.

```python
pynapple_obj = (Table & key).fetch_pynapple()
```

## Upstream/Downstream Restriction

**Performance caveat**: `<<`, `>>`, and `restrict_by()` traverse the dependency graph heuristically and can be ~10x slower than direct joins on long chains. They also may warn or return ambiguous results if the graph has multiple paths between tables. Use them for interactive exploration and debugging; prefer explicit joins or merge-table methods for production code and long-running scripts.

### `restrict_by(restriction=True, direction='up', return_graph=False, verbose=False) -> QueryExpression`
Restrict table by searching up or down the dependency chain for matching fields.

```python
# Find position outputs for a session (searches up for nwb_file_name)
PositionOutput().restrict_by("nwb_file_name = 'file.nwb'", direction="up")

# Find sessions with specific params (searches down)
Session().restrict_by('trodes_pos_params_name="default"', direction="down")
```

### `__lshift__(restriction)` (operator `<<`)
Shorthand for `restrict_by(restriction, direction="up")`.

```python
PositionOutput() << "nwb_file_name = 'file.nwb'"
```

### `__rshift__(restriction)` (operator `>>`)
Shorthand for `restrict_by(restriction, direction="down")`.

```python
Session() >> 'trodes_pos_params_name="default"'
```

### `ban_search_table(table)` / `unban_search_table(table)` / `see_banned_tables()`
Control which tables are excluded from restrict_by graph traversal.

## Deletion (Mixin)

### `cautious_delete(force_permission=False, dry_run=False, *args, **kwargs)`
Permission-checked deletion. Checks that the user is an admin or on a team with the session's experimenter(s).

### `delete(*args, **kwargs)`
Alias for `cautious_delete`.

### `super_delete(warn=True, *args, **kwargs)`
Bypass permission checks. Use with caution.

## Helper Methods

### `dict_to_pk(key) -> dict`
Extract only primary key fields from a dictionary.

```python
Session().dict_to_pk({'nwb_file_name': 'file.nwb', 'extra_field': 'ignored'})
# Returns: {'nwb_file_name': 'file.nwb'}
```

### `dict_to_full_key(key) -> dict`
Extract all fields that match the table's heading from a dictionary.

### `camel_name` (property)
Returns table name in CamelCase format.

### `file_like(name=None, **kwargs) -> QueryExpression`
Wildcard search on file name fields.

```python
Session().file_like('j16%')
# Finds sessions with nwb_file_name matching 'j16%'
```

### `restrict_by_list(field: str, values: list, return_restr=False) -> QueryExpression`
Restrict table by a list of values for a specific field.

```python
Session().restrict_by_list('nwb_file_name', ['file1.nwb', 'file2.nwb'])
```

### `find_insert_fail(key)`
Identifies which parent table is causing an IntegrityError on insert. Useful for debugging.

### `get_fully_defined_key(key=None, required_fields=None) -> dict`
Gets complete primary key, prompting user for missing fields if needed.

### `ensure_single_entry(key=True)`
Validates that a key corresponds to exactly one table entry.

### `load_shared_schemas(additional_prefixes=None)`
Loads shared schemas for graph traversal (needed for `restrict_by` across schemas).

## Population (Mixin)

### `populate(*restrictions, **kwargs)`
Populate computed table entries. Supports parallel processing via `_parallel_make` class variable.

## Table Inspection

### `describe()`
View schema definition with primary and foreign keys.

### `heading`
View all columns as a heading object.

### `parents()` / `children()`
View parent/child table relationships.

## Storage

### `get_table_storage_usage(human_readable=False, show_progress=False)`
Gets total size of analysis files referenced by this table.

### `delete_orphans(dry_run=True, **kwargs)`
Find and delete entries that have no child table entries.

## Parameters

### `get_params_blob_from_key(key: dict, default="default") -> dict`
Gets the params blob from a parameter table using a key.

```python
params = TrodesPosParams().get_params_blob_from_key({'trodes_pos_params_name': 'default'})
```

## Thread Safety

### `check_threads(detailed=False, all_threads=False) -> DataFrame`
Check for locked threads in the database.
