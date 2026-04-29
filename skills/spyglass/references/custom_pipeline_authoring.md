# Custom Pipeline Authoring

## Contents

- [Overview](#overview)
- [Schema Naming and Your Write Surface](#schema-naming-and-your-write-surface)
- [Adding a column to a core Spyglass table](#adding-a-column-to-a-core-spyglass-table)
- [Five-Step Decision Tree](#five-step-decision-tree)
- [Non-Negotiables](#non-negotiables)
- [Single Custom Table (Not a Pipeline)](#single-custom-table-not-a-pipeline)
- [Canonical Schema Skeleton](#canonical-schema-skeleton)
- [Extending an Existing Pipeline](#extending-an-existing-pipeline)
- [Building from Ingested Tables](#building-from-ingested-tables)
- [AnalysisNwbfile Storage Pattern](#analysisnwbfile-storage-pattern)
- [Merge Table Guardrail](#merge-table-guardrail)
- [Permissions and Roles](#permissions-and-roles)
- [Further Reading in Spyglass docs](#further-reading-in-spyglass-docs)

## Overview

This reference is for **authoring** a new pipeline that plugs into Spyglass — not for *using* existing pipelines. For calling methods on tables that already exist (`fetch_nwb`, `cautious_delete`, `merge_get_part`, etc.), see [spyglassmixin_methods.md](spyglassmixin_methods.md); this file is for authoring new schema modules. Typical authoring cases:

- You want to run a new analysis downstream of an existing merge table (`PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`).
- You want to run a new analysis on raw/ingested data directly (`Session`, `Raw`, `IntervalList`, `RawPosition`, `Electrode`).

Both cases follow the same DataJoint tier convention: **parameters → selection → computed**, with outputs stored in an `AnalysisNwbfile`. A merge table is only warranted when multiple interchangeable versions of the same analysis need a unified downstream interface.

Authoritative source for these patterns is `docs/src/ForDevelopers/` in the spyglass repo — links at the bottom of this file.

## Schema Naming and Your Write Surface

Before writing any schema file, know where your user is allowed to write — this rule is enforced by MySQL permissions (`spyglass/utils/database_settings.py`), not just convention. Each user has write access **only** on schemas whose names start with `<database_user>_`. Naming your schema anything else either fails with a MySQL permission error at `dj.schema()` call time or silently targets a lab-shared schema your role happens to allow. Both failure modes are confusing.

**The rule.** Your personal schema must be `<database_user>_<suffix>`, where `<database_user>` matches `dj.config["database.user"]`. Other namespaces:

- **Lab-shared** (reserved names, `SHARED_MODULES` in `database_settings.py`): `behavior`, `common`, `decoding`, `figurl`, `lfp`, `linearization`, `mua`, `position`, `ripple`, `sharing`, `spikesorting`. Writes to these require `dj_user` or `dj_admin` and are coordinated across the lab — never pick one of these as a prefix for personal work.
- **Other users' prefixes**: off-limits unless you have `dj_admin`.

> **Common hallucination to avoid.** Do NOT prefix personal schemas with `spyglass_` (as in `spyglass_<user>_<topic>`). User `edeno`'s personal theta/gamma analysis belongs in `edeno_theta_gamma`, not `spyglass_edeno_theta_gamma` — the latter raises a MySQL permission error at `dj.schema(...)` call time because `spyglass_` ≠ `database.user`. There is no implicit "framework namespace" for `spyglass_*`; lab-shared names are the explicit `SHARED_MODULES` listed above.

**Roles your account might hold** (set by whoever admin'd your DB account):

| Role | Select any schema | Write own prefix | Write shared modules |
| --- | --- | --- | --- |
| `dj_guest` | ✓ | — | — |
| `dj_collab` | ✓ | ✓ | — |
| `dj_user` | ✓ | ✓ | ✓ |
| `dj_admin` | ✓ | ✓ | ✓ (including other users') |

`dj_collab` is the common default for new lab members — you own your prefix and can read everything, but can't extend lab-shared schemas. This rule applies equally to custom pipelines and to single custom tables.

## Adding a column to a core Spyglass table

If the user asks to add a column to a Spyglass core table (`Session`, `Electrode`, `IntervalList`, `Raw`, `LFPV1`, `SpikeSorting`, anything in `spyglass.common` or a maintained pipeline), **do not edit the core schema**. The right pattern is a companion table in your user/lab schema that FKs to the core table:

- `dj.Computed` — derived values that come from a deterministic function of upstream rows (write a `make()` body, populate after the upstream populates).
- `dj.Manual` — human annotations, free-form metadata, lab-specific labels (insert by hand or by a small loader script).
- `dj.Lookup` — controlled vocabularies, code-defined enums (`contents` baked into the class).

Each FKs to the core table on its primary key, so your new field is queryable as a join (`CoreTable * MyCompanion`) wherever it would have appeared as a "real" column. Reasons to keep this discipline: (1) core schema changes require an upstream PR + per-release `Table.alter()` migration documented in CHANGELOG.md ([datajoint_api.md → Field Ownership](datajoint_api.md#field-ownership) explains why; ALTER privilege is admin-only on shared DBs), so this is not a routine user workflow; (2) a companion table is reversible — you can drop your schema without touching the canonical pipeline; (3) downstream Spyglass consumers won't break because the canonical heading is unchanged. Push back if the user insists on editing core: route them to opening an issue / PR upstream rather than locally patching their checkout.

## Five-Step Decision Tree

For each new step in your analysis, pick the smallest option that fits:

1. **Use an existing upstream table directly** — if your analysis is a one-off and doesn't need to be re-run with different parameters, you may not need any new tables at all. Just query.
2. **Add a preprocessing / grouping table** (`dj.Manual`) — when you need to combine units, intervals, or electrodes from the raw tables into analysis-ready sets (e.g., "units from these tetrodes during this epoch").
3. **Add a Parameters table** (`dj.Lookup` with `contents`) — any tunable value the analysis reads. Name ends in `Parameters` or `Params`.
4. **Add a Selection table** (`dj.Manual`) — pairs a specific input (upstream key) with a specific parameter set. Name ends in `Selection`. This is the row you `insert1` before calling `populate`.
5. **Add a Computed table** (`dj.Computed`) with a `make()` method — takes the Selection row, runs the analysis, writes output (typically to an AnalysisNwbfile) and inserts the row. Part tables hang off this for row-wise results.

**Add a merge table only if** you end up with multiple interchangeable implementations of the same analysis (e.g., `FooV1`, `FooV2`, `FooImported`) and downstream consumers want a single `merge_id` interface. Do not introduce a merge table for a single-source pipeline — it adds complexity without benefit.

**Pick the narrowest populated upstream that already represents the scientific object you consume.** When the FK choice is between a broad merge/output table and a specific computed endpoint Spyglass already populates, FK to the specific endpoint, not the merge — and do not re-derive that object inside your own `make()`. Concrete: for an analysis that runs on band-filtered LFP, FK to `LFPBandV1` / `LFPBandSelection`, not `LFPOutput` (which exposes wideband LFP and would force you to re-filter inside `make()`). For sorted spikes used downstream, FK to `SortedSpikesGroup` rather than reaching back through `SpikeSortingOutput`. The principle: prefer the upstream whose populated rows are *already* the object you consume; FK'ing one level too broad invites silent recomputation drift between your pipeline and the canonical Spyglass one.

## Non-Negotiables

These are the rules most likely to cause mysterious failures if ignored. Behavior in DataJoint splits across two layers — *structural* (declared in `Table.definition` strings: FK shapes, projections, secondary attributes) and *runtime* (executed in `make()` or other methods). When debugging or describing a pipeline, attribute behavior to the layer where it's declared, not the layer where it surfaces. See [feedback_loops.md § Verify behavior, trust identity](feedback_loops.md#verify-behavior-trust-identity) for the full pattern with worked examples.

1. **`SpyglassMixin` must be first in inheritance order**, before `dj.Manual`/`Lookup`/`Computed`/`Imported`/`Part`. From `docs/src/ForDevelopers/Classes.md`: "SpyglassMixin must be the first class inherited to ensure method overrides work correctly." Part tables use `SpyglassMixinPart` instead.
2. **Choose the right tier**. `dj.Lookup` for params (contents baked into the class), `dj.Manual` for selection/grouping tables the user populates, `dj.Computed` with `make()` for analysis outputs, `dj.Imported` for tables populated by walking an NWB file. See the tier list in `TableTypes.md`.
3. **Keep Parameters, Selection, and Computed tables separate.** Combining them (e.g., putting a `params` blob directly on a Computed table) breaks reproducibility and makes re-runs with different params impossible without deleting rows.
4. **Write analysis outputs to `AnalysisNwbfile`** when the result is sizeable (arrays, waveforms, posteriors). Keep only small metadata in DataJoint columns. Tables should reference exactly one AnalysisNwbfile table — Spyglass validates this on declaration.
5. **Only introduce a merge table for genuinely multi-source outputs.** If you only have one implementation, skip the merge table and let downstream tables FK-ref your Computed table directly.
6. **Never use `skip_duplicates=True` when your `make()` inserts into `IntervalList`.** Spyglass's built-in pipelines protect against orphaned-interval drift by nuking orphans on every delete — but custom `make()`s that call `IntervalList.insert1(..., skip_duplicates=True)` bypass that protection. Scenario: you delete the downstream entry, leave the interval row in place, re-run `make()` — the new computation silently attaches to the OLD interval row. Silent wrong data. If your pipeline needs a new `IntervalList` row, either insert without `skip_duplicates` (let it raise) or delete the old interval first. See `docs/src/ForDevelopers/Management.md`.

## Single Custom Table (Not a Pipeline)

You may not need a pipeline. If you want one standalone table — an annotation log, a notes table, an auxiliary grouping / lookup — the minimal shape is:

```python
import datajoint as dj

from spyglass.common import Session
from spyglass.utils import SpyglassMixin

schema = dj.schema("edeno_annotations")  # <database_user>_<suffix>, per above

@schema
class SessionAnnotations(SpyglassMixin, dj.Manual):
    """Per-session free-text notes keyed by author and timestamp."""

    definition = """
    -> Session
    author: varchar(32)
    annotation_time: datetime
    ---
    note: varchar(2000)
    """
```

Same non-negotiables as for pipelines (SpyglassMixin first in MRO, correct DataJoint tier, outputs to `AnalysisNwbfile` if the rows hold sizeable arrays). Just no Params / Selection / Computed scaffolding — one `dj.Manual` or `dj.Lookup` is enough.

If later the analysis needs re-runnability with different params, upgrade to the full pipeline shape using the decision tree above. Don't retrofit params into a Manual table by adding a `params: blob` column — that breaks reproducibility (Non-Negotiable #3) and makes parameter sweeps impossible without deleting rows.

## Canonical Schema Skeleton

Minimal authoring template that follows every non-negotiable. The
schema declarations are runnable as-is; the `make()` body uses two
placeholder names (`result_array`, `part_rows`) that you fill in
with your actual computation and per-unit dicts. Structure derived
from the canonical example in `docs/src/ForDevelopers/Schema.md`
lines 43–201; part-table syntax uses `SpyglassMixinPart` as
documented in `docs/src/ForDevelopers/Classes.md` line 206.

```python
import datajoint as dj

from spyglass.common import IntervalList, Session  # noqa: F401
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.utils import SpyglassMixin, SpyglassMixinPart

schema = dj.schema("my_username_myanalysis")

@schema
class MyAnalysisParams(SpyglassMixin, dj.Lookup):
    """Parameters for MyAnalysis. Lookup tier: contents baked in."""

    definition = """
    myanalysis_params_name: varchar(32)
    ---
    myanalysis_params: blob
    """
    contents = [
        ["default", {"window_s": 0.5, "threshold": 3.0}],
    ]

@schema
class MyAnalysisSelection(SpyglassMixin, dj.Manual):
    """One row per (session interval, params) pair to analyze."""

    definition = """
    -> Session
    -> IntervalList
    -> MyAnalysisParams
    """

@schema
class MyAnalysis(SpyglassMixin, dj.Computed):
    """Computed analysis; output stored in an AnalysisNwbfile."""

    definition = """
    -> MyAnalysisSelection
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    class Unit(SpyglassMixinPart):
        definition = """
        -> master
        unit_id: int
        ---
        value: float
        """

    def make(self, key):
        params = (MyAnalysisParams & key).fetch1("myanalysis_params")
        nwb_file_name = (Session & key).fetch1("nwb_file_name")

        # Replace these two placeholders with your actual computation:
        #   result_array — the pandas/numpy/xarray object you want
        #     stored as one NWB scratch table on the analysis NWB.
        #   part_rows    — list of {**key, "unit_id": ..., "value": ...}
        #     dicts, one per Unit row.
        result_array = ...   # e.g. compute_my_metric(spike_times, params)
        part_rows = [...]    # one dict per unit you analyzed

        # Builder context manages CREATE -> POPULATE -> REGISTER for you.
        # Do NOT mix builder with separate create()/add()/add_nwb_object()
        # calls — that path raises "Cannot call add_nwb_object() in state:
        # REGISTERED" (see AnalysisTables.md troubleshooting).
        with AnalysisNwbfile().build(nwb_file_name) as builder:
            result_object_id = builder.add_nwb_object(
                result_array, table_name="result"
            )
            analysis_file_name = builder.analysis_file_name

        # Master insert must come BEFORE the part insert — DataJoint's
        # FK from the part to its master rejects part rows otherwise.
        # The master row carries the fields declared above the `---`
        # divider on this Computed table (analysis_file_name +
        # result_object_id), not the bare `key`.
        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "result_object_id": result_object_id,
        })
        self.Unit().insert(part_rows, skip_duplicates=True)
```

## Extending an Existing Pipeline

When your analysis consumes output from an existing merge table, FK-ref the merge table as an upstream key.

```python
from spyglass.position import PositionOutput

@schema
class PosDerivedAnalysis(SpyglassMixin, dj.Computed):
    definition = """
    -> PositionOutput
    -> MyAnalysisParams
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    def make(self, key):
        # Option A: require a specific upstream source (safer).
        parent = PositionOutput().merge_get_parent(key)
        if parent.camel_name != "TrodesPosV1":
            raise ValueError("PosDerivedAnalysis requires TrodesPosV1")
        position_df = (PositionOutput & key).fetch1_dataframe()
        # ... compute ...

        # Option B: accept multiple sources, but check each one's
        # accessor surface. `PositionOutput.fetch1_dataframe()`
        # delegates to the resolved part class
        # (`position/position_merge.py:81`). Trodes / DLC parts
        # implement it (returning `position_x`/`_y` + speed/orientation);
        # `ImportedPose` does NOT — it exposes `fetch_pose_dataframe()`
        # instead (`position/v1/imported_pose.py:110`). The same is true
        # of `fetch_video_path()`. FK-ref'ing the merge master is
        # general; per-source method availability is not. Either gate
        # via merge_get_parent.camel_name (as in Option A), or branch
        # on the parent class and call the appropriate accessor.
```

Same pattern applies to `LFPOutput`, `SpikeSortingOutput`, `DecodingOutput`, `LinearizedPositionOutput`.

## Building from Ingested Tables

When your analysis consumes raw/ingested data directly, FK-ref the relevant common table(s). A grouping table is often the first step.

```python
# `ElectrodeGroup` is the per-probe-shank grouping row from
# common_ephys (`common_ephys.py:30`); `Electrode` is the
# individual electrode (`common_ephys.py:73`). Pick the one your
# analysis groups: this example bundles whole electrode groups
# (probes / shanks). To bundle individual electrodes instead, FK
# `Electrode` and rename the part class accordingly.
from spyglass.common import Session, IntervalList, ElectrodeGroup

@schema
class MyElectrodeGroupSet(SpyglassMixin, dj.Manual):
    """A named set of probe-shank electrode groups to analyze together."""

    definition = """
    my_group_name: varchar(32)
    -> Session
    """

    class ElectrodeGroupMember(SpyglassMixinPart):
        """One row per `ElectrodeGroup` included in the set."""

        definition = """
        -> master
        -> ElectrodeGroup
        """

@schema
class MyRawAnalysis(SpyglassMixin, dj.Computed):
    definition = """
    -> MyElectrodeGroupSet
    -> IntervalList
    -> MyAnalysisParams
    ---
    -> AnalysisNwbfile
    result_object_id: varchar(40)
    """

    def make(self, key):
        # fetch raw data restricted to the group's electrodes + interval
        ...
```

Common upstream tables for authoring: `Session`, `IntervalList`, `Raw`, `RawPosition`, `Electrode`, `ElectrodeGroup`, `LabMember`, `DIOEvents`.

## AnalysisNwbfile Storage Pattern

Heavy results — arrays, correlation/connectivity matrices, embeddings, decoded posteriors, time series, anything that would fit a `longblob` only by being squeezed in — go into an `AnalysisNwbfile`, not a `longblob` column. The DataJoint row stores `analysis_file_name` plus the per-object IDs needed to retrieve them. The non-negotiable here is **reproducibility, exportability, and shareability**, not just write/read performance: the DANDI / Kachery / paper-snapshot export workflows, the cleanup tooling (`AnalysisNwbfile.cleanup`), and the provenance tracking that lets a future reader regenerate or audit a result *all* assume heavy outputs live in addressable analysis files. A `longblob` is invisible to those tools — it round-trips through the DB but can't be exported with the rest of the analysis bundle, can't be re-shared standalone, and won't appear in DANDI uploads.

**Use the `build()` context manager** for all analysis-file writes. It handles the CREATE → POPULATE → REGISTER lifecycle atomically and prevents the common "Cannot call add_nwb_object() in state: REGISTERED" error that arises when separate `create()`, `add_nwb_object()`, `add()` calls are interleaved.

```python
from spyglass.common.common_nwbfile import AnalysisNwbfile

# Inside a Computed table's make(key):
nwb_file_name = (Session & key).fetch1("nwb_file_name")

# table_name is the NAME the object gets in the NWB scratch space
# (the retrieval key), not a description. DataFrames and numpy arrays
# are auto-wrapped into DynamicTable / ScratchData respectively.
# ALWAYS pass table_name explicitly — default is "pandas_table", so
# multiple add_nwb_object() calls without distinct names collide in
# scratch space and later retrieval fails.
with AnalysisNwbfile().build(nwb_file_name) as builder:
    obj_id = builder.add_nwb_object(my_numpy_array, table_name="result")
    analysis_file_name = builder.analysis_file_name
# File is auto-registered on context exit. Builder methods cannot be
# called after exit — the state machine blocks it.

self.insert1({**key, "analysis_file_name": analysis_file_name,
              "result_object_id": obj_id})
```

**Anti-pattern (do not do this):**

```python
# ❌ Raises "Cannot call add_nwb_object() in state: REGISTERED"
analysis_file_name = AnalysisNwbfile().create(nwb_file_name)
AnalysisNwbfile().add(nwb_file_name, analysis_file_name)  # registers
AnalysisNwbfile().add_nwb_object(...)                      # fails
```

**Constraint**: a table may reference only one AnalysisNwbfile table (either `common.common_nwbfile.AnalysisNwbfile` or a custom per-user one, not both). Spyglass validates this on declaration.

**Discovering what already exists**: import `AnalysisRegistry` from `spyglass.common` (re-exported from `spyglass.common.common_nwbfile`) and use the `all_classes` property — `AnalysisRegistry().all_classes` (`common_nwbfile.py:431`) returns every registered `AnalysisNwbfile` subclass across schemas as a `list[SpyglassAnalysis]`. For one specific team, `AnalysisRegistry().get_class("myteam")` (`common_nwbfile.py:396`) returns just that subclass. Use these when auditing what other teams have already authored before adding your own, or when building cross-pipeline tools that need to iterate all analysis-file tables. (The `AnalysisRegistry` class docstring lists a `get_all_classes()` method — that's stale; the actual surface is the `all_classes` property.)

## Merge Table Guardrail

Skip this unless you have **multiple interchangeable implementations** of the same analysis that downstream consumers need to treat uniformly. Signals it's warranted:

- Two independently-written versions (`MyAnalysisV1`, `MyAnalysisV2`) exist and both should remain usable.
- You want users to be able to import the same source analysis from outside Spyglass (`MyAnalysisImported`) alongside the computed one.
- A downstream table needs a single `merge_id` FK regardless of which implementation produced the row.

If none of these apply, let downstream tables FK-ref your Computed table directly. Adding a merge table for a single-source pipeline adds complexity (UUID indirection, `merge_get_part` calls) with no benefit.

When you do add one, follow the conventions in `TableTypes.md`: name it `{Pipeline}Output`, use tier `_Merge`, primary key `merge_id: uuid`, non-primary key `source: varchar`.

## Permissions and Roles

When authoring a pipeline that other lab members will run, the table tier and `make()` body assume the runner has SELECT on every upstream schema and INSERT/ALTER on the schema your tables live in. Verify those grants before debugging "missing data" — half of `populate()` no-ops trace to a permission gap, not a logic bug.

### Testing for user permissions and roles

Two layers of check, used for different decisions:

**DataJoint-level — what the SQL connection can actually do.** Ask MySQL directly:

```python
import datajoint as dj
conn = dj.conn()
grants = conn.query("SHOW GRANTS FOR CURRENT_USER()").fetchall()
for row in grants:
    print(row[0])
```

Look for `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `ALTER` on the schema names you care about. A user without `ALTER` cannot run `dj.schema(...).drop()` or `Table.alter()`, regardless of admin status in `LabMember`. A user without `DELETE` on a downstream schema gets the IntegrityError-1217 / NoneType-groupdict failure mode documented in [destructive_operations.md](destructive_operations.md#when-delete-raises-integrityerror-1217-or-nonetype-object-has-no-attribute-groupdict).

**Spyglass-level — whether the user is a recognized lab member with team membership.** This is what `cautious_delete` checks before allowing a delete (`src/spyglass/utils/mixins/cautious_delete.py:195`). Replicate the same lookup yourself when an authoring decision depends on it (e.g., a `make()` that branches on whether the runner is the data owner). The `datajoint_user_name` lives on the part table `LabMember.LabMemberInfo`, not on `LabMember` itself — restricting `LabMember & {"datajoint_user_name": ...}` would silently match every row (the `_Merge`-style silent footgun, but on a regular table). Restrict the part:

```python
from spyglass.common.common_lab import LabMember, LabTeam

dj_user = dj.config["database.user"]
member_info = (LabMember.LabMemberInfo & {"datajoint_user_name": dj_user}).fetch1()
print(member_info)  # raises DataJointError if no row — user is unknown to Spyglass

# Teams the user is on
member_name = member_info["lab_member_name"]
my_teams = (LabTeam.LabTeamMember & {"lab_member_name": member_name}).fetch("team_name")
print(list(my_teams))
```

A user with no `LabMember.LabMemberInfo` row hits `cautious_delete` errors of the form `Could not find name for datajoint user <name> in LabMember.LabMemberInfo`. The fix is to insert the row, not to bypass the check — see [setup_troubleshooting.md](setup_troubleshooting.md) "AccessError / PermissionError".

**When to use which.** SQL grants when the question is "can this connection structurally do X" (ALTER, DROP, cross-schema DELETE). `LabMember` / `LabTeam` when the question is "should Spyglass let this user do X to *this* session's data" (cautious_delete behavior, ownership-aware logic in custom `make()` bodies).

## Further Reading in Spyglass docs

All authoritative; this reference summarizes them for skill-time lookup:

- `docs/src/ForDevelopers/CustomPipelines.md` — full worked example, FK-ref syntax gotchas, `make()` conventions.
- `docs/src/ForDevelopers/TableTypes.md` — tier choice cheat-sheet, naming conventions for each role.
- `docs/src/ForDevelopers/Schema.md` — canonical schema file skeleton, import ordering, definition-string grammar.
- `docs/src/ForDevelopers/Classes.md` — SpyglassMixin rules, AnalysisMixin methods, part-table inheritance.
- `docs/src/ForDevelopers/Reuse.md` — formatting (black/isort/ruff), NumPy docstring style, pre-commit hooks.
