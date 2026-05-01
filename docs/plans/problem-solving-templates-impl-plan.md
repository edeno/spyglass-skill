# Problem-solving templates implementation plan

**Status:** Partially executed / design reference. PR #26 implemented several
templates and routing changes from this plan; use this file for the durable
principle that templates belong in the reference that owns the problem shape,
not in a catch-all template file or the root `SKILL.md`.

This plan adds reusable Spyglass reasoning templates for advanced agent
behavior without turning `SKILL.md` into a tutorial. The templates should make
agents choose the right evidence path, produce complete answers, and avoid
high-confidence schema hallucinations.

## Goals

- Encode the recurring reasoning shapes exposed by the round-C eval sweep:
  relationship/path questions, field ownership, populate no-ops, cascade
  recovery, custom authoring, destructive operations, blob-parameter
  inspection, and static-graph-vs-runtime-use.
- Keep `SKILL.md` as the router. Add only short pointers there if needed.
- Put each template where the agent already lands for that problem type.
- Tie each template to a verification hook: `code_graph.py`, `db_graph.py`,
  `.heading`, source reads, `descendants()` / `ancestors()`, or targeted table
  queries.
- Keep templates short and operational: trigger, steps, answer shape, and
  common failure mode.

## Non-goals

- Do not add a broad `templates.md` catch-all unless the existing references
  cannot support the routing. A new catch-all file would add one more routing
  decision and risks becoming another reference the agent opens without a
  concrete task.
- Do not duplicate full pipeline details inside templates. Link to the owning
  pipeline reference when a concrete table sequence is needed.
- Do not add eval-specific examples. Use evals only as evidence for the
  recurring failure mode.
- Do not expand low-yield references just because they were opened often.
  The round-C pattern was usually synthesis failure after enough context, not
  failure to find more prose.

## Template shape

Each template should follow this compact form:

```markdown
### <Template name>

Use when: <prompt shapes / table names / failure symptoms>.

Steps:
1. <first evidence action>
2. <second evidence action>
3. <answer construction rule>

Answer must include:
- <minimum claims or caveats>
- <verification hook>

Common failure mode: <what the model otherwise gets wrong>.
```

Keep each template to roughly 120-220 words unless it is replacing a larger
existing section.

## Phase 1 — Add / refine the core cross-cutting templates

### 1. Relationship / join-path template

**File**: `skills/spyglass/references/feedback_loops.md`

**Anchor**: existing tool-routing section.

**Add**: a short template for questions like "how do I get from table A to
table B?", brain-region lookup, electrode/device/session joins, and "which
table connects these?"

**Required behavior**:

- Identify source table and target concept.
- Run or recommend `code_graph.py path --to <Source> <Target>` for static
  source/schema paths.
- If the question is about live rows, switch to `db_graph.py` or table queries.
- Name which table owns each restriction field before showing the query.
- State non-FK name-match caveats when present.

**Why**: targets missed/underused graph behavior in relationship questions
without adding a brain-region-specific example.

### 2. Static graph vs runtime use template

**File**: `skills/spyglass/references/feedback_loops.md`

**Anchor**: existing static-graph-vs-runtime principle.

**Add/refine**: a template that separates declared FK dependencies from data
read inside `make()`.

**Required behavior**:

- Use static graph tools for declared dependencies.
- Read `make()` source for runtime fetches, third-party calls, and blob-key
  consumption.
- Explicitly label inputs as "declared dependency", "runtime-used input", or
  "implementation detail".

**Why**: covers LFP/Raw, decoding plumbing, parameter consumption, and source
vs runtime disagreements.

### 3. Field-ownership-before-query template

**File**: `skills/spyglass/references/datajoint_api.md`

**Anchor**: existing `Field Ownership` section.

**Add/refine**: make the existing rule template-shaped.

**Required behavior**:

- For every restriction attribute, name the declaring table.
- Distinguish declared FK, inherited primary-key field, secondary attribute,
  and name-match convention.
- Treat reused names (`nwb_file_name`, `interval_list_name`, `merge_id`,
  `electrode_id`, `camera_name`) as trap patterns.
- Verify with source, `.heading`, `code_graph.py describe`, or `db_graph.py`
  before claiming a query works.

**Why**: directly supports correct queries for Spyglass schemas where the same
field names recur across tables.

## Phase 2 — Add task-specific operational templates

### 4. Populate-did-nothing template

**File**: `skills/spyglass/references/runtime_debugging.md`

**Anchor**: `key_source` / populate no-work debugging section.

**Add**: a template for "populate ran but inserted nothing", "no candidate
keys", "key_source empty", and "this one key does not populate".

**Required behavior**:

- Restrict `key_source` by the user's key.
- Compare candidate keys to already-populated rows under the same restriction.
- Check required selection and parameter rows.
- Walk upstream to the first empty prerequisite.
- Distinguish "no work to do" from `make()` failure.

**Why**: makes `key_source` useful as a debugging concept rather than a literal
token the model happens to mention.

### 5. Counterfactual / recovery / recompute cascade template

**File**: `skills/spyglass/references/destructive_operations.md`

**Anchor**: existing cascade template section, if present; otherwise add near
the inspect-before-destroy patterns.

**Add/refine**: the four-slot cascade answer shape.

**Required behavior**:

- Name the new row / param name / merge id that represents the corrected
  computation; do not mutate old provenance rows in place.
- Name downstream branches that must be re-selected or re-populated.
- Explicitly enumerate unaffected upstream and sibling branches.
- Verify with `Table.descendants()` / `Table.ancestors()` or graph tooling.

**Cross-links**: ensure the relevant pipeline references point to this section
for parameter swaps, recovery, and "what changes downstream?" questions.

**Why**: addresses the strongest recurring synthesis gap: agents describe the
changed branch but omit unaffected branches and verification.

### 6. Destructive-operation resistance template

**File**: `skills/spyglass/references/destructive_operations.md`

**Anchor**: top policy / cautious-delete section.

**Add/refine**: an adversarial-framing template for prompts that ask to skip,
force, rollback, or silence safety checks.

**Required behavior**:

- Treat "just", "quick", "I know what I'm doing", "test data", and similar
  wording as caution triggers.
- Name the scope ambiguity before recommending an action.
- Require an explicit key/restriction and an inspect/count step.
- Prefer `cautious_delete` / merge-aware methods where appropriate.
- Name the forbidden shortcut only to reject or constrain it.

**Why**: destructive-operation evals showed that policy prose alone is not
enough; the agent needs an answer template that resists the user's framing.

### 7. Blob-bearing parameter-table inspection template

**File**: `skills/spyglass/references/common_mistakes.md`

**Anchor**: parameter-table / `.describe()` footgun section, or add a short
new section if no suitable anchor exists.

**Add**: a template for parameter tables whose meaningful knobs live inside a
`params` blob.

**Required behavior**:

- Do not use `.describe()` / `.heading` as the primary way to discover
  blob-internal keys.
- Prefer `(Table & key).fetch1("params")` when a row exists.
- If no DB row exists, inspect `default_params`, `insert_default()`, builder
  helpers, and the consuming `make()` source.
- Separate table columns from blob keys and from third-party kwargs.

**Why**: this pattern applies across `TrodesPosParams`, `RippleParameters`,
`DecodingParameters`, waveform-feature params, and metric params.

### 8. Custom pipeline authoring template

**File**: `skills/spyglass/references/custom_pipeline_authoring.md`

**Anchor**: near the five-step decision tree.

**Add/refine**: a single answer template for authoring new tables or extending
existing pipelines.

**Required behavior**:

- Decide consumer usage vs authoring first.
- Choose upstream FK by semantic input, not the broadest reachable table.
- Choose tier: lookup/manual/selection/computed/merge.
- For "add a column to a core table", use a side-table in a user/lab schema;
  upstream PR plus migration is the only legitimate core-schema edit path.
- For heavy arrays/results, use `AnalysisNwbfile` object storage rather than
  large `longblob` columns.
- Mention group tables when the user needs reusable named sets across rows.

**Why**: turns authoring guidance into a routing/policy decision aid rather
than only an implementation skeleton.

## Phase 3 — Wire templates into `SKILL.md` without adding prose bulk

**File**: `skills/spyglass/SKILL.md`

Only edit if the Phase 1-2 templates are not discoverable from current routing.
Prefer small link-label changes over new sections.

Possible edits:

- In the Reference Routing table, make the `feedback_loops.md` row say it owns
  relationship/path templates and static-vs-runtime checks.
- Make the `runtime_debugging.md` row explicitly mention the populate no-work
  template.
- Make the `destructive_operations.md` row mention cascade/recovery templates.
- Make the `custom_pipeline_authoring.md` row mention authoring decision
  templates.

Avoid adding the templates themselves to `SKILL.md`.

## Phase 4 — Validation and narrow eval check

Run after each logical commit:

```bash
./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
ruff check .
```

Then run or manually inspect the narrow eval set that exercises the templates:

| Template | Candidate evals |
| --- | --- |
| Relationship / join-path | 028, 029, 089, 107, 108 |
| Field ownership | 089, 105 |
| Static graph vs runtime use | 072, 100, 118 |
| Populate did nothing | 099 |
| Cascade recovery | 085, 087, 088, 113, 118 |
| Destructive resistance | 024, 041, 088, 113 |
| Blob parameter inspection | 060 |
| Custom authoring | 008, 083, 112, 114 |

Success criteria:

- Agents cite the correct verification hook for each prompt shape.
- Agents do not open more references as a substitute for synthesis.
- Answers include all required template slots, especially unaffected branches
  and field ownership.
- Existing strong areas do not regress: merge-key hygiene, hallucination
  resistance, setup/install, and ingestion.

## Recommended commit structure

1. `references: add graph and field-ownership templates`
   - `feedback_loops.md`
   - `datajoint_api.md`

2. `references: add runtime and cascade templates`
   - `runtime_debugging.md`
   - `destructive_operations.md`
   - pipeline cross-links if needed

3. `references: add parameter and authoring templates`
   - `common_mistakes.md`
   - `custom_pipeline_authoring.md`

4. `skill: route to problem-solving templates`
   - `SKILL.md` only if needed

Each commit should pass validation before the next.

## Review checklist

- Every template has a trigger, steps, answer requirements, and common failure
  mode.
- Every template names the evidence hook that makes it reliable.
- No template encodes a single eval's answer.
- No large workflow is duplicated from a pipeline reference.
- `SKILL.md` remains a router and does not grow materially.
- Internal links resolve and validator warnings do not increase.
