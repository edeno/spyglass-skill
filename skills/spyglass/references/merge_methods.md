# Merge Table Method Reference

Covers the `_Merge`-base methods that live on merge master tables
(`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`,
`LinearizedPositionOutput`), plus the projected-FK-rename pattern that
merge tables force on downstream computed tables. For mixin-level
methods (`cautious_delete`, `restrict_by`, `<<`/`>>`, `file_like`,
`dict_to_pk`, ...) plus the **NWB-backed-table-only** `fetch_nwb` /
`fetch_pynapple` (which raise `NotImplementedError` on tables without
an `Nwbfile` / `AnalysisNwbfile` FK), see
[spyglassmixin_methods.md](spyglassmixin_methods.md).

## Contents

- [Is this a merge table?](#is-this-a-merge-table)
- [Silent wrong-count footgun](#silent-wrong-count-footgun)
- [Classmethod Restriction Discard (Read First)](#classmethod-restriction-discard-read-first)
- [Import merge masters before cascade-deleting](#import-merge-masters-before-cascade-deleting-upstream-keys)
- [Merge-table methods — discovery, finding, fetching](#merge-table-methods--discovery-finding-fetching)
- [Merge-table methods — lifecycle (parts, deletion, population)](#merge-table-methods--lifecycle-parts-deletion-population)
- [Per-master method availability](#per-master-method-availability)
- [Projected FK rename pattern](#projected-fk-rename-pattern)

## Is this a merge table?

Before reaching for any of the methods below, confirm the table actually
inherits from `_Merge`. The skill's most common merge-related mistake is
treating a lookalike class as a merge table — e.g., calling
`MuaEventsV1.merge_get_part(...)` (no such method; `MuaEventsV1` is
`dj.Computed`).

**The five merge masters in Spyglass** — these are the tables that
inherit `class Foo(_Merge, SpyglassMixin)` and carry `merge_id` as their
only primary-key column:

| Merge master (source) | Import path | Purpose |
|-----------------------|-------------|---------|
| `SpikeSortingOutput` (`src/spyglass/spikesorting/spikesorting_merge.py:34`) | `spyglass.spikesorting.spikesorting_merge` | Unifies v0 + v1 sorting outputs |
| `LFPOutput` (`src/spyglass/lfp/lfp_merge.py:16`) | `spyglass.lfp.lfp_merge` | Unifies `LFPV1`, `ImportedLFP`, etc. |
| `PositionOutput` (`src/spyglass/position/position_merge.py:24`) | `spyglass.position.position_merge` | Unifies `TrodesPosV1`, `DLCPosV1`, `CommonPos`, `ImportedPose` |
| `LinearizedPositionOutput` (`src/spyglass/linearization/merge.py:13`) | `spyglass.linearization.merge` | Unifies linearization pipeline outputs |
| `DecodingOutput` (`src/spyglass/decoding/decoding_merge.py:19`) | `spyglass.decoding.decoding_merge` | Unifies `ClusterlessDecodingV1` + `SortedSpikesDecodingV1` |

**Common lookalikes that are NOT merge tables.** All of these are
`dj.Computed` or `dj.Manual` — they have their own PKs and respond to
normal `& {"nwb_file_name": f}` restrictions; do not call `merge_*`
methods on them:

- `MuaEventsV1` (`dj.Computed` at `src/spyglass/mua/v1/mua.py:63`)
- `CurationV1` (`dj.Manual` at `src/spyglass/spikesorting/v1/curation.py:30`)
- `SpikeSorting`, `LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1` — all `dj.Computed`
- `SpikeSortingSelection`, `SpikeSortingRecordingSelection`, `LFPSelection` and other `*Selection` tables — all `dj.Manual`

**Quick check in Python:**

```python
from spyglass.utils.dj_merge_tables import Merge
isinstance(SomeTable(), Merge)   # True only for the five masters above
```

## Silent wrong-count footgun

Restricting a merge master by a field that lives on its **part tables**
produces a silent no-op — not an error, not zero rows. The merge
master's only PK is `merge_id`, so a restriction like
`{"nwb_file_name": "j1620210710_.nwb"}` references a field the master
doesn't have. DataJoint silently drops the restriction and the `&`
returns the full table.

```python
# ❌ Silently wrong — returns every row in DecodingOutput, not the
#    rows for this session.
len(DecodingOutput & {"nwb_file_name": "j1620210710_.nwb"})
# 2735   (the entire table)

# ❌ Also silently wrong for the same reason, even though it looks
#    like a "multi-session" restriction:
files = ["a_.nwb", "b_.nwb", "c_.nwb", "d_.nwb"]
len(DecodingOutput & [{"nwb_file_name": f} for f in files])
# 2735   (still the entire table)

# ✅ Correct — merge_restrict walks the part tables to resolve
#    attributes that aren't on the master.
len(DecodingOutput.merge_restrict({"nwb_file_name": "j1620210710_.nwb"}))
# 7   (actual rows for this session)

# ✅ Canonical "count rows across a set of sessions" pattern:
total = sum(
    len(DecodingOutput.merge_restrict({"nwb_file_name": f}))
    for f in files
)
```

The same silent no-op happens with `.fetch()`, `.fetch1()`, `len()`,
and any operation that consumes the `&`-restricted relation. The
failure shape is uniform: a *plausibly sized* number or set of rows,
no exception, no warning. Pairing the bad pattern with the correct one
in the same diff is the only reliable way to catch it in review.

**When the field really is on the master.** `source` is an attribute
of the master (it names the part table). `DecodingOutput & {"source":
"SortedSpikesDecodingV1"}` is fine. The footgun is specifically
upstream-session / upstream-interval attributes.

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

## Import merge masters before cascade-deleting upstream keys

When describing a cascade chain that traverses a merge master, write the merge hop explicitly — `LFPV1 → LFPOutput.LFPV1 → LFPBandSelection → LFPBandV1`, not `LFPV1 → LFPBandV1`. The Output-named master sits between the Computed table and its downstream consumers; eliding it produces a chain that looks plausible but doesn't match `Table.descendants()`. See [feedback_loops.md § Verify behavior, trust identity](feedback_loops.md#verify-behavior-trust-identity) for the full pattern.

`SpyglassMixin.cautious_delete` walks the DataJoint dependency graph to
cascade deletes and check permissions. The graph only contains tables
whose Python classes have been **imported in the current session**.
None of the five merge masters (`LFPOutput`, `SpikeSortingOutput`,
`PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput`) are
auto-imported by `spyglass.common` — deleting from `Nwbfile`,
`Session`, or `IntervalList` without first importing them raises:

- `NetworkXError: The node \`<schema>.<table>\` is not in the digraph`
- `ValueError: Table <schema>.<name> not found in graph. Please import this table and rerun`

**Fix.** Import all relevant merge masters (and any custom
merge-extending modules in your lab) before the delete:

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.lfp.lfp_merge import LFPOutput
from spyglass.position.position_merge import PositionOutput
from spyglass.linearization.merge import LinearizedPositionOutput
from spyglass.decoding.decoding_merge import DecodingOutput
# plus any lab-specific merge-extending modules
```

The sibling error `ValueError: Please import <merge>.<part> and try
again` (or `DataJointError: Attempt to delete part table ... before
deleting from its master first`) means you're deleting from a part-
table row directly. Always restrict via the master using
`merge_get_part(key)` and delete through `merge_delete(key)`.

## Merge-table methods — discovery, finding, fetching

Read-only methods inherited from `_Merge` for exploring merge contents, resolving a merge entry to its part table, and fetching data through the merge. All five merge masters (`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, `LinearizedPositionOutput`) share these.

### When to pick `merge_restrict` vs `merge_get_part`

Both accept the same restriction shapes and both are classmethods — they differ in what they return:

| Method | Returns | Use when |
| --- | --- | --- |
| `merge_restrict(restriction)` | `dj.U` — a unified view across all parts (secondary attrs become `NULL` where a part lacks them) | You don't know which part the entry lives in, or you want a single query over the whole merge. Good for `.fetch1('KEY')` when resolving a merge-master key. |
| `merge_get_part(restriction)` | The specific part-table query (one of `PositionOutput.TrodesPosV1`, `.DLCPosV1`, etc.) | You need part-specific attributes for downstream code — fetching part-table secondary columns, joining against the part directly, or running `fetch1_dataframe()` on a source-specific result. |

**For discovering a `merge_id` from upstream keys, both work** — `.fetch1('KEY')` on either returns the merge-master primary key (just `merge_id`). Pick the one whose return type matches what you do next.

**Failure modes differ:**

- `merge_restrict` on an over-broad restriction returns many rows (no raise); always check `len(...)` before `.fetch1(...)`. On a zero-match restriction it returns an empty query (no raise).
- `merge_get_part` on a restriction that matches entries in multiple parts raises `ValueError: Found multiple potential parts: [...]` unless `multi_source=True`.
- `merge_get_part` on a restriction that matches zero parts raises `ValueError: Found 0 potential parts: []` — usually because the upstream was populated but never inserted into the merge (see the misleading-error note below and common_mistakes.md for the explicit insert fix). This raise does NOT fire for `merge_restrict`.

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

## Merge-table methods — lifecycle (parts, deletion, population)

Methods that introspect part-table structure, delete rows, or populate from sources. Same `_Merge` inheritance — available on all five merge masters.

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

## Per-master method availability

The methods above all live on the `_Merge` base — they exist on every merge master. A few helpers look similar but are defined on a **single master** and don't exist on the others. Calling them on the wrong master raises `AttributeError`.

| Method | Defined on | NOT available on | Replacement for the other masters |
|--------|-----------|------------------|-----------------------------------|
| `get_restricted_merge_ids(key, sources=..., restrict_by_artifact=..., as_dict=...)` | `SpikeSortingOutput` only (`src/spyglass/spikesorting/spikesorting_merge.py:111`) | `PositionOutput`, `LFPOutput`, `DecodingOutput`, `LinearizedPositionOutput` | Use `merge_restrict({"nwb_file_name": f, ...}).fetch("merge_id")` or `merge_get_part(key).fetch("merge_id")` |
| `fetch_results(key)` | `DecodingOutput` only (`src/spyglass/decoding/decoding_merge.py:74`) | `PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `LinearizedPositionOutput` | Use `merge_get_part(key).fetch1_dataframe()` or `(Master & merge_key).fetch1_dataframe()` |

The base-`_Merge` methods (`merge_view`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_fetch`, `merge_populate`, `merge_delete`, `merge_delete_parent`, `extract_merge_id`, `get_source_from_key`) are the portable way to work across all five masters — reach for a per-master helper only when you are on that specific master and want its convenience shape.

**Why the convenience helpers exist.** `SpikeSortingOutput.get_restricted_merge_ids` wraps the common "resolve session + sort-group + artifact filter → merge_ids" flow that is specific to sorted data. `DecodingOutput.fetch_results` wraps the decoding-specific "load the xarray result set for one decode" flow (the V1 tables `ClusterlessDecodingV1` and `SortedSpikesDecodingV1` also define their own `fetch_results` — those are downstream computed tables, not merge masters). Neither pattern generalizes to the other four masters, which is why the helper isn't on the base.

**`fetch_results` has a merge-aware cardinality check — but the diagnostic is not bare `&`.** `DecodingOutput.fetch_results(key)` delegates through `cls().merge_restrict_class(key).fetch_results()` (`src/spyglass/decoding/decoding_merge.py:74-76`). `merge_restrict_class` (`src/spyglass/utils/dj_merge_tables.py:770-789`) does `parent.fetch("KEY", as_dict=True)` and raises `ValueError: Ambiguous entry. Data has mult rows in parent` when the key resolves to more than one parent row (not the `fetch1()` "expected one tuple" error). **Don't** precheck with `len(DecodingOutput & key) == 1` — that's subject to the silent-no-op footgun above because the master only has `merge_id` in its heading. Use `len(DecodingOutput.merge_get_part(key))` or `len(DecodingOutput.merge_restrict(key))` to check cardinality first. See [common_mistakes.md](common_mistakes.md) Common Mistake #2 for the general too-loose-restriction pattern.

## Projected FK rename pattern

When a Computed table needs two foreign keys that would collide on a shared primary-key slot, Spyglass uses `.proj(new_name='old_name')` in the table definition to rename one of them. At insert/populate time, pass the *renamed* field — not the original.

Examples in the wild:

- `RippleTimesV1` (ripple.py:186): `-> PositionOutput.proj(pos_merge_id='merge_id')`. Build populate key with `pos_merge_id`, not `merge_id`, because `RippleTimesV1`'s own primary FK into `RippleLFPSelection` already uses a `merge_id` slot via `LFPBandV1`.
- `MuaEventsV1` (mua.py:67–68): *two* renames at once — `PositionOutput.proj(pos_merge_id='merge_id')` and `IntervalList.proj(detection_interval='interval_list_name')`. Populate keys must use both renamed fields.

The pattern is widespread — at least a dozen tables use it, including `LFPBandV1`, `DecodingClusters`, `PoseGroup.Pose`, `SortedSpikesUnit`, and selection tables in `position/v1/` and `spikesorting/`. Grep `.proj(` inside `definition = """` blocks to find them in your own pipeline.

**How to detect it.** Read the target table's `definition`. If you see `.proj(foo='bar')` inside an FK line, `foo` is what your populate key needs, not `bar`. `Table.heading.primary_key` also lists the renamed names, not the originals.
