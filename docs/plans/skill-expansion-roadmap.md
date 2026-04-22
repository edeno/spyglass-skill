# Spyglass skill — expansion roadmap

**Date:** 2026-04-22
**Author drafted by:** Claude, via skill-creator best practices
**Status:** Draft for review

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

Gap analysis (previous turn) established that most Aim 1 text deliverables
are ~50 % shipped, the remaining 50 % and nearly all of Aim 2/3 depend on
**live database access** and **introspection APIs** that don't exist yet.
This roadmap sequences the work so the skill's *own* surface stays lean
while unlocking those downstream capabilities.

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

Before changing anything, lock in **where we are today** so the lift of
each subsequent phase is measurable.

### Work items

- **0.1** Add 6–8 new eval cases in `skills/spyglass/evals/evals.json`
  targeting aim-relevant behavior. Suggested cases:
  - "Explain `filter_name=lfp_600Hz` and when I'd pick it" (param
    literacy — Aim 1).
  - "I have 120 sessions; which have spike-sorting quality metrics
    below our lab's usual range on `nn_isolation`?" (metric
    interpretation + cross-session — Aims 2 + 3).
  - "Write the full selection-insert for running `DLCPosV1` on
    session X with params Y" (boilerplate generation — Aim 1).
  - "Given my current DB state, is it safe to re-run `populate` on
    these 5 sessions?" (context-aware guidance — Aim 1, expected to
    fail today because there's no DB access).
  - "Compare ripple rates across rats during novel-environment
    task" (natural-language query — Aim 1 flagship).
  - "Flag sessions where position tracking looked unstable" (Aim 2).
- **0.2** Run the existing skill-creator eval harness against these
  cases (with-skill vs. baseline-no-skill). Save under
  `spyglass-workspace/iteration-0-baseline/`.
- **0.3** Publish the baseline numbers in this file (fill in Phase 0
  table at the end) so Phase 1+ can claim deltas honestly.

### Acceptance criteria

- [ ] 6+ new evals merged.
- [ ] Baseline benchmark.json committed (or linked from workspace).
- [ ] Each eval classified as "text-achievable" or "gated on DB
      access" — tells us which phase it should move in.

## Phase 1 — Skill-internal wins (2–3 weeks)

Highest-leverage, lowest-cost additions. Pure content + validator work;
no new dependencies.

### 1.1 Quality-metrics ontology reference

**Why:** Aim 2.1 asks for a formal mapping metric ↔ modality ↔ failure
mode. Today the skill only lists metric *names* in
`spikesorting_pipeline.md`. A maintained ontology is a natural
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

**Deliverables:**

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

Biggest single unlock identified in the gap analysis: **live read-only
DB access**. This is *not* skill content; it's a sibling package. The
skill learns how to invoke it.

### 2.1 `spyglass-mcp` — read-only DataJoint MCP server

**Why:** Covers Aim 1.2 (programmatic introspection), enables Aim 1.3
context-aware guidance, and is the prerequisite for Aims 2/3 analyses
to run against real data. MCP is the right shape because Claude Code
/ Codex CLI / Gemini CLI all speak it, matching the skill's
multi-harness story in the README.

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

**Decision point before starting Phase 2:** run Phase 1 for 4–6 weeks
in the wild. If onboarding friction demonstrably drops and users
start asking for "but can it query my DB too?", Phase 2 is validated.
If not, revisit scope.

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

Agree on Phase 0 eval cases + their expected-output sketches, then
run the baseline. Phase 1.1 (quality-metrics ontology) is a natural
kickoff because it's fully skill-internal, has obvious structure,
and touches the smallest surface area while still being visible to
users.
