# Spyglass skill evals

Capability evals for the Spyglass skill. Each eval is a realistic user prompt paired with structured pass/fail criteria. Runs are scored three ways: grep-scorable required/forbidden substrings (fast, deterministic), and behavioral checks (LLM- or human-graded, single-sentence pass/fail).

## File

- `evals.json` — the entire suite. Single JSON object. No per-eval files yet (`files: []` on every entry).

## Top-level keys

| Key | Type | Purpose |
| --- | --- | --- |
| `skill_name` | string | Identifies the skill under test (`spyglass`). |
| `notes` | string | Suite-wide context: the three classification axes, the anonymization convention for lab/host/user identifiers (`db.example.test`, `testuser`, `otheruser`, `example lab`, `example institution`), and how assertions are scored. Kept here rather than only in a README so it travels with the JSON if the suite is redistributed. |
| `assertion_schema` | object | Self-describing summary of how to interpret each assertion type. Lets a new grader understand the scoring without reading this README. |
| `evals` | array | The eval entries themselves. |

## Per-eval keys

Every entry in `evals` has exactly these keys:

| Key | Type | Purpose |
| --- | --- | --- |
| `id` | int | Unique, stable identifier. New evals get the next integer; IDs are never reused or renumbered so run logs stay comparable across suite edits. |
| `eval_name` | string | Short kebab-case slug used in run directories and benchmark output. Should describe what the eval tests, not what tier it's in. |
| `stage` | string | Which phase of a Spyglass workflow the prompt is about. Orthogonal to tier — used when slicing results by topic area. See [Stages](#stages). |
| `tier` | string | What *kind* of capability is being tested (skill activation, atomic lookup, multi-step reasoning, pressure on guardrails, etc.). See [Tiers](#tiers). |
| `difficulty` | string | What kind of cognitive load the eval imposes on the answer side. One of `easy` / `medium` / `hard`. See [Difficulty](#difficulty). |
| `prompt` | string | The literal user message the grader sends. Written in realistic voice — casual, frustrated, or concise, with concrete file paths, session IDs, and error strings where that's how a real user would phrase it. |
| `expected_output` | string | Prose description of the ideal response. Not a literal string to match — a human-readable reference that captures what the answer should route to, which commands/APIs it should mention, and what it must not recommend. Used by the LLM grader as the ground-truth description when evaluating behavioral checks. |
| `assertions` | object | Three-bucket scoring criteria (see below). **Authoring surface — edit this.** |
| `expectations` | array | **Auto-generated from `assertions`.** Flat list of declarative pass/fail statements in skill-creator's stock `expectations: [str]` format. Do not hand-edit. Regenerate with `scripts/flatten_expectations.py` after any change to `assertions`. |
| `files` | array | Optional attachments shipped with the prompt (not currently used). |

## Assertions

Three buckets, designed to catch different failure modes:

| Bucket | Scoring | What it catches | What to put here |
| --- | --- | --- | --- |
| `required_substrings` | Grep (case-insensitive). Every entry must appear at least once. | Missing the specific API, flag, or file the user needs. | Unique, discriminating strings — API names (`insert_sessions`), flags (`raise_err=True`), file paths (`setup_troubleshooting.md`), diagnostic commands (`SHOW GRANTS`). |
| `forbidden_substrings` | Grep (case-insensitive). No entry may appear. | Hallucinations, unsafe shortcuts, outdated advice, wrong API. | The specific bad answer the eval is guarding against (`skip_duplicates=True`, `chmod -R 777`, `super_delete()`). |
| `behavioral_checks` | LLM grader or human reviewer. One pass/fail per check. | Reasoning steps a string match can't verify — order of operations, root-cause identification, "asks before destructive action." | Single-sentence, objectively checkable statements: "Uses the raw filename (no trailing underscore)", "Runs SHOW GRANTS before assuming filesystem." |

### Substring hygiene

A substring assertion is only useful when it discriminates a good answer from a bad one. Three traps:

1. **Prompt echo.** If the prompt contains `DLCPosV1`, then `required_substrings: ["DLCPosV1"]` passes on any response that parrots the prompt. Pick a string that appears in the *diagnosis*, not the question — e.g. `"(DLCPosV1 & key).fetch1_dataframe"`.
2. **Bare words.** `required_substrings: ["restart"]` matches "no need to restart" just as well as "restart the kernel." Pair with a disambiguating word (`kernel` + `restart`) or use a phrase.
3. **Forbidden-fires-on-denial.** Substring grading can't detect negation. A `forbidden_substrings: ["is Computed"]` fires false-positive on a correct answer that says "LFPV1 is Computed" in passing reference. Same for `forbidden_substrings: ["arbitrary"]` — the skill's own Nyquist note uses "arbitrary" naturally, and a correct answer paraphrasing it would false-fail.

If a check can't be expressed without one of these traps, move it to `behavioral_checks`.

**Forbidden-substring rule.** Forbidden substrings must be **uniquely-wrong identifiers or quoted bad commands** — strings a correct answer would never naturally contain, even in a denial. Examples that pass the rule:

- Hallucinated class names (`LFPBandOutput`, `MuaEventsV1.merge_get_part`)
- Specific bad commands (`super_delete()`, `chmod -R 777`, `skip_duplicates=True` on insert_sessions)
- Specific bad recommendations the wrong answer would commit to (`Yes, just delete the DataAcquisitionDevice`)

Examples that **fail** the rule (use behavioral checks instead):

- Conceptual claims (`is Computed`, `populate`, `merge`, `arbitrary`, `one electrode per group`)
- Words that appear naturally in correct denials (`use v0` would fire on "Don't use v0")

Test: "Could a correct answer contain this string in a denial like 'this is NOT X' or 'you do NOT call Y'?" If yes → behavioral check, not forbidden.

### Validator-enforced hygiene (two rules)

Two `validate_skill.py` checks mechanically surface the traps above so authors don't have to catch them by eye:

- **Bare-word / literal-format hygiene** (`check_eval_required_substring_hygiene`) — warns when a `required_substring` is a single lowercase English word (trap #2), wraps literal backticks (`` `Raw` `` forces one rendering), or ends with `(` (`SpikeSorting.populate(` locks the call form). Known Spyglass class names (`Electrode`, `Session`, `LFPV1`) are auto-exempted via the class registry since they're discriminating identifiers even when they look like bare words.
- **Required-vs-expected completeness** (`check_eval_required_substring_completeness`) — warns when `expected_output` names a Spyglass class that no `required_substring` contains. Catches the eval-72 pattern where the prose description enumerates tables but the grep-scorable assertion list omits them, leaving a grep-pass possible on answers that skip substantive upstreams.

### Silencing a warning (per-eval exempt lists)

Both rules are warn-level, not fail. When a warning is a false positive for an eval — e.g. a rare domain term that really is discriminating, or a class named in passing as a distractor — add the substring to a per-eval exempt list inside `assertions`:

```json
{
  "id": 58,
  "assertions": {
    "required_substrings": ["Nyquist", "downsample"],
    "required_substrings_exempt": ["Nyquist"],
    "expected_output_tables_exempt": [],
    ...
  }
}
```

- `required_substrings_exempt` silences the bare-word / literal-format check for the listed substrings.
- `expected_output_tables_exempt` silences the completeness check for the listed Spyglass class names.

**Each exempt entry is audit-worthy.** Every entry says "I looked at this warning and decided the substring is discriminating (or the mention is contextual) despite the heuristic." Use sparingly — prefer tightening the substring (`"Manual"` → `"Manual table"`) or moving the claim to a behavioral check.

#### Legitimate exempt categories (three buckets)

Independent audit of the post-cleanup state found `expected_output_tables_exempt` entries fall into three recurring patterns. If your exempt doesn't match one of these, the class probably belongs in `required_substrings` instead:

1. **Prose distractors / contrast tables.** The class is named to say what the answer is *not* or to list lookalikes the user should distinguish. Example: eval 52 exempts `CurationV1`, `DLCPosV1`, `LFPV1` etc. — the 5 merge masters are required; the V1-suffix lookalikes are prose "these look like merges but aren't" examples.
2. **Concept-word false-positives** on 3–4 letter class names matching ordinary English. Example: eval 54 exempts `Raw` because the match hit "Filter Raw Data" (a reference-file section title), not a reference to the `Raw` table. Eval 29 exempts `LFP` because "LFP stream" refers to the signal, not a class.
3. **Subject appearing in its own explanation.** Schema-introspection evals (74-77) ask for field-name-only answers; the expected_output mentions the target class to explain why (e.g., "Electrode's PK is..."), but a terse correct answer doesn't need to produce `Electrode` as a token.

`required_substrings_exempt` has two legitimate categories: rare domain terms that are discriminating in practice despite looking bare (`Nyquist`, `immobility`, `pynwb`, `spikeinterface`), and DJ-API literals where the specific form IS the test token (`len(`, `.aggr(`, `.proj(`, `set(`, `secondary`).

## Tiers

Tiers capture *what kind of capability* the eval tests. A single skill can be strong at atomic reads and weak at adversarial pushback — slicing by tier shows that.

| Tier | N | What it tests |
| --- | --- | --- |
| `baseline` | 7 | Skill activation + correct routing on canonical, happy-path questions (fresh install, first ingest, first LFP populate). If these fail, nothing else matters. |
| `atomic-read` | 8 | Single-table fetch by primary key or restricted scan. Tests that the skill can point to the right table and write the right `& key` restriction. |
| `merge-key-discovery` | 3 | Given a merge-output table and an upstream selector, resolve the specific `merge_id` or part-table entry. Merge tables are Spyglass's highest-friction abstraction. |
| `joins` | 9 | Compose across 2+ tables to answer a question no single table can. Tests relationship knowledge. |
| `adversarial` | 17 | Non-activation (the skill should NOT fire on unrelated questions), hallucination resistance (made-up table names), destructive-operation pushback (`cautious_delete` bypass requests). |
| `compound` | 4 | Multi-reference handoffs mirroring real session-length problems — the answer must draw on three or more reference files. |
| `post-ingest-validation` | 3 | After a fresh ingest "completed," verify what actually made it into the tables and catch silent skips (electrodes missing, PositionSource empty, DIOEvents absent). |
| `merge-table-gotchas` | 5 | Merge-table-specific failure modes beyond key discovery — insert-order violations, `cautious_delete` cascades, `_object_id` + `SpyglassMixin` requirements on custom merge parts. |
| `runtime-errors` | 10 | Real tracebacks from `populate()` / `make()` / `fetch1()` with the user's debugging context attached. Tests triage: which reference, which diagnostic, which fix. |
| `environment-triage` | 4 | Install-level failures (editable-install drift after `git pull`, conda env broken by a stray `pip install`, conda path isolation). |
| `config-troubleshooting` | 3 | Config-level failures (`dj.config` wiring, Kachery credentials, shared-install permission layers). |
| `table-classification` | 6 | Classify a table by DataJoint tier (Manual / Lookup / Computed / Imported / Part) and Spyglass role (selection / parameter / compute / output / merge). |
| `parameter-semantics` | 8 | Explain what a specific parameter controls and predict downstream effects of changing it. |
| `disambiguation` | 8 | Choose between two similar tables or workflow branches with explicit reasoning. Also covers under-specified prompts where correct behavior is to ask or narrow scope before answering. |
| `counterfactual` | 7 | "If X were different, which downstream entries would change." |
| `resource-selection` | 4 | Meta-test: which reference file should be opened first to answer a question. |
| `workflow-recovery` | 3 | Recover from partial success — `populate()` completed but rows are missing, a parameter row was edited in place, an insertion was rolled back mid-chain. Tests whether the skill narrows the safe-next-diagnostic rather than defaulting to broad reruns or destructive cleanup. |
| `workflow-position` | 3 | "I'm at point X in the pipeline; what populates next." |
| `dependency-tracing` | 6 | Abstract enumeration of the full upstream chain for a given output table. |
| `schema-introspection` | 7 | Direct fact about a table's schema (PK fields, direct dependency, part-table set). Grep-scorable, stable canonical answer. |
| `table-usage` | 5 | Given an already-populated row or selection table, choose the next safe table/API to call and avoid treating intermediate tables as final outputs. |

## Stages

Stages capture *which phase of a Spyglass workflow* the prompt lives in. Orthogonal to tier — an `adversarial` eval can live in any stage.

| Stage | N | Meaning |
| --- | --- | --- |
| `setup` | 7 | Install, env vars, DataJoint config, permissions. |
| `ingestion` | 4 | Converting + loading NWB files into Spyglass tables. |
| `pipeline-usage` | 44 | Using a pipeline end-to-end: insert params → populate → fetch. Largest slice by design — pipeline usage is the 80% case. |
| `runtime-debugging` | 21 | Triaging an error that already happened. |
| `common-mistakes` | 6 | Prompts that specifically test the patterns documented in `common_mistakes.md`. |
| `pipeline-authoring` | 7 | Writing a custom pipeline table (`SpyglassMixin`, `AnalysisNwbfile` FK, `_object_id` convention). |
| `framework-concepts` | 9 | DataJoint-layer concepts (blob vs external, `filepath@` stores) and schema-introspection (PK / dependency / part-table facts). |
| `non-activation` | 2 | Questions the skill should stay silent on (plain Python, unrelated neuro tooling). |
| `hallucination-resistance` | 11 | User cites a made-up API, field, dependency, or class name extrapolated from a naming pattern; correct answer is "that doesn't exist, here's the real one — and here's the verification primitive." |
| `destructive-operations` | 6 | User asks for `cautious_delete` bypass, `super_delete()`, manual DROP, or an under-specified delete — correct answer pushes back, scopes, or asks before acting. |
| `table-understanding` | 4 | Questions about what a table *is* (DataJoint tier, Spyglass role, what it stores, relationship to its merge wrapper). Cross-pipeline. |
| `parameter-understanding` | 9 | Questions about what a specific parameter *controls* and downstream consequences of changing it. Cross-pipeline. |

## Difficulty

Captures *how hard the eval is to answer*, independent of stage and tier. Used for slicing benchmarks within a single tier ("does the skill degrade on harder parameter-semantics evals?").

| Difficulty | N | What it tests |
| --- | --- | --- |
| `easy` | 35 | One-step lookup or single-fact recall. Atomic-read, schema-introspection, baseline activation, hallucination/non-activation. |
| `medium` | 62 | Two-step composition or one inference hop. Single-table debugging, merge-key discovery, parameter-semantics with locally documented effects. |
| `hard` | 33 | Multi-step reasoning, multi-reference handoff, ambiguity, or counterfactual reasoning. Compound, dependency-tracing, recovery-from-incomplete-state. |

Difficulty is judged on the *answering* side, not the question side. A short prompt can be hard ("trace upstream of `LFPBandV1`") and a long traceback prompt can be easy.

## Tier vs stage — why both?

A `runtime-errors` eval in stage `ingestion` tests a different failure mode than a `runtime-errors` eval in stage `pipeline-usage`, even though both are runtime errors. And a `baseline` eval in `setup` is different from a `baseline` in `ingestion`. Keeping both dimensions means benchmark cuts like "how does the skill handle runtime errors specifically in merge tables" stay one filter away.

## Adding a new eval

1. Pick the next unused `id`. Don't renumber existing IDs.
2. Pick a tier and stage from the tables above. If the situation doesn't fit any existing tier, add a new one — but check first whether the new situation is really a new *capability* or just a new *topic* (topic → stage, capability → tier).
3. Write the prompt in realistic user voice. Include the specific error string, file path, or session ID a real user would paste in.
4. Draft `expected_output` as a description, not a script. Name the reference file the answer should route to and the specific APIs / flags it should mention.
5. Start `assertions.required_substrings` with the one or two discriminating strings the right answer *must* contain. Add `forbidden_substrings` for the specific wrong answer you're guarding against. Put anything that needs reasoning (order, root-cause framing, "asks before destructive action") in `behavioral_checks`.
6. Sanity-check your substrings against [Substring hygiene](#substring-hygiene).
7. Run `python3 scripts/flatten_expectations.py` to regenerate the `expectations` field for the new eval.
8. `python3 -c 'import json; json.load(open("evals.json"))'` to confirm the JSON still parses.

## Running

This suite follows skill-creator's eval lifecycle (one `with_skill` run + one baseline per eval; outputs aggregate into a tier/stage benchmark) and is **drop-in compatible** with skill-creator's shipped `agents/grader.md` via the auto-generated `expectations` field. Two parallel representations coexist in `evals.json`:

- **`assertions`** (authoring surface): three buckets — `required_substrings`, `forbidden_substrings`, `behavioral_checks`. Grep-scorable substrings are deterministic and cheap to re-check across iterations; behavioral checks stay reserved for reasoning steps a grep can't verify. Edit this when adding or changing an eval.
- **`expectations`** (derived, skill-creator compat): a flat list of declarative pass/fail statements. Regenerated from `assertions` by `scripts/flatten_expectations.py`. Do not hand-edit.

### Keeping `expectations` in sync

```bash
# After any change to an eval's `assertions`:
python3 scripts/flatten_expectations.py

# Pre-commit / CI check — exits 1 if stale:
python3 scripts/flatten_expectations.py --check
```

The script is idempotent: running it on an in-sync file is a no-op. The `--check` flag is suitable as a pre-commit hook or CI gate so `expectations` can never drift from `assertions` in a merged commit.

### Gotcha: `assertions` vs skill-creator's `eval_metadata.assertions`

Skill-creator's workflow (`SKILL.md` Step 1) writes a per-run `eval_metadata.json` in the workspace whose `assertions` field is a **flat list of strings** — same shape as `expectations` in `evals.json`, just a different field name. Our `assertions` in `evals.json` is a **three-bucket object** (`required_substrings`, `forbidden_substrings`, `behavioral_checks`). Same field name, incompatible shape.

If you generate `eval_metadata.json` per skill-creator's workflow, copy this suite's **`expectations`** list into that file's `assertions` field — not our `assertions` object. Example:

```python
# eval_metadata.json generation (skill-creator workspace layout)
from json import dumps, load
e = next(x for x in load(open('evals.json'))['evals'] if x['id'] == 1)
dumps({
    'eval_id': e['id'],
    'eval_name': e['eval_name'],
    'prompt': e['prompt'],
    'assertions': e['expectations'],  # note: flat list, not our three-bucket object
})
```

### Other skill-creator interop notes

- **Extra fields** — `notes`, `assertion_schema` (top-level) and `eval_name`, `stage`, `tier`, `assertions` (per-eval) are not in skill-creator's published schema but are tolerated; none of its scripts schema-validate `evals.json`. `eval_name` is explicitly consumed by `aggregate_benchmark.py` and appears in `benchmark.json`.
- **Files field** — skill-creator expects `files: ["evals/files/sample1.pdf"]` relative to skill root. Ours are `[]`; add attachments under `evals/files/` if ever needed.
- **Trigger evals** — skill-creator's `scripts/run_eval.py` reads a *different* eval format (`{query, should_trigger}`) for skill-activation testing, not capability grading. Not this file.
