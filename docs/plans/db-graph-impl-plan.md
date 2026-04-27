# Implementation plan - `db_graph.py` (DB-resolved Spyglass inspection)

**Date drafted:** 2026-04-26
**Last revised:** 2026-04-27 (post-implementation planning cleanup)
**Status:** Implemented / PR-ready; retained as implementation record.
Current behavior lives in `skills/spyglass/scripts/db_graph.py`,
`skills/spyglass/tests/test_db_graph.py`, `skills/spyglass/scripts/README.md`,
and `skills/spyglass/references/feedback_loops.md`. This plan explains the
design rationale and should not be treated as the user-facing contract.
**Predecessor:** [db-graph-decision-record.md](db-graph-decision-record.md)
**Target PR:** separate PR after the source-only `code_graph.py` work on `master`

## Current implementation note

The shipped tool now includes the MVP plus follow-on runtime `describe` and
`path` surfaces, fake-backed tests, source/runtime comparison guidance, safe
serialization for blob-like values, non-finite restriction refusal, pagination
guards, and machine-readable `info --json`. Live Spyglass tests are optional
because they are slow and environment-dependent; the default gate remains the
fake-backed suite plus static validation.

## Summary

Build `skills/spyglass/scripts/db_graph.py` as a read-only, DB-resolved sibling to `code_graph.py`.

The source-only graph answers "what does the checked-out source declare?" The DB graph answers "what rows and runtime DataJoint tables exist in this configured session?" The decision record counted 16 hard-blocked evals, 13 of which are `find-instance` shaped. That makes `find-instance` the MVP. Runtime `describe` and `path` are useful, but they should not delay row/merge lookup.

The core discipline: this script inspects only. It never inserts, deletes, updates, populates, alters, or drops.

## Goals

- Ship `db_graph.py find-instance` for read-only row lookup, counts, merge-key resolution, simple intersections, antijoins, joins, and bounded aggregate counts.
- Emit LLM-friendly JSON with explicit provenance: `graph: "db"`, `authority: "runtime-db"`, DataJoint/Spyglass environment metadata, executed query summary, result shape, and limit/truncation markers.
- Fail loudly and structurally for the cases an LLM must not guess through: DB unavailable, class not importable, ambiguous class, unsafe request, empty result.
- Integrate routing into `feedback_loops.md` so agents choose `code_graph.py` for source declarations and `db_graph.py` for row/runtime questions.
- Add tests that run without a live Spyglass DB by default, plus optional integration tests behind an explicit flag.

## Non-goals

- No writes: no `insert`, `delete`, `drop`, `populate`, `update`, `.alter()`, or raw SQL execution.
- No arbitrary SQL or arbitrary Python expression evaluation.
- No full workflow runner. The tool returns evidence; it does not decide scientific equivalence or migrate data.
- No `find-method`. Method ownership remains a source/Python-inspection question, not a DB graph question.
- No attempt to share state with a notebook kernel. This is a separate process using the shell's DataJoint config.
- No general restriction-cascade engine in the MVP. Existing Spyglass `RestrGraph` / `TableChain` machinery is for broad graph traversal and restriction propagation; `find-instance` should be a fast direct-relation inspector.

## Efficiency strategy

The MVP must be optimized around the eval-driving question: "what rows exist for this table/restriction?" That is a narrower problem than "walk the full DataJoint dependency graph."

Rules:

- `find-instance` must not instantiate `RestrGraph` or `TableChain`. Resolve the class, instantiate the DataJoint table, validate fields from `heading`, apply direct relation operations, and fetch bounded evidence.
- `info --json` must not import DataJoint or Spyglass. It should stay available even when the user's DB environment is broken.
- Avoid importing every Spyglass module. Stock short-name resolution may use `_index.py`, then import only the resolved module.
- Treat DataJoint connection setup as a real cost. Keep one invocation capable of answering one compound question through joins/set operations instead of forcing an agent to make several subprocess calls.
- Prefer database-side relational operations over Python-side full-table materialization. If a fallback requires Python-side key comparison, it must fetch only bounded keys and report `truncated: true` / `incomplete: true` rather than pretending the set operation is complete.
- Keep row output bounded by `--limit`; default 100, hard max 1000. Counts may use `len(relation)`, but row evidence should never fetch an unbounded relation.
- Cache only within the process: class-resolution records, imported modules, table headings, and merge part/master metadata. Do not add cross-invocation cache files in v1.
- Emit `timings_ms` in JSON so slow calls can be diagnosed as import, connection, resolution, heading, query, or serialization cost.
- Defer `batch` / server mode until repeated-agent-call latency is measured. Do not pre-build a daemon without evidence that subprocess startup is the bottleneck.

This keeps `db_graph.py` complementary to the existing Spyglass graph utilities: fast row/runtime evidence by default; broad runtime graph traversal only in explicit follow-on subcommands.

## MVP scope

### Subcommand: `find-instance`

Initial CLI:

```bash
python skills/spyglass/scripts/db_graph.py find-instance \
  --class Session \
  --key nwb_file_name=example.nwb \
  --fields nwb_file_name,session_description \
  --json
```

Supported in MVP:

- `--class CLASS`: class short name, dotted module path, or `module:Class`.
- `--src PATH`: optional Spyglass source root override for stock short-name resolution. Default is the installed `spyglass` package's *parent* directory — i.e., `Path(spyglass.__file__).resolve().parent.parent`, which is the directory `_index.scan(src_root)` expects (it looks for `src_root / "spyglass"`, see [skills/spyglass/scripts/_index.py:884-886](../../skills/spyglass/scripts/_index.py#L884-L886) and the canonical pip form at [skills/spyglass/scripts/_index.py:500-502](../../skills/spyglass/scripts/_index.py#L500-L502)). Fall back to `$SPYGLASS_SRC` only when the package cannot be imported. Do not pass `Path(spyglass.__file__).parent` — that is the package root, one directory too deep, and `_index.scan` will exit `2`.
- `--import MODULE`: repeatable imports for custom/lab modules before class resolution.
- `--key FIELD=VALUE`: repeatable equality restrictions.
- `--fields f1,f2`: fetch selected fields. Default is `KEY`.
- `--count`: return count only.
- `--limit N`: default 100, hard max 1000 in MVP.
- `--merge-master MASTER --part PART`: resolve a merge master through the named part table using merge-aware semantics. Both flags are required together; supplying one without the other returns exit `2`.
- `--intersect CLASS`: rows present in both relations, restricted to shared primary-key fields.
- `--except CLASS`: rows present in the left relation and absent from the right relation, restricted to shared primary-key fields.
- `--join CLASS`: DataJoint join for explicit field fetches across related tables.
- `--group-by f1,f2 --count-distinct FIELD`: bounded grouped counts by explicit fields.
- `--group-by-table CLASS --count-distinct FIELD`: bounded grouped counts by the grouping table's primary key. MVP supports this single table-shaped aggregate because eval #19 needs per-session distinct electrode-group counts.

Deferred from MVP:

- arbitrary `--aggregate` expressions beyond `--count` and `--count-distinct`.
- multi-value key files.
- CSV output.
- automatic workflow-specific aliases like "trodes position for session".

### Output contract

Every JSON payload:

```json
{
  "schema_version": 1,
  "kind": "find-instance",
  "graph": "db",
  "authority": "runtime-db",
  "source_root": null,
  "db": {
    "host": "example",
    "user": "alice",
    "database": null,
    "spyglass_version": "0.5.x",
    "datajoint_version": "0.14.x"
  },
  "query": {
    "class": "Session",
    "resolved_class": "spyglass.common.common_session.Session",
    "restriction": {"nwb_file_name": "example.nwb"},
    "fields": ["KEY"],
    "mode": "rows"
  },
  "count": 1,
  "limit": 100,
  "truncated": false,
  "incomplete": false,
  "timings_ms": {
    "import": 25,
    "connect": 120,
    "resolve": 5,
    "heading": 8,
    "query": 40,
    "serialize": 2,
    "total": 200
  },
  "rows": []
}
```

Rules:

- Include stable top-level fields on every payload: `schema_version`, `kind`, `graph`, `authority`, `source_root`, `db`, `query`.
- `rows` is always a list when row-shaped output is requested.
- `count` is always present when the query reaches DataJoint.
- `truncated` is true when fetched rows hit `--limit`.
- `incomplete` is true when the result is known to be partial, for example a Python-side fallback set operation hit a bounded-key limit.
- `timings_ms` is always present on successful DB-reaching calls and may be present on structured failures. Use integer milliseconds and include at least `total`.
- Values that are not JSON-serializable are converted **per-field**, never by aborting the whole payload: UUID to string, NumPy scalar to Python scalar, bytes to `{"_unserializable": true, "type": "bytes", "length": N}`, ndarray to `{"_unserializable": true, "type": "ndarray", "shape": [...], "dtype": "..."}`, datetime to ISO-8601 string. The same envelope shape is used everywhere so the LLM has one pattern to recognize.
- `db.spyglass_version` is `getattr(spyglass, "__version__", None)`; fall back to `importlib.metadata.version("spyglass-neuro")` (the PyPI distribution name per `spyglass/pyproject.toml`); otherwise emit `null`. Do the same for `datajoint_version` (distribution `datajoint`). Never raise on version-lookup failure — the rest of the payload should still ship.
- `db.database` is the active default schema prefix (DataJoint configs `database.prefix` / `custom["database.prefix"]` when set), not a per-table schema name. When no prefix is configured, emit `null`. Document this in `info --json` so the LLM does not mis-cite it as the table-owning schema.
- Do not print raw passwords, connection URLs with credentials, or full tracebacks. Use `scrub_dj_config.py`'s scrubbing helpers (or a shared `_dj_scrub` module if one is factored out) to strip sensitive values before any payload includes config data.

### Exit codes

Use tool-local exit codes. "Class not found" and "0 rows from a valid query" are different conditions; collapsing both into `4` would force LLMs to guess. Split them:

- `0`: query succeeded. Empty rows count as success — `count: 0` is a valid scientific answer ("I checked; there are zero matching rows").
- `2`: usage error (argparse default; also missing required flag combos like `--merge-master` without `--part`).
- `3`: class resolution ambiguous; re-run with module path or `--import`.
- `4`: class/table not found in the resolved source/runtime. Distinct from "0 rows": this means the *thing the user named* could not be located at all.
- `5`: DB/session error: connection failure, authentication failure, schema unavailable, import-time DataJoint failure. Payload includes a structured `error.kind` (`"connection" | "auth" | "schema" | "datajoint_import"`) so the LLM does not need to grep prose.
- `6`: refused unsafe request (e.g., raw SQL passed via a future flag, attempt to call a write method).
- `7`: query succeeded but `--fail-on-empty` was set and `count == 0`. Opt-in only; the default is exit `0` with `count: 0`.

Rationale for the default-`0`-on-empty choice: agents reading exit codes can already distinguish "valid query, no rows" via `count: 0` in the payload. Forcing exit `4` for empty results conflates "I asked about something that doesn't exist" with "I asked about something that exists but has no rows" — the second is genuine evidence and the LLM should be able to cite it. `--fail-on-empty` is for callers (e.g., shell scripts) that genuinely want a non-zero exit on empty.

`code_graph.py` already uses exit `5` for strict heuristic refusal — a different meaning than `db_graph.py`'s connection/auth error. This divergence is intentional (each tool has a different failure surface) but **must** be flagged in both `db_graph.py info --json` and `feedback_loops.md` so an LLM that already knows `code_graph.py`'s codes doesn't carry over the wrong assumption.

### `info --json` contract

`db_graph.py info --json` is part of Batch A and must be static: it must not import DataJoint, Spyglass, or user-supplied modules. It exists so an LLM can discover the tool contract without parsing prose or needing a working database.

Payload fields:

- `schema_version`, `kind: "info"`, `graph: "db"`, `authority: "runtime-db"`, `source_root: null`.
- `subcommands`: each subcommand has `purpose`, `modes`, and `hints`. MVP entries: `find-instance`, `info`; planned entries: `describe`, `path`.
- `exit_codes`: the tool-local exit-code table above, including the `code_graph.py` exit-5 divergence.
- `payload_envelopes`: ordered top-level field lists for `find-instance`, `not_found`, `ambiguous`, `db_error`, `unsafe`, `info`, and merge / aggregate variants. Field-validation errors (exit `2`) and empty-success results (exit `0` with `count: 0`) reuse the `find-instance` envelope rather than introducing new shapes — only the values differ. State this explicitly so an implementer does not invent extra envelopes.
- `result_shapes`: enum-style names such as `rows`, `count`, `merge`, `grouped_count`, `error`.
- `comparison`: a small sibling-tool delta block, e.g. `{"sibling_tool": "code_graph.py", "differences": {"exit_code_5": "DB/session error here; heuristic refusal there", "authority": "runtime-db here; source-only there"}}`.
- `security_profile`: read-only, no raw SQL, imports named by `--import` execute normal Python import side effects, no config secrets printed.
- `null_policy`: `--key field=null` is refused in MVP because DataJoint dict restrictions do not mean SQL `IS NULL`.

## Class resolution

Resolution order:

1. If input contains `module:Class` or a full dotted module path, import that module and resolve directly.
2. Import optional `--import MODULE` values. This is the custom-table escape hatch.
3. For stock Spyglass short names, find the source root in this order:
   - `--src PATH` if supplied
   - installed-package parent directory: `import spyglass; Path(spyglass.__file__).resolve().parent.parent` (this is the directory containing the `spyglass/` package; `_index.scan` requires `src_root / "spyglass"` to exist — see [skills/spyglass/scripts/_index.py:884-886](../../skills/spyglass/scripts/_index.py#L884-L886))
   - `$SPYGLASS_SRC`
   Then use the existing source-index helpers rather than reimplementing lookup: `_index.resolve_src_root` (or the installed-package fallback above) to choose the root, `_index.scan(src_root) -> ClassIndex` to build the map (the actual factory exposed by `_index.py`; there is no `ClassIndex.from_root`), and `code_graph._resolve_class(...)` for dotted-qualname and same-name disambiguation. Derive the module path from the returned `ClassRecord`, import it, and retrieve the class.
4. If multiple source records share the same short name, return exit `3` with candidates and require a module/file hint.
5. If the class imports but is not a DataJoint table-like object, return exit `4` with a clear hint. Predicate (concrete form for the installed DataJoint surface):

   ```python
   import inspect
   from datajoint.user_tables import UserTable

   if not (inspect.isclass(cls) and issubclass(cls, UserTable)):
       # exit 4
   ```

   `UserTable` is the public superclass for `Manual`, `Lookup`, `Imported`, `Computed`, and `Part` in the currently installed DataJoint version, so `issubclass(cls, UserTable)` covers every Spyglass table without instantiation. Do not use `isinstance(cls(), dj.Table)` — instantiation may connect, defeating the no-DB constraint of class resolution. Keep a narrow fallback only if a future DataJoint version moves the import path; the validator should pin the import location so a rename is caught at test time rather than runtime.

This keeps stock Spyglass convenient in both editable-source and installed-package environments while forcing custom/lab tables to be explicit. It also avoids importing every Spyglass module up front.

Alignment choice: if feasible, backport the installed-package fallback into `_index.resolve_src_root` so `code_graph.py` and `db_graph.py` share one source-root behavior. If that is out of scope for the DB-graph PR, document the divergence in `info --json`, `feedback_loops.md`, and `scripts/README.md`; do not silently catch `_index.resolve_src_root`'s `SystemExit`.

## Query semantics

### Restriction parsing

`--key FIELD=VALUE` parses only literal scalar values:

- strings by default
- integers and floats when unambiguous
- booleans `true` / `false`
- JSON object values only behind `--key-json FIELD=JSON`

`null` / `None` is **not** accepted in MVP. DataJoint silently drops `{field: None}` from a restriction (it does not generate `field IS NULL`); supporting it correctly requires emitting a SQL string restriction, which expands the surface this MVP is trying to keep small. Document the workaround in `info --json` ("filter NULLs in a follow-up step") and revisit only if evals demand it.

`--key-json` is intended for fields whose stored representation is JSON-typed (e.g., DataJoint's `json` attribute type). It is not a hatch for blob/longblob fields, which DataJoint cannot restrict server-side; restricting on a blob attribute returns exit `2` with that explanation.

No Python `eval`. No raw DataJoint restriction strings in MVP.

### Field validation

Before fetch:

- Get `table.heading.names` and `table.primary_key` for every relation that participates in the query (base + each `--join` target + `--intersect` / `--except` operands).
- Validate every `--key` field exists on at least one participating relation. After validation, push each restriction to the narrowest unambiguous owner before building joins: fields unique to the base apply as `(L & key)`, fields unique to a join operand apply as `(R & key)`, and shared fields apply after the join only when ownership is genuinely ambiguous. Surface the chosen application point in the `query` payload (`restriction_applied_to: "base" | "join:<Class>" | "joined"`) so the LLM can see which relation owned the field.
- Validate every `--fields` field exists on the post-join relation.
- If a restriction field is not in a merge master heading but `--merge-master` is used, route through the part relation rather than applying a silent no-op restriction.
- If a restriction field is absent on every participating relation and no merge-aware mode is active, return exit `2` with a message explaining DataJoint's silent unknown-attribute footgun.

### Merge master mode

For:

```bash
db_graph.py find-instance --merge-master PositionOutput --part TrodesPosV1 --key nwb_file_name=X
```

Algorithm:

1. Resolve master and part classes.
2. Validate the user restriction against the part table first. If any key field is absent from the part heading, fail with exit `2`; do not try the master relation as a fallback.
3. Restrict the part relation by the user key.
4. Identify the part column(s) that reference the master via DataJoint's structural metadata, in this order:
   - resolve `part.master` (the live class attribute every DataJoint Part exposes); confirm it matches the user-supplied master class.
   - if `part.master` is unavailable or disagrees, inspect `part.heading.foreign_keys` (or `part.parents()` on older DataJoint) and pick the FK whose target is the resolved master class.
   - only as a last resort, fall back to PK-name overlap (`set(part.primary_key) & set(master.primary_key)`); never accept a single shared PK field unless that field name appears in the master's FK declaration on the part.
   - if neither structural source is unambiguous, fail with exit `3` and require a more explicit part/master pairing.

   Do not heuristically assume the linking field is named `merge_id`. The eval pressure is real merge masters whose link field happens to be `merge_id`, but the algorithm must work for any master/part pair the user names.
5. Fetch the part rows' master key values.
6. Restrict the master relation by those master key values.
7. Return both the master rows and the part rows' key evidence.

The direction is intentionally **part -> master**. APIs such as `merge_get_part()` are useful when starting from a master key, but the eval pressure here starts from a session/part restriction and needs the corresponding merge IDs. Implement the part-first relation logic as the core path; use upstream merge helpers only if they preserve that direction and return the same evidence.

Payload includes:

```json
"merge": {
  "master": "PositionOutput",
  "part": "TrodesPosV1",
  "restriction_applied_to": "part",
  "master_key_fields": ["merge_id"],
  "merge_ids": ["..."]
}
```

This directly closes the silent wrong-count shape where `(MergeMaster & {"nwb_file_name": f})` returns the whole master.

### Set operations

`--intersect`, `--except`, and `--join` stay conservative:

- Canonical operator mapping (DB-side, used unless explicitly forced into fallback):
  - `--intersect R`: `L & R.proj()` — DataJoint's natural restriction along shared attributes.
  - `--except R`: `L - R.proj()` — DataJoint's antijoin along shared attributes.
  - `--join R`: `L * R` — DataJoint's natural join.
- Shared-attribute requirement: `--intersect`, `--except`, and `--join` require at least one shared attribute name across `L.heading.names` and `R.heading.names`. If zero overlap, return exit `2` and list each side's headings; do not silently degenerate to a Cartesian product. A future explicit `--allow-cross-join` flag could be considered, but it is out of MVP.
- They return the shared key fields by default.
- They validate that the requested output fields exist after the operation.
- They cap output with `--limit`.
- They prefer DataJoint/database-side relational operations. If an operation falls back to Python-side key comparison, it must fetch only bounded keys (`--limit + 1` is the default fallback bound) and mark `incomplete: true` when the fallback fetch fills its bound. The fallback must record `fallback: "python_set_diff"` (or analogous) in the payload so the LLM can see why the result is bounded.
- They must not fetch all keys from a large relation just to compute a set difference. If completeness cannot be guaranteed under the limit, return bounded evidence plus an explicit warning, or require a narrower user restriction.

### Grouped counts

`--group-by f1,f2 --count-distinct FIELD` and `--group-by-table CLASS --count-distinct FIELD` are the only MVP aggregates. They exist to cover questions like "how many distinct tetrodes/electrode groups per session?" without opening a general SQL surface.

Rules:

- `--group-by` fields must exist on the current or joined relation.
- `--group-by-table CLASS` algorithm (canonical form):
  1. Resolve `--class` to the *counted* relation `C`; apply `--key` restrictions to `C`.
  2. Resolve `--group-by-table CLASS` to the *grouping* relation `G`.
  3. Form `joined = C * G.proj()`. The `.proj()` keeps only `G`'s primary-key fields, so the group key is unambiguous and equal to `G.primary_key`.
  4. Aggregate via DataJoint: `G.aggr(joined, n=f"count(distinct {field})")` for `--count-distinct field`. Use `G` (not `joined`) as the aggregation source so the result key is `G.primary_key`. DataJoint's default `keep_all_rows=False` means output has one row per matching `G` primary-key tuple, which is the desired eval #19 shape. Do not set `keep_all_rows=True` in MVP unless a prompt explicitly asks for zero-count groups.
  5. Validate `field` exists on `C.heading.names` (the counted relation), not `G`.

  For eval #19: `--class Electrode --key subject_id=aj80 --group-by-table Session --count-distinct electrode_group_name` becomes `Session.aggr(Electrode & {"subject_id": "aj80"} * Session.proj(), n="count(distinct electrode_group_name)")`. Output rows: `{"nwb_file_name": "...", "count_distinct_electrode_group_name": N}`.
- `--count-distinct` field must exist on the relation being counted.
- Output rows are dictionaries with the group fields plus `count_distinct_<field>`.
- No free-form aggregate expressions in MVP.
- Use DataJoint aggregation. If a DataJoint aggregation cannot be expressed (e.g., the SQL backend rejects the form), refuse with exit `2` rather than fetching all rows into Python — Python-side grouping is too easy to mis-bound.

## Follow-on subcommands

These should be planned but not block the MVP PR unless implementation stays small.

### `describe`

```bash
db_graph.py describe CLASS --json
```

Runtime view from DataJoint:

- table full name and module/class path
- `heading.primary_key`
- `heading.secondary_attributes`
- attribute types from `heading.attributes`
- parent/child table names when available
- part tables when available
- row count, optionally gated behind `--count`

Use cases:

- custom tables outside `$SPYGLASS_SRC`
- runtime schema drift
- source graph says one thing, DB graph says another

### `path`

```bash
db_graph.py path --up CLASS --json
db_graph.py path --down CLASS --json
db_graph.py path --to A B --json
```

Runtime graph traversal from DataJoint parents/children/diagram APIs. This is a fallback for cases where source declarations diverge from imported runtime state. Keep the shape aligned with `code_graph.py path` where practical: `nodes`, `edges`, `max_depth`, `truncated`, `record_id` equivalent when possible.

## Routing updates

Update `skills/spyglass/references/feedback_loops.md`:

- Code graph: source declarations, method ownership, FK declarations, source-only paths.
- DB graph: row existence, counts, merge IDs, live imported custom tables, runtime-vs-source divergence.
- Disk graph: concrete artifact paths.

Add a short "try order":

1. Use `code_graph.py` for source facts.
2. Use `db_graph.py find-instance` for row facts.
3. If `db_graph.py` exits `5`, fall back to user-session snippets and explain that the CLI cannot see notebook-only environment variables or imports.
4. Add the exit-code-5 caveat: `code_graph.py` exit `5` means heuristic refusal; `db_graph.py` exit `5` means DB/session failure.

Insertion point: `skills/spyglass/references/feedback_loops.md` section `### Three graphs, three primitive families`. Add a DB-row/runtime row directly after the source-code row, and add one short paragraph after the table explaining the two `exit 5` meanings.

Update `skills/spyglass/scripts/README.md` with a concise row and upstream candidate, matching the existing lifecycle style:

| Script | Upstream candidate |
| --- | --- |
| `db_graph.py` | `spyglass.utils.db_graph` or `spyglass.cli.db_graph`; upstream merge should preserve `info --json` and read-only/no-write guarantees |

Do not add a long `SKILL.md` section. At most add one routing row if the reference table lacks a DB graph entry.

## Test plan

### Unit tests, no DB

Add `skills/spyglass/tests/test_db_graph.py`.

Add `skills/spyglass/tests/fakes.py` for shared fake DataJoint-like relation objects, then use those fakes from `test_db_graph.py`:

- relation restriction by dict
- `fetch("KEY")`
- `fetch(*fields, as_dict=True)`
- `len(relation)`
- mock heading with `primary_key`, `names`, and attributes
- mock merge master/part resolution
- fake `aggr`, `proj`, join, restriction, antijoin, and fallback-limit behavior where needed

Fixtures:

1. class resolution: unique stock class maps to module import path
2. class ambiguity returns exit `3`
3. not found returns exit `4` with suggestions/candidates
4. scalar `--key` parsing
5. field validation catches unknown restriction field
6. `--count` returns count payload
7. row fetch returns stable JSON payload
8. `--limit` sets `truncated`
9. merge master restriction applies to part, not master
10. intersect returns shared keys
11. except returns left-minus-right keys
12. join validates output fields
13. grouped count by explicit fields
14. grouped count by table primary key (`--group-by-table Session`)
15. DB connection/import error returns exit `5` without traceback/secrets
16. unsafe raw query shape is refused with exit `6`
17. schema envelope fixture pins top-level field order and presence: `schema_version`, `kind`, `graph`, `authority`, `source_root`, `db`, `query`, `count`, `limit`, `truncated`, `incomplete`, `timings_ms`, then shape-specific fields such as `rows` / `merge` / aggregate output. Build JSON with stable insertion order and `sort_keys=False`.
18. `find-instance` uses the direct relation path and does not instantiate `RestrGraph` / `TableChain`; enforce by monkeypatching `spyglass.utils.dj_graph.RestrGraph` and `TableChain` to raise on construction.
19. Python-side set-operation fallback marks `incomplete: true` when the bounded key fetch hits the limit
20. zero-overlap `--join` is refused with exit `2`
21. `timings_ms` keys are present on successful DB-reaching payloads: `import`, `connect`, `resolve`, `heading`, `query`, `serialize`, `total`; assert `total >= sum(parts) - 1` to allow rounding
22. connection/import errors map to exit `5` without traceback/secrets: mock `ModuleNotFoundError("datajoint")`, `datajoint.errors.LostConnectionError`, auth/access errors, and `pymysql.err.OperationalError` where available
23. read-only invariant is structurally enforced: monkeypatch `insert`, `insert1`, `delete`, `delete_quick`, `drop`, `drop_quick`, `populate`, and `.alter()` on the fake relation to raise `AssertionError`; assert no `find-instance` code path (basic, merge, intersect, except, join, group-by, group-by-table, count) triggers any of them. Pins the read-only-by-construction claim the way fixture #18 pins the no-RestrGraph claim.

### Optional integration tests

Add a skipped-by-default mode:

```bash
python skills/spyglass/tests/test_db_graph.py --integration
```

Only run if a test DB is explicitly configured. Use a tiny DataJoint schema created for the test, not the user's real Spyglass DB. The integration test should prove:

- actual DataJoint restriction and fetch
- unknown attribute handling
- join/intersection behavior
- connection error classification

Do not require integration tests in pre-commit.

### Validation

Extend `validate_all.sh` with a gated unit-test step for `test_db_graph.py`, but keep integration informational/skipped unless env vars are present.

Run before merge:

```bash
./skills/spyglass/scripts/validate_all.sh --spyglass-src /Users/edeno/Documents/GitHub/spyglass/src --baseline-warnings 3
ruff check .
```

## Rollout plan

### Batch A - scaffold and contract

- Add `db_graph.py` skeleton with argparse, `info --json`, exit codes, safe JSON renderer, provenance envelope, and timing envelope.
- Add `tests/fakes.py` and `test_db_graph.py` schema/exit-code fixtures.
- Add README lifecycle row.

Acceptance:

- `db_graph.py info --json` works without importing DataJoint.
- `info --json` exposes `subcommands`, `exit_codes`, `payload_envelopes`, `result_shapes`, `security_profile`, `null_policy`, and `comparison` vs `code_graph.py`.
- Unit tests cover ordered payload envelopes.
- Successful DB-reaching payloads include the full `timings_ms` key set.

### Batch B - class resolution

- Implement class resolution for explicit module paths, `--import`, `--src`, installed Spyglass package root, `$SPYGLASS_SRC`, and stock Spyglass short names via `_index.py` / `code_graph._resolve_class`.
- Add ambiguity/not-found/suggestion payloads.
- Add the DataJoint table-class predicate without instantiating the class as the primary check.

Acceptance:

- Installed-package and editable-source environments both resolve stock classes.
- Stock class resolution works without importing all Spyglass modules.
- Ambiguous short names fail loud.
- Custom module path is supported.
- `_index.resolve_src_root` either gets the installed-package fallback backported or the documented divergence is covered in `info --json`, `feedback_loops.md`, and `scripts/README.md`.

### Batch C - basic `find-instance`

- Implement scalar restrictions, field validation, count, row fetch, limit/truncation.
- Add safe serialization for common scalar types.
- Keep the implementation on direct DataJoint relation operations; do not invoke `RestrGraph` or `TableChain`.

Acceptance:

- Eval shapes #9 to #13 are addressable.
- Eval #9 shape: `--class Session --key nwb_file_name=X --fields KEY` returns `query.resolved_class`, `count`, bounded `rows`.
- Eval #10 shape: selected fields return per-field serialized values rather than aborting on one unserializable field.
- Eval #11 shape: `IntervalList` field fetch returns bounded interval names.
- Eval #12 shape: `--count` returns count-only payload with `rows: []`.
- Eval #13 shape: row lookup resolves the merge/source key evidence needed before the user fetches a dataframe; dataframe/blob fetching remains out of scope.
- Unknown restriction fields cannot silently no-op.
- The direct-relation-path fixture proves the MVP did not inherit broad graph traversal cost.

### Batch D - merge-aware lookup

- Implement `--merge-master --part`.
- Add explicit merge payload and tests for the silent wrong-count footgun.

Acceptance:

- Eval shapes #14 to #16 and #50 are addressable.
- Eval #14/#15/#16 shapes return `merge.master`, `merge.part`, `restriction_applied_to: "part"`, `master_key_fields`, and merge IDs / master rows.
- Eval #50 shape: when the user supplies `--merge-master MASTER --part PART`, restrictions route through the part deterministically (per the merge-master algorithm above). Exit `2` is reserved for the misuse case where the user names only `--class MASTER` (no `--merge-master`/`--part`) with a part-only field — that path is refused with the silent-no-op explanation. The "ambiguous: refuse or route" framing is intentionally not used; the algorithm is deterministic.
- A merge master cannot return whole-master counts from a silently ignored restriction on any code path.

### Batch E - set operations

- Implement `--intersect`, `--except`, conservative `--join`, `--group-by`, and `--group-by-table`.
- Add tests for shared-key validation, output fields, and bounded fallback behavior.

Acceptance:

- Eval shapes #17, #18, #19, #28, #29 are addressable, including the `--group-by-table Session --count-distinct electrode_group_name` form for #19.
- Eval #17 shape uses DB-side intersection when possible and returns shared session keys.
- Eval #18 shape uses DB-side antijoin when possible; bounded fallback marks `incomplete: true`.
- Eval #19 shape uses DataJoint aggregation and returns one row per matching `Session.primary_key`.
- Eval #28/#29 shapes join to `BrainRegion` only through shared attributes; zero-overlap joins are refused.
- Set operations do not require unbounded `fetch("KEY")`; if a fallback cannot prove completeness under the limit, payloads set `incomplete: true`.

### Batch F - optional runtime `describe`

- Add `describe CLASS --json` if Batch A to E are stable.
- Keep it smaller than `code_graph.py describe`: runtime heading and relationships only.

Acceptance:

- Runtime heading can verify PK/field claims and custom table visibility.

### Batch G - optional runtime `path`

- Add `path --up`, `--down`, `--to` only if DB/source divergence examples justify it.

Acceptance:

- Output shape aligns with `code_graph.py path`.
- Runtime traversal is clearly labeled as DB authority.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| The CLI cannot see notebook-only env vars or imports | Document this in exit-5 hints; support `--import`; keep user-session snippet fallback |
| Accidental secret leakage | Never print raw config, connection strings, or tracebacks; scrub exception text |
| Unknown restriction fields silently no-op in DataJoint | Validate fields before restriction; special-case merge master routing |
| Overbuilding a query language | Keep MVP to equality keys, fields, count, merge, simple set ops; no raw SQL |
| Inheriting slow full-graph behavior from existing Spyglass utilities | Keep `find-instance` on direct relation operations; reserve `RestrGraph` / `TableChain` style traversal for explicit follow-on modes |
| Python-side set operations accidentally fetch broad tables | Prefer DB-side operations; otherwise fetch bounded keys only and mark incomplete results |
| Subprocess connection cost dominates eval throughput | Record `timings_ms.connect` from Batch A; flip to `batch` / stdin-fed mode if `connect` is more than half of `total` across realistic evals |
| `_index.resolve_src_root` exits before installed-package fallback | Backport fallback if feasible; otherwise try installed-package resolution before calling `_index.resolve_src_root` and document the divergence |
| `dj.config` mutation leaks across tests | Save/restore `dj.config.copy()` in fixtures that import DataJoint |
| Custom-table `--import` runs arbitrary import side effects | Document this in `info --json.security_profile`; imports are user-named and no Python `eval` is provided |
| Spyglass renames `RestrGraph` / `TableChain` and the direct-path fixture goes stale | Pin the import path in fixture #18 and re-run `tests/test_db_graph.py -k restrgraph` when bumping the Spyglass source baseline |
| Live DB tests are flaky | Mock by default; integration opt-in only |
| LLM treats DB rows as source truth | Payload says `graph: "db"` and `authority: "runtime-db"`; routing docs distinguish DB vs code |
| Custom tables are not importable | Require `--import` or explicit module path; return actionable exit `3`/`4` |

## Open questions

Resolved during the 2026-04-26 critique pass:

- ~~Empty result default exit code.~~ **Resolved:** exit `0` with `count: 0`; opt-in `--fail-on-empty` returns exit `7`. See "Exit codes" above.
- ~~`--allow-empty` flag.~~ **Resolved:** dropped. Inverted to `--fail-on-empty` so the safe default needs no flag.
- ~~Merge-mode part-relation-first vs `_Merge` helpers.~~ **Resolved:** part-relation-first is canonical; `_Merge` helpers may be used to confirm but never to substitute (their direction is master→part, opposite to the eval pressure).

Still open:

- `--db-user` / `--db-host` flags? Recommended no for MVP. Let DataJoint config load normally; add flags only if users repeatedly hit env-only auth issues.
- Should `db_graph.py` support `--config PATH` to load a non-default `dj_local_conf.json`? Possibly useful for "agent runs against a test schema" workflows. Defer until evals demand it.

## Definition of done

- `db_graph.py find-instance` addresses the 13 `find-instance` evals plus the merge-silent wrong-count eval named in the decision record.
- The tool is read-only by construction.
- `info --json` exposes `subcommands`, `exit_codes`, `payload_envelopes`, `result_shapes`, `security_profile`, `null_policy`, and a `comparison` block vs `code_graph.py`.
- JSON output is stable, ordered, provenance-stamped, and safe for LLM citation.
- Unknown-field and merge-master silent-no-op hazards are tested.
- Exit-code split (`0` / `4` / `7`) for class-not-found vs zero-rows-with-fail-on-empty is implemented and tested.
- `find-instance` is implemented as a direct-relation fast path, not a wrapper around broad runtime graph traversal.
- Set operations either run database-side or clearly mark bounded/incomplete fallback evidence.
- Zero-overlap joins are refused in MVP.
- Per-batch acceptance sections name the eval ids and expected payload-shape contracts.
- `tests/fakes.py` provides the shared mock-relation harness.
- `_index.resolve_src_root` either backports installed-package fallback or the divergence is documented in `info --json`, `feedback_loops.md`, and `scripts/README.md`.
- Default test suite runs without a live DB.
- `feedback_loops.md` routes DB/session questions to `db_graph.py` and preserves the fallback to user-session snippets.
- `scripts/README.md` documents lifecycle and upstream candidate.
