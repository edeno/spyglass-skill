# `db_graph.py` — decision record

**Status:** decision record (not a build plan).
**Date:** 2026-04-26.
**Question:** should we build `db_graph.py` as a sibling to `code_graph.py`?
**Decision:** **YES** — build it in a separate PR after `feature/inquiry-time-navigation` merges. ~16 evals are blocked by the source-only graph's documented blind spots (find-instance, runtime data lookup, cross-table joins). The killer subcommand is `find-instance`.

---

## What this document is

This is a **decision record**, not a build plan. It captures the framing for whether to build `db_graph.py`, the cost/benefit, and the specific eval pressure that motivates the decision. If the recommendation is "build it" (and it is), the next artifact is a separate `db-graph-impl-plan.md` that follows the `code-graph-impl-plan.md` mold.

It exists for two reasons:

1. **Freeze the rationale while it's fresh.** The reasoning behind "deferred → out of scope → maybe build it after all" lived only in the conversation around commits `e30426c` and `fa0438a`. Without writing it down, in two weeks the question "why didn't we build this?" or "why did we?" wouldn't have a coherent answer.
2. **Force the eval-pressure question.** "Build it if N evals fail because of source-only blind spots" is a dodge unless you actually count the evals. This document does the count.

---

## Context — what we ship today

`feature/inquiry-time-navigation` ships a source-only code-graph subsystem:

- `_index.py` — AST scan of `$SPYGLASS_SRC/spyglass/`. Returns a frozen `ClassIndex` with ~310 `ClassRecord`s. Stdlib-only. lru_cached.
- `code_graph.py` — three CLI subcommands consuming `_index`:
  - `describe X` — node view: tier, bases, structured PK/FK, methods inherited from registered mixins, parts.
  - `path --to A B / --up X / --down X` — FK chain traversal with master-part containment bridges.
  - `find-method Y` — reverse method index plus mixin inherited-availability summary.
- Validator integration: `validate_skill.py` consumes `ClassIndex` for schema-shape checks; multi-version (v0/v1) ambiguity surfaces as fail-loud warnings.

The system is constrained to be source-only:

- No `import spyglass`, no `import datajoint`.
- Stdlib-only (`ast`, `argparse`, `json`, `pathlib`, `dataclasses`, `functools`).
- ~0.3s scan, lru_cached per process.
- Runs on a machine with no Spyglass install or DB access.

This constraint was deliberate. It's also responsible for the system's three documented blind spots, listed in `code_graph.py:53-83`:

1. **Mixin / base-class FKs.** `SpyglassMixin`, `_Merge`, etc. don't add FKs but DO add inherited methods. (Mitigated by `find-method` + `describe`.)
2. **Cross-pipeline merges via dynamic part registration.** Static AST sees only what's in source at scan time.
3. **Runtime-overridden FKs.** Tables whose `key_source` is overridden in Python rather than declared in `definition` aren't reflected.
4. **Path ambiguity.** Multiple FK paths exist; we print the shortest.
5. **Cross-class redesigns.** v0 `Curation` ≠ v1 `CurationV1`; the graph won't link them.
6. **Inheritance in `definition`.** Classes inheriting `definition` via Python class inheritance are invisible.
7. **Expression-form refs.** DataJoint resolves `->` ref-tables via Python `eval()` against the import namespace.
8. **Custom tables outside `$SPYGLASS_SRC`.** Lab-member-defined or external-package-defined tables are invisible to the AST scan.

A ninth blind spot, **not in the docstring** but identified during smoke testing of the eval surface (see eval #73): the source-only graph only sees declared FKs. It cannot see **runtime data dependencies** (e.g. v0 `LFP.make_fetch()` calls `.fetch()` on `Raw` to populate, but no `-> Raw` FK exists). The eval expects `Raw` in the LFPBandV1 upstream answer; the CLI correctly omits it because it's not in the static graph. The answer requires combining CLI output with skill-content prose.

---

## Why DB-resolved tools were originally framed "out of scope"

In commit `e30426c` we explicitly rejected `db_graph.py` as a future deliverable. The argument:

> DB-resolved variants (live `Table.descendants()` / `dj.Diagram`) are out of scope for this source-only tool — the user's analysis session is the authoritative source for those.

Three premises supported this:

1. **The user already has DJ access in their session.** A 2-line fallback ("import the table and call `.descendants()`") is cheap.
2. **A separate DB connection from a CLI is awkward.** Either it spawns its own (auth, latency) or it shells out to the user's session somehow (impossible without IPC).
3. **Custom tables: the agent doesn't know what's imported in the session, so the CLI couldn't either.** The agent has to ask the user anyway.

Premises 1 and 2 stand. **Premise 3 was incomplete reasoning.** The agent talking to the user IS a turn of latency + a chance for the user to mistype/paste-fail. A CLI invoked by the agent removes the user from the loop for questions the user wouldn't have wanted to answer manually anyway. The user only needs to be in the loop for *custom* tables (because import state isn't shared between processes); for stock Spyglass tables, the CLI can authenticate and query directly using the same `dj.config` the user's session uses.

The decision to reframe was correct **at the time** because we didn't have eval-pressure evidence. We now do.

---

## Eval pressure — the actual count

Out of 95 evals in `skills/spyglass/evals/evals.json`, **16 are genuinely blocked by the source-only graph's blind spots** in ways `db_graph.py` would close. Three more (#74, #75, #78) would benefit from runtime cross-checks but are answerable source-only.

### The 16 DB-required evals

Grouped by which `db_graph.py` subcommand would close them.

#### `find-instance` (the killer subcommand) — 13 evals

"Is there a row matching X?" / "What's the merge_id for Y?" / "Fetch row attributes for Z." Source-only graph cannot answer; agent currently has to write the DJ query and ask the user to run it.

| Eval | Question | Required CLI |
|---|---|---|
| #9 atomic-fetch-session-row | Get the Session row for X | `find-instance --class Session --key nwb_file_name=X` |
| #10 atomic-fetch-session-attributes | Fetch specific fields for X | `find-instance --class Session --key X --fields description,start_time` |
| #11 atomic-list-intervals-for-session | List interval_list_name for X | `find-instance --class IntervalList --key X --fields interval_list_name` |
| #12 atomic-count-electrodes | How many Electrode rows for X | `find-instance --class Electrode --key X --count` |
| #13 atomic-trodes-position-dataframe | Fetch dataframe for X | `find-instance` to resolve merge_key, then user fetches dataframe |
| #14 merge-key-trodes-position | Find merge_id for Trodes pos on X | `find-instance --merge-master PositionOutput --part TrodesPosV1 --key X` |
| #15 merge-key-lfp-default | Find LFP merge_id for X | `find-instance --merge-master LFPOutput --part LFPV1 --key X` |
| #16 merge-key-decoding-clusterless | Find DecodingOutput merge_id | `find-instance --merge-master DecodingOutput --part ClusterlessDecodingV1 --key X` |
| #17 join-sessions-with-ripples-and-decoding | Sessions with both X and Y populated | `find-instance --class RippleTimesV1 --intersect ClusterlessDecodingV1 --fields nwb_file_name` |
| #18 join-sessions-trodes-but-no-dlc | Sessions with X but not Y | `find-instance --class TrodesPosV1 --except DLCPosV1 --fields nwb_file_name` |
| #19 count-tetrodes-per-session | Per-session aggregate count | `find-instance --class Electrode --key subject_id=aj80 --aggregate count(distinct electrode_group_name) --group-by Session` |
| #28 brain-region-for-curated-sorting | Given sorting_id, what region? | `find-instance --class CurationV1 --key sorting_id=X --join BrainRegion --fields region_name` |
| #29 brain-region-for-lfp-electrode | Given electrode_id, what region? | `find-instance --class Electrode --key X,electrode_id=7 --join BrainRegion --fields region_name` |

#### `find-instance` with merge_restrict semantics — 1 eval

| #50 merge-silent-wrong-count | Count merge rows by session — but merge restriction silently no-ops on non-PK fields | The CLI should detect this case (restricting a merge master by a part-table-only field) and surface it loudly, returning the actual count via `merge_restrict` semantics |

#### `describe` from runtime heading — 2 evals

| #69 counterfactual-two-users-empty | Compare two users' results | `describe --runtime` shows the actual `Selection` row state, including UserEnvironment context |
| #85 recover-parameter-edit-in-place | Find rows that depend on edited params | `find-instance --class RippleTimesV1 --key ripple_param_name=X` to enumerate stale rows |

### Marginal — runtime cross-check would help but source-only is sufficient

| Eval | Source-only suffices via | DB cross-check would add |
|---|---|---|
| #74 schema-pk-electrode | `describe Electrode` shows PK from definition | Eval expects "show me the one-liner you'd run to verify" — DB describe could provide the literal `Electrode.heading.primary_key` invocation |
| #75 schema-pk-firfilterparameters | same | same |
| #78 schema-part-tables-probe | `describe Probe` shows parts | same |

These are nice-to-haves, not blockers.

### Source-only sufficient — already handled

The remaining ~76 evals split across:

- **Code-graph-shaped (already work):** #5, #7, #8, #21, #51, #54-57, #58, #66, #67, #72, #73, #76, #77, #79, #80, #81, #89.
- **Skill-content questions (no CLI needed):** debugging recipes, parameter explanations, framework concepts, install / setup, destructive ops, hallucination-resistance abstentions.
- **Adversarial / non-activation:** #20, #22, #23, #24, #43.

### Verdict on eval pressure

**16 hard-blocked evals + 3 marginal = 19 evals that benefit from `db_graph.py`.** The 16-blocker count is well above any reasonable threshold for "build it." The killer use case is `find-instance` (13 of the 16).

For comparison, `code_graph.py`'s three subcommands cover ~16 evals total (per the impl plan's claim). `db_graph.py` would cover a comparable surface.

---

## Design sketch

### Subcommand surface

Three subcommands, mirroring `code_graph.py`'s shape where overlap exists.

#### `find-instance` — the new capability

```
db_graph.py find-instance --class CLASS [--key K=V ...]
                          [--fields F1,F2,...]
                          [--merge-master M --part P]
                          [--intersect OTHER_CLASS]
                          [--except OTHER_CLASS]
                          [--join OTHER_CLASS]
                          [--aggregate EXPR --group-by CLASS]
                          [--count] [--limit N] [--json]
```

Run a DJ restriction + (optional) join + (optional) aggregate, return rows or count as JSON.

**Semantics:**

- `--key field=val` — repeatable. Translates to a DJ restriction dict.
- `--fields f1,f2` — `.fetch(*fields)`. Default: `.fetch('KEY')` returning PKs.
- `--merge-master M --part P --key K=V` — translates to `M.merge_get_part({**key})` for the merge-restriction-via-part-table pattern (closes #14, #15, #16).
- `--intersect OTHER` — `.intersect()` with the other class's PK.
- `--except OTHER` — antijoin via `.fetch('KEY')` set difference (the portable form documented in eval #18's expected output).
- `--join OTHER` — `*` join.
- `--aggregate EXPR --group-by CLASS` — `.aggr(OTHER, alias='count(...)')` shape (closes #19).
- `--count` — return `len(restriction)` only.
- `--limit N` — for safety; default 100, max 10000.

**Exit codes:**

- 0 — query succeeded, rows returned (count > 0 or count==0 with `--allow-empty`).
- 4 — query succeeded, zero rows (default; the "I checked, the answer is no" signal).
- 2 — usage error.
- 5 — DB error (new code, distinguishes "no answer" from "tool broken").

**Why exit code 5 is new:** `code_graph.py`'s exit codes (0/2/3/4) cover source-only failure modes. DB failures are a fundamentally different category — credentials wrong, DB unreachable, schema not found — and the agent's behavior should differ ("retry source-only" for code 5, "the answer is no" for code 4). One new code is justified.

#### `describe` — runtime heading + runtime descendants

```
db_graph.py describe <Class> [--json]
```

Fallback for when `code_graph.py describe` returns `not_found` or has stale source info. Same JSON shape as `code_graph.py describe` where keys overlap; populated from `Table.heading` + `Table.parents()` + `Table.children()` + `.parts()` rather than AST.

**Use cases:**

- Custom tables outside `$SPYGLASS_SRC` (blind spot #8).
- Runtime-overridden FKs (blind spot #3).
- Verify the source-graph answer matches runtime (closes #74, #75, #78).

#### `path` — runtime descendants / ancestors

```
db_graph.py path --to A B / --up X / --down X [--max-depth N] [--json]
```

Same surface as `code_graph.py path`, populated from `Table.ancestors()` / `Table.descendants()`. Mostly a fallback for source-only blind spots; the agent's routing decision is "try `code_graph.py` first, fall back to `db_graph.py` if exit-4 OR if asking about custom tables."

### What we DON'T build

- **`find-method`** — DJ doesn't expose method definitions at runtime in any useful way. Python `inspect` does, but at that point we're not using DJ. Stay source-only for method lookups.
- **Aggregate over arbitrary expressions.** `--aggregate` accepts only `count(...)`, `sum(...)`, `min(...)`, `max(...)`, `avg(...)`. No arbitrary SQL injection surface.
- **Write operations.** Read-only. No `insert`, `delete`, `update`, `populate`. The whole point is that the agent uses this to inspect, not modify. Modifications go through the user's session.

### Authentication

- Don't read `dj_local_conf.json` directly. Core Directive #6 of SKILL.md prohibits raw reads of DJ config.
- Let `import datajoint as dj` load its config the standard way (env vars + cwd lookup). Then read `dj.config` after import.
- Hard-fail with a clear message if no DB connection available: exit 5, stderr message naming the most likely fix ("your session has DJ_USER set but the CLI doesn't — pass `DJ_USER=$DJ_USER` to the invocation").

### Output

- JSON via `--json` (default for agent invocations) with `schema_version: 1`. Same shape as `code_graph.py` outputs where they overlap (e.g. `describe` returns the same `class`, `bases`, `pk_fields`, `fk_edges` keys).
- Human output for debugging; same renderer style as `code_graph.py`.
- All `find-instance` outputs include a `query` field showing the DJ expression that was actually executed — auditability.

### Testing

- Synthetic-tree fixtures don't work (the whole point is real DB).
- Two-tier strategy:
  - **Unit fixtures:** mock `dj.Table` to verify exit code / JSON shape logic. Fast, run in pre-commit.
  - **Integration fixtures:** docker-compose MySQL with a minimal schema. Run in CI only, with a `--integration` flag for skip-on-no-DB locally. Matches Spyglass's CI pattern.
- Add `--mock-dj` flag for unit tests so the CLI's argparse + JSON-formatting logic can be tested without a real DB.

### Lifecycle

- Module docstring must include a Lifecycle paragraph naming the upstream target.
- Candidate: `spyglass.utils.db_graph` (or `spyglass.cli.db_graph`).
- The DB-resolved tools are arguably **more natural in upstream Spyglass than the source-only ones** — they require Spyglass anyway, so they have no reason to live as a separate prototype indefinitely.
- When upstream merges, retire `db_graph.py` from this skill and route at `python -m spyglass.db_graph` instead.

---

## Costs

### Hard runtime dependency

- `import datajoint`, `import spyglass.utils.dj_mixin` (for `_Merge` detection at runtime).
- `uv run --with spyglass-neuro --with datajoint` works for one-off invocations; the user's existing env works for normal use.
- **This breaks the source-only constraint that the rest of the skill carefully maintains.** That's why it's a sibling tool, not an extension of `code_graph.py`.

### Connection latency

- DJ connection setup ~1-3s on first invocation per process.
- lru_cache won't help across separate process invocations (each CLI call is a new process).
- Mitigation: keep invocations rare; the agent should batch-query when possible (one `find-instance` with multiple `--key` values rather than three separate calls).

### Failure modes the source-only tool doesn't have

- DB down / network blip → exit 5, retry source-only is the agent's fallback strategy.
- Wrong credentials → exit 5 with credential-naming hint.
- Schema not found (rare, but possible if DB has pre-2024 schema) → exit 4 (treated as "no answer" — the agent moves on).

### Authentication subtlety

- The CLI runs in a separate process from the user's notebook. Env vars set in the notebook (`os.environ['DJ_USER']`) are NOT visible to the CLI.
- The user's `dj_local_conf.json` IS visible (DJ reads it from cwd or `~`).
- For environments that rely on env-var-only auth, the agent has to explicitly pass `--db-user X --db-pass-from-env DJ_PASS` style arguments, or invoke the CLI from the user's shell with the env exported.
- Document this clearly. Probably the #1 source of "the CLI doesn't work" support questions.

### Test infrastructure

- Docker-compose MySQL fixture in `skills/spyglass/tests/integration/`.
- CI gate: integration tests only run with `--integration` flag and only in GitHub Actions (not pre-commit). Skip cleanly with a clear message if the docker-compose isn't available.
- Adds ~2-3 minutes to CI time. Accept.

---

## Decision criteria — recap

The threshold for building was "≥3-5 evals blocked by source-only blind spots." We have **16 hard-blocked + 3 marginal = 19 evals** that benefit. Well above threshold. **Build it.**

### Why NOT in the inquiry-time-navigation PR

Three reasons, all unchanged from the conversation:

1. **PR size.** The current PR is 33 commits / +7000 net lines. Adding ~600 LOC + tests + docs pushes it well past easy-review territory. A separate PR keeps each shippable independently reviewable.
2. **Design constraint blur.** The inquiry-time-navigation PR is committed to "source-only, stdlib-only, runs without `import spyglass`." `db_graph.py` is the explicit opposite. Merging them blurs the design constraint and makes future readers wonder why some scripts have one constraint and some don't.
3. **Different validation story.** `code_graph.py` is verified by synthetic-tree fixtures + smoke testing on real Spyglass source. `db_graph.py` requires docker-compose integration tests. The CI surface is different.

### What's next if "build it"

Write `docs/plans/db-graph-impl-plan.md` in the `code-graph-impl-plan.md` mold (~800-1500 lines). That plan has:

- Per-subcommand build sequence with exact CLI shapes.
- Per-eval coverage matrix (the 16 + 3 evals from this document, what specific invocation closes each).
- Test strategy (unit + integration split, docker-compose fixture).
- Authentication design + env-var subtlety documentation.
- File-by-file scope: `db_graph.py` (~600 LOC), `tests/test_db_graph_unit.py` (~300 LOC), `tests/integration/test_db_graph_integration.py` (~400 LOC), `tests/integration/docker-compose.yml`, `tests/integration/schema.sql`.
- Lifecycle paragraph + upstream-migration target.

Then build in a separate branch (`feature/db-graph`) off master after the inquiry-time-navigation PR merges.

### What's next if "don't build it"

Document the existing escape hatch better in `feedback_loops.md` and (for the merge_id-fetching evals especially) in the relevant pipeline references. The escape hatch is "agent writes the DJ query, user runs it in their session, pastes back the output." This works but adds a turn of latency and is a hallucination risk (agent may write the wrong query).

We are **not** taking this path because the eval-pressure count is high enough to justify the build.

---

## Open questions for the build plan

These are flagged here so they don't get forgotten when the impl plan is written:

1. **`merge_get_part` vs `merge_restrict` semantics.** The merge-table API has two restriction patterns; #50 documents the silent-no-op footgun. `find-instance` should pick the safe one by default and surface the unsafe one only on opt-in.
2. **Does `--except` use set-difference (the portable form per #18) or DJ antijoin?** Set-difference is portable; DJ antijoin is faster but has the dependent-attribute footgun (#18 documents it). Default to set-difference, document the tradeoff.
3. **How does the agent know to fall back from `code_graph.py` to `db_graph.py`?** The `feedback_loops.md` routing block needs a clear decision tree. Probably: "try `code_graph.py` first; if exit-4 AND the question involves runtime data (merge_id, row counts, joins), try `db_graph.py`."
4. **Caching across invocations?** Per-invocation lru_cache is useless (separate processes). Cross-invocation caching (write JSON to a temp file, read back if fresh) is doable but adds complexity. Skip for v1.
5. **Pagination.** `find-instance` with `--limit 100` is the default. What about queries that want more? `--limit 0` for no limit (with a warning)?

---

## References

- `skills/spyglass/scripts/code_graph.py` — the source-only sibling.
- `skills/spyglass/scripts/_index.py` — the AST scan layer.
- `skills/spyglass/references/feedback_loops.md` — current routing for "three graphs" framing.
- `docs/plans/code-graph-impl-plan.md` — the build plan we'd mirror.
- `docs/plans/inquiry-time-navigation-plan.md` — the precedent for sketch-then-build.
- `skills/spyglass/evals/evals.json` — the 95 evals.
- Commit `e30426c` — the original "out of scope" reframing (now superseded by this document).
- Commit `fa0438a` — extending parts-as-upstream-contributors to all nested parts; surfaced eval-pressure evidence that motivated this revisit.
