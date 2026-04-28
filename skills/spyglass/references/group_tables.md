# Group Tables

Group tables aggregate many upstream rows under one user-named key, so downstream pipelines can foreign-key the *group* instead of the underlying rows. Different shape from merge tables; different problem solved. This file is the landing target when a question references a `*Group` table or talks about "grouping units / electrodes / position streams together for one downstream analysis."

## Contents

- [What is a group table?](#what-is-a-group-table)
- [Why they exist](#why-they-exist)
- [Concrete examples in Spyglass](#concrete-examples-in-spyglass)
- [Group vs. merge — quick comparison](#group-vs-merge--quick-comparison)
- [Worked example](#worked-example)
- [Cross-references](#cross-references)

## What is a group table?

A group table is a `dj.Manual` (occasionally `dj.Lookup`) whose primary key is a user-supplied name plus the session it belongs to, paired with a `dj.Part` table whose rows reference the upstream entities being grouped. The shape:

```
class FooGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    foo_group_name: varchar(80)
    """

    class Member(SpyglassMixinPart):
        definition = """
        -> master
        -> SomeUpstreamTable
        """
```

Downstream tables foreign-key `FooGroup` (the master), pulling in the part rows transparently when they `*` join. The user picks the group name; the framework manages the cardinality.

## Why they exist

Many analyses operate on a *set* of upstream rows that are conceptually one input but live in many DataJoint rows. Concrete cases:

- A decoding run consumes spike times from a chosen subset of sorted units across multiple sort groups. Without grouping, the decoding selection table would need a multi-row primary key with one row per unit — every fetch would have to re-aggregate.
- The same decoding run uses one or more position streams (head, body, nose). Each is a separate row in `PositionOutput`; the analysis treats them as one position vector.

A group table assigns the user's chosen subset a single name. Downstream selection rows then carry one foreign key (the group name) instead of N (one per upstream row), which keeps the dependency graph readable and the `populate()` call cardinality sane.

## Concrete examples in Spyglass

| Group table | Part table | Upstream entities grouped | Downstream consumers |
|-------------|------------|---------------------------|----------------------|
| `SortedSpikesGroup` (`spyglass/spikesorting/analysis/v1/group.py`) | `SortedSpikesGroup.Units` | merge keys from `SpikeSortingOutput` (one row per sorted unit set) | `SortedSpikesDecodingSelection`, `MuaEventsV1` (FKs `SortedSpikesGroup` directly at `mua/v1/mua.py:66`; no `MuaEventsV1.Selection` part exists) |
| `PositionGroup` (`spyglass/decoding/v1/core.py`) | `PositionGroup.Position` | merge keys from `PositionOutput` (one row per position stream) | `SortedSpikesDecodingSelection`, `ClusterlessDecodingSelection` |
| `UnitSelectionParams` (`spyglass/spikesorting/analysis/v1/group.py`) | — | label-filter parameters (e.g. `all_units`, `exclude_noise`) referenced from `SortedSpikesGroup`'s primary key | `SortedSpikesGroup` |

`UnitSelectionParams` is a parameter table referenced *from* `SortedSpikesGroup`'s PK rather than a group itself; it's listed here because it's part of the same end-to-end "group some units for decoding" flow — picking a label filter is one of the inputs the group is built from.

## Group vs. merge — quick comparison

Same suffix conventions live nearby (`*Group` vs. `*Output`), and both involve a master + part shape, but the problem they solve is different.

| | Merge table | Group table |
|---|---|---|
| Rows aggregated | Different *versions* of one analysis (v0 vs v1, sorter A vs sorter B). One row per version per upstream input. | Multiple upstream entities grouped into one named set. One row per member. |
| PK shape on master | `merge_id` only | Per-table; user-supplied. `SortedSpikesGroup` keys on `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)` (`spikesorting/analysis/v1/group.py:63-67` — note the `-> UnitSelectionParams` FK in the PK). `PositionGroup` keys on `(nwb_file_name, position_group_name)` only (`decoding/v1/core.py:130`). Downstream-FK or `create_group(...)` callers must supply the right tuple — `unit_filter_params_name` is required for SortedSpikesGroup and is a common omission. |
| Downstream FK target | The master's `merge_id` (opaque UUID) | The group name (semantic, user-readable) |
| Helper methods | `merge_get_part`, `merge_restrict`, `merge_get_parent`, `merge_delete` | `create_group()` instance method on the master |
| Common landmines | Classmethod-discard on restricted relations, silent-no-op on `& {nwb_file_name: ...}` (see [merge_methods.md](merge_methods.md)) | Re-creating an existing group raises (or logs and returns) — must delete first; downstream-name reuse not enforced |

Use a merge when you have *interchangeable* implementations of one analysis. Use a group when you have *several distinct entities* that one downstream analysis needs as a unit.

## Worked example

Group three sorted-unit sets into one `SortedSpikesGroup`, then point a sorted-spikes decoding run at it.

```python
from spyglass.common import Session
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
from spyglass.spikesorting.analysis.v1.group import (
    SortedSpikesGroup,
    UnitSelectionParams,
)

# 1. Discover the merge keys for the unit sets you want to group.
#    `SortedSpikesGroup.Units` FKs `SpikeSortingOutput.proj(
#    spikesorting_merge_id='merge_id')` (`spikesorting/analysis/v1/group.py:73`),
#    so each `keys` entry must carry `spikesorting_merge_id`, NOT
#    `merge_id` — `create_group` splats the dict straight into the part
#    (`group.py:97-103`). Project the renamed column when fetching.
nwb_file = "j1620210710_.nwb"
candidate_units = (
    SpikeSortingOutput.merge_restrict({"nwb_file_name": nwb_file})
    .proj(spikesorting_merge_id="merge_id")
    .fetch("KEY", as_dict=True)
)
print(len(candidate_units), "candidate unit sets")

# 2. Pick a parameter row that tells the group how to filter labels.
#    UnitSelectionParams ships defaults like "all_units" and "exclude_noise".
filter_name = "exclude_noise"

# 3. Inspect before write — is the group name already taken?
group_name = "ca1_pyramidals_for_decoding"
existing = SortedSpikesGroup & {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}
print(len(existing), "existing rows for this group key")

# 4. Create the group. create_group() inserts the master row and all
#    part rows in one call; it raises if a row with the same
#    (nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)
#    triple already exists (`spikesorting/analysis/v1/group.py:84-95`).
#    The same group_name CAN coexist under a different
#    unit_filter_params_name — they're distinct rows by PK
#    (`spikesorting/analysis/v1/group.py:63`). HOWEVER:
#    `SortedSpikesGroup.fetch_spike_data` only restricts the Units
#    part by (`nwb_file_name`, `sorted_spikes_group_name`)
#    (`spikesorting/analysis/v1/group.py:171`) — it does NOT filter
#    by `unit_filter_params_name`. If two rows share a group_name
#    under different filter params, fetch_spike_data merges their
#    units silently. Keep `sorted_spikes_group_name` unique per
#    session unless you've verified the helper behavior matches
#    your intent.
SortedSpikesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name=group_name,
    unit_filter_params_name=filter_name,
    keys=candidate_units,
)

# 5. Downstream: a decoding selection FKs the group, not the units.
group_key = {
    "nwb_file_name": nwb_file,
    "sorted_spikes_group_name": group_name,
    "unit_filter_params_name": filter_name,
}
print((SortedSpikesGroup & group_key).fetch1())
print(len(SortedSpikesGroup.Units & group_key), "units in the group")
```

The decoding-selection insert then takes `group_key` as one foreign-key block; `SortedSpikesDecodingSelection` declares `-> SortedSpikesGroup` and the part rows come along automatically when the decoding `make()` calls `SortedSpikesGroup.fetch_spike_data(key, time)` to materialize spike times.

## Cross-references

- [merge_methods.md](merge_methods.md) — sister concept. Classmethod-discard is the merge-table footgun where a restricted relation is silently dropped because the method is a `@classmethod` that ignores `self`. Group-master methods need to be checked individually: `SortedSpikesGroup.fetch_spike_data(key, time)` is a `@classmethod`, but it takes `key` as an explicit argument and routes through `get_fully_defined_key(key)` (`spikesorting/analysis/v1/group.py:142, 168`), so the merge-style classmethod-discard footgun doesn't apply there. The general rule still holds: don't rely on relation restrictions reaching the method body unless the method is documented as instance- or restriction-aware.
- [common_tables.md](common_tables.md) — `Session`, the upstream FK every group masters references.
- [spyglassmixin_methods.md](spyglassmixin_methods.md) — `cautious_delete` semantics apply to groups; deleting a group cascades to its part rows.
- [decoding_pipeline.md](decoding_pipeline.md) — `SortedSpikesDecodingSelection` and `ClusterlessDecodingSelection` are the canonical downstream consumers.
- [mua_pipeline.md](mua_pipeline.md) — `MuaEventsV1` consumes `SortedSpikesGroup` directly (no `Selection` part).
