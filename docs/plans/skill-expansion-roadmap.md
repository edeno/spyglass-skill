# Spyglass skill — expansion roadmap

**Date:** 2026-04-22
**Author drafted by:** Claude, via skill-creator best practices
**Status:** Revised 2026-04-27 after `code_graph.py` and `db_graph.py`

---

## Motivation

We want to grow the spyglass skill from a **text-only guardrail/router** into
the language layer for three research aims:

1. **AI-assisted onboarding and decision support** — parameter literacy,
   context-aware guidance, natural-language querying, boilerplate
   generation.
2. **AI-assisted data health monitoring** — metric ontology, anomaly
   flagging, lab-level health summaries.
3. **Cross-dataset meta-analysis (reach)** — reusable cross-dataset
   queries, pattern ranking with provenance, human-in-the-loop
   exploration tooling.

Gap analysis originally found that most Aim 1 text deliverables were partly
shipped, while live database access and introspection were missing. That is no
longer the right baseline: `code_graph.py` now provides source-only
introspection, and `db_graph.py` provides a bounded read-only runtime database
inspection surface. This roadmap now prioritizes **using those tools well**
before adding more bundled scripts or adjacent services.

## Design principles (from skill-creator)

- **Progressive disclosure.** SKILL.md stays under its word cap; every
  new capability lives in a reference, a bundled script, or an adjacent
  package. If a topic grows past 500 lines, split — don't raise the cap.
- **Evals first (RED before GREEN).** Every new capability lands with a
  failing eval *first* so we can measure the lift. Regression fixtures
  for any new validator rule.
- **Explain the *why*.** New references follow the existing style: lead
  with the decision, include code, cite source. No "ALWAYS/NEVER" walls.
- **Lean prompts; bundle repeated work.** If Claude writes the same
  helper script twice across evals, bundle it into `scripts/` and teach
  the skill to invoke it.
- **In-skill vs. adjacent-infra split.** The skill is documentation +
  guardrails. Python packages, MCP servers, dashboards, and statistical
  tooling live in *sibling* repos — the skill teaches users how to
  invoke them. This keeps the skill installable by anyone without
  pulling in the whole analysis stack.

## Phase 0 — Baseline measurement (1–2 days)

Before changing more surface area, lock in **whether agents use the existing
tools correctly**. The next baseline is not "skill vs. no skill"; it is
"direct answer from memory" vs. "proof-carrying answer grounded in
`code_graph.py` / `db_graph.py`."

### Work items

- **0.1** Add 8–10 eval cases in `skills/spyglass/evals/evals.json`
  targeting proof-carrying behavior. Suggested cases:
  - "What key do I need for this table?" with a plausible but wrong field
    name in the prompt. Expected behavior: verify heading / key via
    `db_graph.py` or abstain if DB is unavailable.
  - "Does table A depend on table B?" where source-only structure is enough.
    Expected behavior: cite `code_graph.py path`, including merge hops and
    truncation/warnings if present.
  - "Why is my query empty after changing params?" Expected behavior: combine
    source path evidence with runtime row/count checks and avoid inventing
    parameter names.
  - "What does this parameter row actually affect?" Expected behavior: inspect
    the parameter blob, identify the consuming `make()` source, and flag
    third-party call sites rather than inferring from the parameter name.
  - "Can I ingest this unfamiliar raw NWB?" Expected behavior: inspect file
    metadata, namespaces, table shapes, and array shapes without reading array
    payloads or assuming the DB already knows the file.
  - "What did this AnalysisNWB output actually contain?" Expected behavior:
    inspect processing modules, object paths, table/dataset shapes, and
    extension namespaces without reading large payload values.
  - "My custom lab table is not in source." Expected behavior: use
    `db_graph.py --import` / runtime heading rather than `code_graph.py`.
  - "Source says the class exists, but the DB heading differs." Expected
    behavior: distinguish source truth from runtime DB truth.
  - "Explain `filter_name=lfp_600Hz` and when I'd pick it" (param
    literacy — Aim 1).
  - "I have 120 sessions; which have spike-sorting quality metrics
    below our lab's usual range on `nn_isolation`?" (metric
    interpretation + cross-session — Aims 2 + 3).
  - "Write the full selection-insert for running `DLCPosV1` on
    session X with params Y" (boilerplate generation — Aim 1).
  - "Given my current DB state, is it safe to re-run `populate` on
    these 5 sessions?" (context-aware guidance — Aim 1; requires
    runtime DB evidence and should abstain if no DB is available).
  - "Compare ripple rates across rats during novel-environment
    task" (natural-language query — Aim 1 flagship).
  - "Flag sessions where position tracking looked unstable" (Aim 2).
- **0.2** Run the existing skill-creator eval harness against these
  cases. Score both final correctness and evidence behavior: did the agent
  cite source/runtime evidence for table, key, method, and DAG claims? Save under
  `spyglass-workspace/iteration-0-baseline/`.
- **0.3** Publish the baseline numbers in this file (fill in Phase 0
  table at the end) so Phase 1+ can claim deltas honestly.

### Acceptance criteria

- [ ] 8+ new evals merged.
- [ ] Baseline benchmark.json committed (or linked from workspace).
- [ ] Each eval classified by required authority:
      `source-only`, `runtime-db`, `source+runtime`, `reference-only`, or
      `abstain/no-access`.

## Phase 1 — Skill-internal wins (2–3 weeks)

Highest-leverage, lowest-cost additions. Pure content + eval/validator work;
no new runtime dependencies.

### 1.0 Graph-tool integration and evidence habits

**Why:** The largest current hallucination reducers already exist. Agents now
need simple, copyable habits for when to call them and how to cite their
outputs.

**Deliverables:**

- Tighten `feedback_loops.md` and `runtime_debugging.md` examples around:
  source DAG evidence (`code_graph.py`), runtime row/key evidence
  (`db_graph.py`), and source/runtime disagreement.
- Add proof-carrying answer templates for insert/fetch/populate code:
  verified table, primary key, upstream key, row count, and remaining
  uncertainty.
- Add evals where direct confident answers fail and tool use or abstention is
  the expected behavior.
- Update stale script-priority docs so future work does not duplicate the two
  graph tools.

This is Phase 1's first step. Do it before catalogs or new scripts.

### 1.0.5 Parameter and NWB evidence probes

**Why:** Two valuable evidence surfaces remain outside the graph tools.
Parameters live in DB rows as blobs, but their effect is determined where
`make()` reads those blobs and passes values into Spyglass or third-party
functions. NWB files also carry facts the DB graph cannot see: raw files before
ingestion and AnalysisNWB files containing analysis results. They may be too
large to read into context. Both are common places where an agent otherwise
guesses.

**Deliverables:**

- Add evals for parameter traceability: params row -> blob summary -> consuming
  source location -> third-party call site -> uncertainty caveat.
- Add evals for lightweight NWB inspection: raw file metadata, AnalysisNWB
  processing modules/results, namespaces, table shapes, array shapes, object
  paths, and no array payload values.
- If evals show graph-tool + reference patterns are awkward, write narrow
  plans for `describe_params.py` / `trace_params.py` and `inspect_nwb_lite.py`.
- Keep both tools evidentiary. They should surface facts for the agent to cite,
  not decide scientific validity or ingestion policy by themselves.

### 1.1 Quality-metrics ontology reference

**Why:** Aim 2.1 asks for a formal mapping metric ↔ modality ↔ failure
mode. Today the skill only lists metric *names* in
`spikesorting_v1_pipeline.md`. A maintained ontology is a natural
addition and compounds with every downstream monitoring feature.

**Deliverables:**

- `skills/spyglass/references/quality_metrics.md` — prose with the
  decision tree and a reference table.
- `skills/spyglass/references/catalog/quality_metrics.yaml` — the
  same data, machine-readable. First entry in a new `catalog/`
  subdirectory for structured data.
- Router row in SKILL.md: "Interpreting quality metrics / data health
  checks → `quality_metrics.md`".
- 2 evals (one "explain this metric", one "interpret this range").
- Validator rule: each YAML entry's `source_file:line` citation must
  resolve in the Spyglass checkout. Add regression fixture first.

**Size budget:** aim for ≤ 300 lines on the `.md`; the `.yaml`
is unconstrained but organized.

### 1.2 Cross-dataset query recipes

**Why:** Aim 3.1 wants reusable cross-dataset queries. Today
`workflows.md § Batch Processing` has one pattern. Claude currently
reconstructs the others from scratch each time.

**Deliverables:**

- New reference `cross_dataset_queries.md` with 5–7 recipes:
  parameter-sensitivity sweep, representation-stability comparison,
  "find sessions with X and Y but not Z", per-subject summaries,
  longitudinal drift check, failed-vs-successful populate diff.
- Router row update.
- 2 evals: one parameter-sweep prompt, one "why did populate fail
  on these 5 but not these 47" prompt.
- If `workflows.md` + this file > 500 lines total, split cleanly.

### 1.3 Parameter catalog (structured)

**Why:** Aim 1.1 calls for a *searchable* index of parameters, not
prose. A YAML catalog serves both Claude (via the skill) and future
programmatic consumers (Aim 1.2 APIs).

**Current decision:** defer as a large static catalog until parameter trace
evals prove it is needed. Prefer live parameter inspection for row/blob facts
and source reads for behavioral consequences. A catalog is still valuable for
high-level parameter sensitivity labels, but it should not become a stale copy
of live Params table contents.

**Possible deliverables if revived:**

- `skills/spyglass/references/catalog/parameters.yaml` — one entry
  per parameter: name, parent table, type, default, legal range/enum,
  downstream sensitivity tag (`high` / `medium` / `low`), one-line
  description, source citation.
- Start small: spike-sorting + DLC position + ripple detection params
  only (covers ~70 % of real questions).
- `references/parameter_catalog.md` — short reader guide + query
  patterns ("how to look up a param", "how to surface sensitivity
  warnings").
- Validator rule: all referenced tables + fields exist in Spyglass
  source.

### 1.4 Boilerplate-generation audit

**Why:** Aim 1.3 highlights boilerplate generation as a high-impact
onboarding lever. Skill has canonical examples for each pipeline but
they vary in completeness. Audit for consistent "given these upstream
keys, here is the exact selection insert" pattern.

**Deliverables:**

- Sweep the 9 pipeline references. For each: confirm a working
  selection-insert example with realistic FK values and a comment
  marking "replace these".
- Add 2 evals: "generate the insert to run RippleTimesV1 on session
  X" and "same for DLCPosV1".
- No new files — this is polish of existing references.

### 1.5 Description re-optimization

**Why:** Every time scope expands, triggering drift creeps in. The
existing description is tight but doesn't cover the new "quality
metrics" / "cross-dataset query" surface.

**Deliverables:**

- After 1.1–1.4 land, run skill-creator's
  `scripts/run_loop.py --skill-path skills/spyglass` with an
  expanded 20-query trigger eval set (include the new capability
  queries + near-miss negatives like "show me cross-session patterns
  in a plain pandas DF" that should *not* trigger).
- Adopt the winning description; commit the eval set under
  `evals/trigger_eval_set.json`.

### Phase 1 acceptance

- [ ] All new references under size cap; validator clean.
- [ ] 8+ new evals green; aim-1/2/3 "text-achievable" cases show
      measurable lift over baseline.
- [ ] Re-optimized description passes triggering eval at ≥ 0.85 on
      held-out test set.

## Phase 2 — Adjacent infrastructure the skill calls (4–8 weeks)

This phase is now conditional. `db_graph.py` gives the skill a bounded
read-only DB inspection surface without running a persistent MCP server. A
separate MCP or Python package should wait until usage shows that subprocess
CLI calls are too slow, too hard to compose, or unavailable in the target
agent environments.

### 2.1 `spyglass-mcp` — read-only DataJoint MCP server

**Why:** Covers Aim 1.2 (programmatic introspection), enables Aim 1.3
context-aware guidance, and is the prerequisite for Aims 2/3 analyses
to run against real data. This remains plausible, but it is no longer the
first live-DB milestone; `db_graph.py` should be evaluated in real use first.

**Deliverables (separate repo `spyglass-mcp`):**

- Tools exposed: `list_tables(schema)`, `describe(table)`,
  `heading(table)`, `parents(table)`, `children(table)`,
  `fetch(table, restriction, limit)`, `restrict(table, key)`,
  `count(table, restriction)`, `merge_restrict(master, key)`,
  `merge_get_part(master, key)`.
- Hard guardrails: read-only credentials, no `delete`, no `populate`,
  no `insert`. Enforce at the MCP layer, not just by DB perms (belt
  and suspenders).
- Row cap on `fetch` (default 500, overridable per call).
- Optional: `provenance(merge_id)` returning the upstream chain.
- Config: reads DataJoint config the same way Spyglass does (env
  vars → `dj_local_conf.json` → `~/.datajoint_config.json`), never
  logs passwords.

**Deliverables (in this skill repo):**

- `skills/spyglass/references/mcp_query_patterns.md` — when to use
  MCP tools vs. writing Python, how to compose them, how results
  feed into follow-up restrictions.
- Router row: "Querying the live DB via MCP →
  `mcp_query_patterns.md`".
- `allowed-tools` in SKILL.md frontmatter extended to include the
  new MCP tools (scoped, not wildcard).
- 4+ evals that require live DB access — these will have failed in
  Phase 0 and now pass.

### 2.2 `spyglass-introspect` — Python introspection helpers

**Why:** Not every user wants to run an MCP server. A small Python
package offering the same primitives inside Jupyter/scripts covers
Aim 1.2 in a second delivery shape and is the substrate for
Aim 2.2 / 3.1 statistical tooling.

**Deliverables (separate repo `spyglass-introspect`):**

- `describe_pipeline_context(table)` → upstream keys, FK chain,
  required params, typical downstream consumers.
- `sensitive_parameters(table)` → params tagged `high` / `medium`
  in the catalog from 1.3, with rationale.
- `pipeline_provenance(key)` → full upstream dependency tree for a
  row.
- `diff_keys(good, bad)` → returns the differentiating column(s)
  for "why did populate fail on 5 but not 47"-style queries.

**Deliverables (skill side):**

- `skills/spyglass/references/introspection_api.md` — API tour +
  worked examples.
- Router row.
- 3 evals combining introspection + reasoning.

### 2.3 Cross-validation: Phase 1 evals now run end-to-end

Cases like "ripple rates across rats during novel-environment task"
or "safe to re-run populate on these 5 sessions?" were logged in
Phase 0 as "gated on DB access". With 2.1 + 2.2 shipped, they should
pass. Rerun the harness; the Phase 2 benchmark delta is the headline
result for any write-up or demo.

### Phase 2 acceptance

- [ ] `spyglass-mcp` published; installable alongside the skill.
- [ ] `spyglass-introspect` installable via pip.
- [ ] Phase 0 "DB-gated" evals now pass (target ≥ 80 % pass rate).
- [ ] Zero destructive-action regressions in eval suite (the
      read-only guardrail holds under adversarial prompts).

**Decision point before starting Phase 2:** run the graph tools for 4–6 weeks
in real interactions. Start MCP/introspection work only if users or evals show
one of these concrete blockers: subprocess latency dominates, agents need
multi-query stateful sessions, notebook users need the same primitives without
shelling out, or cross-dataset health tooling needs a package API rather than
a CLI.

## Phase 3 — Monitoring and meta-analysis (quarter+)

This is where the research aims get most ambitious. Most of the work
lives *outside* the skill — statistical infrastructure, dashboards,
longitudinal stores. The skill contributes correctness (query
authoring, metric interpretation, provenance tracking) and
guardrails (not confusing anomaly flags with errors; not
over-claiming effect sizes).

### 3.1 Aim 2 — anomaly detection & lab health

Separate repo `spyglass-health`. Depends on 2.1/2.2.

- Baseline-vs-observed anomaly detection per modality (position
  tracking dropout, sorter quality drift, decoding confidence).
- Lab-level dashboard (Streamlit or equivalent) rendering the
  ontology-tagged metrics over time.
- Non-destructive flags written to a dedicated DataJoint schema
  (never modifies original analyses).

**Skill additions (small):**

- `references/data_health_interpretation.md` — how to read the
  flags, when to escalate, when to ignore.

### 3.2 Aim 3 — cross-dataset meta-analysis (reach)

Separate repo `spyglass-meta`. Depends on everything prior.

- Query templates from 1.2 codified as callable functions.
- Pattern-ranking layer (effect size + consistency across
  datasets + provenance links).
- FigURL integration for every surfaced pattern.

**Skill additions:**

- `references/meta_analysis_patterns.md` — ties together the query
  recipes, introspection APIs, and the ranking functions.

### Phase 3 acceptance

Deferred — define once Phase 2 is shipped and stable.

## Out of scope for this roadmap

- Write access via MCP/introspection. The `SKILL.md` core directive
  "NEVER delete or drop without explicit confirmation" extends
  naturally to "no programmatic writes". If we ever relax this, it
  needs its own plan with its own guardrails.
- A bespoke chat UI. Claude Code / Codex CLI / Gemini CLI already
  provide the surface; we don't need to build another.
- Replacing the Spyglass tutorials. The skill *routes to* notebooks;
  it doesn't supplant them.

## Cross-cutting concerns

### Size-budget discipline

| File                                | Soft cap | Hard cap |
| ----------------------------------- | -------: | -------: |
| SKILL.md                            |  word-cap (validator) | — |
| Each `references/*.md`              |     500  |     700  |
| Per-H2 subsection in a reference    |     150  |       — |

If a phase tempts us to exceed these, split — see
`populate_all_common_debugging.md` as precedent.

### Validator evolution

Each new structured artifact needs a corresponding check:

- YAML catalog entries → schema validation + source-citation
  resolution (like existing `file.py:line` check).
- MCP tool descriptions referenced in `mcp_query_patterns.md` →
  cross-check against the MCP server's advertised tool list (once
  it exists; add to `scripts/validate_all.sh` as an optional
  check gated on the server being installed, mirroring the
  "optional import harness" pattern).
- Class registry extension (add each new Spyglass class touched by
  new evals/references to `KNOWN_CLASSES` in `validate_skill.py`
  — noted in `CLAUDE.md`).

### Eval discipline

- Every new capability: RED eval first (failing or mediocre),
  land the change, re-run, commit the benchmark delta.
- Regression fixtures in `tests/test_validator_regressions.py`
  before tightening any validator rule (pattern described in
  `CLAUDE.md`).
- Trigger eval set grows with every major scope change — re-run
  description optimization loop.

### Packaging & install surface

- Skill ships as today (copy `skills/spyglass/` into the host's
  skills directory).
- `spyglass-mcp` and `spyglass-introspect` ship as pip-installable
  packages with their own CI. Document install in the skill's
  README ("Optional companions") rather than bundling — keeps the
  skill zero-dependency for users who only want the guidance layer.

## Phase 0 baseline table (to fill in after Phase 0 runs)

| Eval name                           | Today (baseline) | Skill-only (Phase 1) | +MCP (Phase 2) |
| ----------------------------------- | ---------------: | -------------------: | -------------: |
| explain-filter-name                 |              TBD |                  TBD |            TBD |
| cross-session-metric-query          |              TBD |                  TBD |            TBD |
| boilerplate-dlc-selection           |              TBD |                  TBD |            TBD |
| context-aware-repopulate-safety     |              TBD |                  TBD |            TBD |
| natural-language-ripple-rates       |              TBD |                  TBD |            TBD |
| flag-position-instability           |              TBD |                  TBD |            TBD |

## Risks and mitigations

- **Scope creep into infra.** Keep adjacent packages out of this
  repo; review boundary at every Phase 2 PR.
- **Skill bloat from catalog YAML.** `catalog/` is data, not prose;
  validator gates content, but file count could grow. Organize by
  pipeline (one YAML per pipeline) rather than one giant file.
- **MCP + live DB = security surface.** Read-only creds + tool-level
  enforcement + CI testing of the "no writes" guarantee. Treat any
  regression as a blocker, not a warning.
- **Description drift as scope grows.** Trigger eval loop must be
  re-run at every phase boundary, not just at v1.
- **Grant-timeline coupling.** Aims 2/3 are long-horizon; users should
  feel immediate wins from Phase 1 regardless of whether Phase 2/3
  ever ship. Every phase must stand alone.

## Immediate next step

Agree on the Phase 0 proof-carrying eval cases + expected-output sketches,
then run the baseline. Phase 1.0 (graph-tool integration and evidence habits)
is the natural kickoff because it hardens the capabilities already shipped and
prevents the next round of plans from duplicating them.
