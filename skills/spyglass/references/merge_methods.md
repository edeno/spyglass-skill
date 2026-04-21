# Merge Table Method Reference

Covers the `_Merge`-base methods that live on merge master tables
(`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`,
`LinearizedPositionOutput`), plus the projected-FK-rename pattern that
merge tables force on downstream computed tables. For mixin-level
methods that apply to every Spyglass table (`fetch_nwb`, `fetch_pynapple`,
`cautious_delete`, `restrict_by`, `<<`/`>>`, helpers like `file_like` and
`dict_to_pk`), see [spyglassmixin_methods.md](spyglassmixin_methods.md).

## Contents

- [Classmethod Restriction Discard (Read First)](#classmethod-restriction-discard-read-first)
- [_Merge Class Methods](#_merge-class-methods)
- [Projected FK rename pattern](#projected-fk-rename-pattern)

## Classmethod Restriction Discard (Read First)

Most `_Merge` methods you reach for are **classmethods** whose restriction parameter defaults to `True` (= every row). Python dispatches classmethod calls to the class regardless of instance context, so `(Table & key).method()` silently discards the `& key` and the method runs with the default — i.e., on the entire table.

**High-impact examples** from `src/spyglass/utils/dj_merge_tables.py`:

| Method | Shape | What silent discard does |
|--------|-------|--------------------------|
| `merge_delete(restriction=True)` (line 444) | `@classmethod`, destructive | Deletes master + all parts across the whole merge table |
| `merge_delete_parent(restriction=True, dry_run=True)` (line 468) | `@classmethod`, destructive (dry_run=True is the only safety net on default) | Same as above plus deletes all part-parent rows |
| `merge_restrict(restriction=True)` (line 424) | `@classmethod`, read-only | Returns a view across the whole table |
| `merge_get_part(restriction=True, ...)` (line 580) | `@classmethod`, read-only (raises on multi-source) | Returns wrong part or raises |
| `merge_get_parent(restriction=True, ...)` (line 657) | `@classmethod`, read-only | Same |
| `merge_view(restriction=True)` (line 400) | `@classmethod`, read-only | Prints the whole table |
| `merge_html(restriction=True)` (line 418) | `@classmethod`, read-only | HTML of whole table |

Plus the staticmethod `Nwbfile.cleanup(delete_files=False)` at `src/spyglass/common/common_nwbfile.py:140` — same shape, same footgun.

**`restriction` parameter type.** The annotations in source read `restriction: str = True` (e.g. `dj_merge_tables.py:469` for `merge_delete_parent`). The `str` annotation is misleading — you can pass:

- a DataJoint restriction **dict** (e.g. `{"nwb_file_name": f}`) — most common;
- a **SQL WHERE string** (e.g. `"nwb_file_name = 'j1620210710_.nwb'"`);
- a **table/query expression** (e.g. `PositionOutput & session_key`);
- or the literal default `True` — which restricts to the whole table and is what makes the classmethod-discard shape so dangerous.

**Always pass the restriction as an argument:**

```python
# ❌ Wrong (shown as a comment so nobody copies it by accident):
#   (PositionOutput & merge_key).merge_delete()
# The `& merge_key` is silently dropped and this call deletes every row.

# ✅ Correct — restriction is the first positional arg:
PositionOutput.merge_delete(merge_key)
PositionOutput.merge_delete_parent(merge_key, dry_run=True)
PositionOutput.merge_restrict(merge_key)
PositionOutput.merge_get_part(merge_key)
PositionOutput.merge_view(merge_key)
```

**Instance methods are safe** — these respect `self.restriction`, so `(Table & key).method()` works as expected: `merge_fetch`, `merge_populate`, `merge_restrict_class`, `merge_get_parent_class`, `fetch_nwb`, `delete` (the mixin override), plus SpyglassMixin helpers like `delete_orphans`, `fetch1`, `fetch`.

If you are uncertain whether a method is a classmethod, read the source or err on the side of passing the restriction as an argument.

#### Import merge masters before cascade-deleting upstream keys

`SpyglassMixin.cautious_delete` walks the DataJoint dependency graph to
cascade deletes and check permissions. The graph only contains tables
whose Python classes have been **imported in the current session**.
Merge masters (`LFPOutput`, `SpikeSortingOutput`, `PositionOutput`,
`LinearizedPositionOutput`) are not auto-imported by `spyglass.common`
— deleting from `Nwbfile`, `Session`, or `IntervalList` without first
importing them raises:

- `NetworkXError: The node \`<schema>.<table>\` is not in the digraph`
- `ValueError: Table <schema>.<name> not found in graph. Please import this table and rerun`

**Fix.** Import all relevant merge masters (and any custom
merge-extending modules in your lab) before the delete:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.lfp import LFPOutput
from spyglass.position.position_merge import PositionOutput
from spyglass.linearization.merge import LinearizedPositionOutput
# plus any lab-specific merge-extending modules
```

The sibling error `ValueError: Please import <merge>.<part> and try
again` (or `DataJointError: Attempt to delete part table ... before
deleting from its master first`) means you're deleting from a part-
table row directly. Always restrict via the master using
`merge_get_part(key)` and delete through `merge_delete(key)`.

## _Merge Class Methods

All merge tables (`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, `LinearizedPositionOutput`) inherit from `_Merge` and have these methods.

### Data Discovery

#### `merge_view(restriction=True)`
Preview the merged structure with null entries for unique columns. Good for exploration.

```python
PositionOutput.merge_view()
# Shows all entries across all part tables with their source
```

#### `merge_restrict(restriction=True) -> dj.U`
Returns restricted merged view as a DataJoint Union. Unlike `merge_view()`, this returns a query object you can further restrict.

```python
# All position data for a session
PositionOutput.merge_restrict({'nwb_file_name': nwb_file})

# Chain further restrictions
PositionOutput.merge_restrict({'nwb_file_name': nwb_file}) & 'source = "TrodesPosV1"'
```

**Do not restrict the merge master directly with upstream keys for
data access.** The master's only primary-key column is `merge_id`;
fields like `nwb_file_name` live on the part tables. A query like
`(LFPOutput & {'nwb_file_name': f}).fetch()` returns no usable rows.
Use `merge_get_part`, `merge_restrict`, or `merge_fetch` instead:

```python
# Find all merge rows for a session, with part-table columns:
LFPOutput.merge_get_part(restriction={'nwb_file_name': f},
                         join_master=True).fetch(as_dict=True)

# Preview unified rows across parts (Nones fill missing columns):
LFPOutput.merge_view(restriction={'nwb_file_name': f})

# Fetch a specific attribute across parts:
LFPOutput.merge_fetch('filter_name', restriction={'nwb_file_name': f})
```

### Finding Part Tables

#### `merge_get_part(restriction, join_master=False, restrict_part=True, multi_source=False, return_empties=False) -> dj.Table`
Returns the part table(s) containing entries matching the restriction. This is the key method for the merge workflow.

**Raises `ValueError`** if zero or multiple sources match when `multi_source=False` (default). Always wrap in try/except or use `multi_source=True`.

**Misleading-error note.** When `merge_get_part` reports
`ValueError: Found multiple potential parts: []` — the empty list means
zero sources matched, not multiple. The usual cause is that the
upstream source table (e.g. `IntervalPositionInfo`) has rows but they
were never inserted into the merge part table (e.g.
`PositionOutput.CommonPos`).

Check:

```python
len(PositionOutput.CommonPos & restriction)    # zero means not inserted
```

Fix by running the merge insert path (e.g. `PositionOutput.insert(...)`
with the correct `part_name`) before retrying the fetch.

```python
# Single source (default) - raises ValueError if 0 or >1 matches
part = PositionOutput.merge_get_part(key)

# Multiple sources allowed
parts = PositionOutput.merge_get_part(key, multi_source=True)

# Join with master table to include merge_id in result
part = PositionOutput.merge_get_part(key, join_master=True)
```

**Common pattern:**
```python
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
# Treat merge_key as an opaque restriction; don't assume it's only
# {"merge_id": ...}. Pass it to `&`, don't read fields out of it.
data = (PositionOutput & merge_key).fetch1_dataframe()
```

#### `merge_get_parent(restriction, join_master=False, multi_source=False) -> dj.FreeTable`
Returns the parent table(s) of part tables matching restriction. Goes one level further than `merge_get_part` — returns the actual source table, not the part table.

```python
parent = PositionOutput.merge_get_parent({'merge_id': merge_id})
```

#### `merge_get_parent_class(source: str) -> dj.Table`
Returns the parent table class for a given source name (CamelCase).

```python
cls = PositionOutput().merge_get_parent_class("TrodesPosV1")
# Returns the TrodesPosV1 table class
```

### Data Fetching

#### `merge_fetch(*attrs, restriction=True, **kwargs) -> list`
Fetch data across all part tables. Similar to `fetch()` but works across the union of all parts. **Instance method** — call on a restricted relation or an instance, not the bare class.

```python
# Correct — instance form:
data = (PositionOutput & {'nwb_file_name': nwb_file}).merge_fetch()
# Also correct — explicit instance + restriction kwarg:
data = PositionOutput().merge_fetch(restriction={'nwb_file_name': nwb_file})
```

#### `fetch1_dataframe(*attrs, **kwargs) -> pd.DataFrame`
Fetch a single entry as a pandas DataFrame. Works by routing to the correct part table's `fetch1_dataframe` method.

```python
df = (PositionOutput & {'merge_id': merge_id}).fetch1_dataframe()
```

#### `fetch_nwb(restriction=None, multi_source=False, return_merge_ids=False, *attrs, **kwargs)`
Fetch NWB file objects from the source tables. This is the merge-table override of the base-mixin `fetch_nwb` at `src/spyglass/utils/dj_merge_tables.py:507` — merge tables need the extra `restriction`, `multi_source`, and `return_merge_ids` kwargs to resolve through the part tables. For the base-mixin signature and behavior on non-merge tables, see [spyglassmixin_methods.md § NWB Data Access](spyglassmixin_methods.md#nwb-data-access).

```python
nwb_objs = (PositionOutput & merge_key).fetch_nwb()
```

### Part Table Management

#### `parts(camel_case=False) -> list`
Returns list of part table objects.

```python
PositionOutput().parts()
# Returns: [PositionOutput.TrodesPosV1, PositionOutput.DLCPosV1, ...]

PositionOutput().parts(camel_case=True)
# Returns part names in CamelCase
```

#### `source_class_dict` (property)
Dictionary mapping part names to their parent classes.

```python
PositionOutput().source_class_dict
# {'TrodesPosV1': TrodesPosV1, 'DLCPosV1': DLCPosV1, ...}
```

#### Stale / orphan merge-part tables

`Merge.parts(camel_case=True)` introspects DB part names and calls
`getattr(module, part_name)`. If a previous Spyglass version declared
a part class (e.g. `ImportedLFPV1`, `ImportedPose`) that has since
been removed from the code, the DB still has the part table but the
Python class is gone. Symptom:

```
AttributeError: module 'spyglass.<pipeline>.<merge>' has no attribute '<PartClass>'
```

raised from `Merge.source_class_dict` / `.fetch_nwb()` on the master.

Find the orphan:

```python
# Substitute the real merge module for your pipeline on the import line,
# e.g. `import spyglass.lfp.lfp_merge as merge_module`.
import spyglass.lfp.lfp_merge as merge_module  # noqa: F401

db_parts = set(MergeMaster.parts(camel_case=True))
py_parts = set(n for n in dir(merge_module))
orphans = db_parts - py_parts
```

Drop the orphan only after confirming no one depends on it:

```python
dj.FreeTable(
    MergeMaster.connection,
    f'`{schema}`.`{master_table}__{orphan_part_name}`',
).drop_quick()
```

Have anyone still on the old Spyglass version upgrade before the
drop — otherwise their client will re-declare the part table.

### Deletion

#### `merge_delete(restriction=True, **kwargs)`
Deletes entries from master and parts matching restriction.

#### `merge_delete_parent(restriction=True, dry_run=True, **kwargs) -> list`
Deletes merge entries, parts, AND parent table entries. Use `dry_run=True` first.

### Population

#### `merge_populate(source: str, keys=None)`
Populates merge table from a source table.

```python
PositionOutput().merge_populate("TrodesPosV1")
```

### Utility

#### `extract_merge_id(restriction) -> Union[dict, list]`
Extracts merge_id from various restriction formats.

#### `get_source_from_key(key: dict) -> str`
Returns the source name for a given key.

---

## Projected FK rename pattern

When a Computed table needs two foreign keys that would collide on a shared primary-key slot, Spyglass uses `.proj(new_name='old_name')` in the table definition to rename one of them. At insert/populate time, pass the *renamed* field — not the original.

Examples in the wild:

- `RippleTimesV1` (ripple.py:186): `-> PositionOutput.proj(pos_merge_id='merge_id')`. Build populate key with `pos_merge_id`, not `merge_id`, because `RippleTimesV1`'s own primary FK into `RippleLFPSelection` already uses a `merge_id` slot via `LFPBandV1`.
- `MuaEventsV1` (mua.py:67–68): *two* renames at once — `PositionOutput.proj(pos_merge_id='merge_id')` and `IntervalList.proj(detection_interval='interval_list_name')`. Populate keys must use both renamed fields.

The pattern is widespread — at least a dozen tables use it, including `LFPBandV1`, `DecodingClusters`, `PoseGroup.Pose`, `SortedSpikesUnit`, and selection tables in `position/v1/` and `spikesorting/`. Grep `.proj(` inside `definition = """` blocks to find them in your own pipeline.

**How to detect it.** Read the target table's `definition`. If you see `.proj(foo='bar')` inside an FK line, `foo` is what your populate key needs, not `bar`. `Table.heading.primary_key` also lists the renamed names, not the originals.
