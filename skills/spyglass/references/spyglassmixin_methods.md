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
Fetch NWB file objects for table entries. Automatically handles both raw `Nwbfile` and analysis `AnalysisNwbfile` sources. Downloads missing files from Dandi/Kachery if needed. Defined at `src/spyglass/utils/mixins/fetch.py:284`. Merge masters (`PositionOutput`, `LFPOutput`, etc.) override this with an extended signature that takes `restriction`, `multi_source`, and `return_merge_ids` kwargs — see [merge_methods.md § Data Fetching](merge_methods.md#data-fetching).

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
Permission-checked deletion. Checks that the user is an admin or on a team with the session's experimenter(s). Walks the DataJoint dependency graph to cascade the delete — if any descendant class (especially a merge master) is not imported in the current session, the walk fails with `NetworkXError: ... not in the digraph`. See [merge_methods.md § Import merge masters before cascade-deleting](merge_methods.md#import-merge-masters-before-cascade-deleting-upstream-keys).

### `delete(*args, **kwargs)`
Alias for `cautious_delete`.

### `super_delete(warn=True, *args, **kwargs)`
Bypass permission checks **and** Spyglass's analysis-file cleanup — aliases straight to `datajoint.Table.delete`. DB rows are removed but `.nwb` files stay on disk; follow up with `AnalysisNwbfile().cleanup(dry_run=True)` → review → `dry_run=False`. Use only for legitimate admin cleanup, not to silence permission errors (the right fix there is wiring the user into `LabMember.LabMemberInfo`).

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
Populate computed table entries. Defined at `src/spyglass/utils/mixins/populate.py:48` as a superset of `datajoint.Table.populate` that adds before/after upstream-hash checking and parallel process support.

Kwargs the mixin handles directly (popped before delegating to DataJoint):
- `processes` (default `1`) — number of worker processes. Only honored when the table sets `_parallel_make = True` on the class; otherwise falls through to single-process populate. Must use `use_transaction=True` with `processes > 1` (enforced; otherwise raises `RuntimeError`).
- `use_transaction` (default: class `_use_transaction`, usually `True`) — wraps each `make()` in a DB transaction so a mid-populate failure rolls back cleanly. Set `False` only for tables with long-running `make()` bodies that can't hold a transaction; then the mixin does a manual upstream-hash check and deletes any rows that were inserted into a table whose parents changed during the run.

Kwargs passed through to `datajoint.Table.populate`:
- `reserve_jobs=True` — acquire a row in the `~jobs` table before each `make()` so parallel workers don't duplicate work. Required when running multiple `populate()` processes in different terminals against the same table.
- `suppress_errors=True` — continue on `make()` exceptions, logging into `~jobs` instead of raising. Pair with a follow-up `Table().fetch_jobs(status="error")` to inspect failures.
- `display_progress=True` — show a tqdm bar over the key set.
- `limit=N` — process at most N keys from the key source.
- Positional `*restrictions` — each is applied to `key_source` before fetching keys to populate.

Class attributes that shape populate behavior: `_use_transaction` (default transaction choice), `_parallel_make` (enable multi-process), `_allow_insert` (allow `make()` to insert into tables other than itself).

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
