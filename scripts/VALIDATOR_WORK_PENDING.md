# Pending validator work — session handoff

**Delete this file when the work below is complete.** It exists only to
hand off mid-stream validator work between Claude Code sessions. The
previous session landed 4 of 7 planned checks (#1–#4); 3 remain (#5–#7).

## How to use this doc

1. Read this doc top to bottom.
2. Read `scripts/validate_skill.py` (the target of all changes).
3. Run the validator once to confirm you're starting from a green baseline
   (see "Current state" below for the expected output).
4. Pick up at check #5. Commit per check. Request code-review after each of
   #5, #6, and #7 individually (not bundled — #6 is the hardest and #7
   lives in a separate file).

## Current state

```
git log --oneline -5 spyglass/scripts/validate_skill.py
01c30ea Validator: check cited lines contain cited identifiers (content check)
91e011d Validator: check link-landing content overlap for internal md links
0206da1 spyglass evals: ... (this one folded check #2's per-section budgets
                              into a misleading commit message during amend;
                              the check_section_budgets function IS in this
                              commit's diff despite the label)
1928034 Validator: warn on PR-number citations in prose
8fbd675 Audit Spyglass skill references against live source and trim bloat
```

Validator produces **1449 passed / 17 warnings / 0 failed** on a clean run.
The 17 warnings are pre-existing signal, not work-to-do:

- 7 PR-number citations (`common_mistakes.md`, `ingestion.md` ×2,
  `position_pipeline.md` ×2, `setup_troubleshooting.md`, `spikesorting_pipeline.md`).
- 5 section-budget hits (`spikesorting_pipeline.md` at 508 lines; H2
  subsections in `datajoint_api.md`, `merge_and_mixin_methods.md`,
  `runtime_debugging.md`, `setup_config.md`).
- 5 citation-content mismatches (some genuinely stale, some prose that
  cites a flow-through line where the identifier is passed via `**kwargs`).

**Do not spend effort eliminating these warnings** — they're intentional
output from the new checks and a reviewer already vetted them as real signal.
They'll be addressed in a separate prose-cleanup pass, not here.

Regression fixtures: `tests/test_validator_regressions.py` passes 29/29.
This suite is standalone (not pytest-discoverable — run it as
`python3 tests/test_validator_regressions.py --spyglass-src PATH`).

## What's landed (for context)

The existing 18-check pipeline now runs:

| # | Check | Added |
|---|---|---|
| 1–14 | Original AST/schema/link/citation checks | pre-existing |
| 15 | Ban PR-number citations in prose | this session |
| 16 | Section + file size budgets | this session |
| 17 | Link-landing content overlap | this session |
| 18 | Citation identifier content check | this session |

Each new check is defined *above* the main pipeline; each is wired in
via a `print("[N/18] ...")` + function call block in `main()`. The
pattern is:

```python
print("[N/18] Short description...")
check_foo(...)
```

When you add check #5, bump the total to `/19`, add the line, and use
`sed -i '' 's|/18]|/19]|g'` to renumber existing prints.

## Pending work — checks #5, #6, #7

### Check #5: duplication detector (~80 lines, simple)

**What it detects:** near-identical code blocks (≥5 lines) appearing in
2+ reference files. Catches the "bloat via accumulation" failure mode
where similar examples leak into multiple references during per-PR
review.

**Algorithm:**
1. Extract every ````python` block from every `.md` file.
2. Normalize each block (strip leading/trailing whitespace per line;
   skip lines that are pure `from`/`import` statements — too commonly
   shared to flag).
3. For every 5-line rolling window in each block, hash the tuple of
   normalized lines.
4. Group hashes across files. If any hash appears in 2+ files, warn.
5. Output: file1:line — file2:line — first 3 lines of the duplicated block.

**Ignores:** import lines (too commonly shared), blocks < 5 non-import
lines, within-file repetition (we don't care about one file repeating
itself here).

**Expected fallout on current corpus:** unknown; most duplication was
cut during the Apr 21 audit, so probably 0–3 hits.

**Commit boundary:** one commit, title "Validator: detect duplicated
code blocks across references".

### Check #6: selection-table key-shape check (~200 lines, hardest)

**What it detects:** `T.insert1({...})`, `T.populate({...})`,
`T.insert([{...}, ...])` calls where the dict literal contains keys that
aren't in table `T`'s primary key or non-PK fields. This would have
caught the `linearization_pipeline.md` bug from Apr 21 (example used
`merge_id` instead of the projected `pos_merge_id`; also included a
nonexistent `interval_list_name` field).

**Algorithm:**
1. AST-walk each python code block; find calls matching the shape above
   where the receiver is a known class (reuse existing `resolve_receiver`
   and `KNOWN_CLASSES` in the validator).
2. For each such call, parse the table's `definition` string from source
   (there's already a helper `_parse_dj_definition` at ~line 682 in
   validate_skill.py — extend/reuse).
3. Resolve the PK + non-PK fields, including:
   - `-> ForeignTable` → recursively resolve ForeignTable's PK.
   - `-> ForeignTable.proj(new='old')` → substitute `new` for `old` in
     the resulting field set. **This is critical** — the linearization
     bug was about this specifically.
   - `attr = default` → treat `attr` as the field name.
   - Inline comments stripped.
4. Extract dict keys from the call's first positional arg. Skip if
   `**spread` is present (we can't verify — fail-open).
5. Warn when a dict key is not in `pk ∪ non_pk ∪ projected_renames`.

**Fail-open on parser limitations** (confirmed in Apr 21 plan): if our
DataJoint definition parser can't fully parse a `definition` string,
skip the check for that class rather than emit a false positive.

**Regression fixtures (per Apr 21 instruction):** the user explicitly
asked to add fixtures for this check. Add to
`tests/test_validator_regressions.py`:
- `fixture_insert1_wrong_pk_field`: a synthetic md with a block doing
  `LinearizationSelection.insert1({"merge_id": ..., "track_graph_name":
  "x", "linearization_param_name": "y"})` (uses unprojected `merge_id`
  instead of `pos_merge_id`). Validator should emit a warn/fail.
- `fixture_insert1_extraneous_field`: same but with an
  `"interval_list_name": "..."` added; field isn't in the schema.
  Validator should emit a warn/fail.
- `fixture_insert1_proj_renamed_ok`: a block that correctly uses
  `pos_merge_id`. Validator should NOT emit a warn.
- `fixture_insert1_spread_kwargs`: a block using
  `LinearizationSelection.insert1({**something, ...})`. Validator
  should skip (can't verify).
- `fixture_insert1_unknown_class`: a block calling `.insert1()` on a
  class not in `KNOWN_CLASSES`. Validator should skip.

**Expected fallout on current corpus:** low — the Apr 21 audit
corrected the known bad examples. 0–2 hits possible.

**Commit boundary:** one commit for the check + fixtures. Code-review
is **mandatory** per the Apr 21 plan — this is the one check most
likely to have parser bugs.

**Title:** "Validator: check DataJoint insert/populate key shape"

### Check #7: runnable-example import harness (~100 lines, separate file)

**What it detects:** code blocks that fail at import time — missing
classes, wrong module paths, etc. Runs as a standalone script so it
doesn't gate the main validator on spyglass being installed.

**Algorithm:**
1. New file: `tests/test_runnable_imports.py`.
2. For each .md file, extract every ````python` block.
3. Parse the block's AST, find every `ImportFrom` / `Import` node.
4. For each, attempt resolution via `importlib.util.find_spec(module)`.
5. For `from X import Y`, also check that `Y` exists on `X` (via
   `getattr` on the imported module). Skip if the module can't be
   imported (spyglass may not be in the test env).
6. Report: file:line + unresolved symbol, or "skipped — module not
   installed".

**Not** wired into `validate_skill.py`. Runs as:
```
python3 spyglass/tests/test_runnable_imports.py --spyglass-src PATH
```

Same argparse interface as `test_validator_regressions.py`.

**Expected fallout:** unknown. Some imports assume lab-configured
environment (DLC, moseq extras). Graceful-skip should distinguish
"import unresolvable" from "class actually missing." The former is
environment noise; the latter is a real bug.

**Commit boundary:** one commit, title
"Tests: runnable-example import harness".

## Design decisions baked in this session

Don't revisit these unless there's a reason:

- **Warnings, not failures**, for everything in #15–#18. Hard failures
  block the validator; warnings let the tree stay green while surfacing
  signal. Check #6 should follow the same convention unless a case is
  *certainly* wrong.
- **Stopword list** for `_LINK_TEXT_STOPWORDS` is hardcoded in the
  validator (not a config). Expand if needed; don't externalize.
- **±8 line window** for citation-content check. Function bodies beyond
  that tolerance fall through to the enclosing-def/class scan (±120
  lines). These two thresholds are tuned against the current corpus;
  touching them risks false-positive regression.
- **File size budgets**: 500 soft / 700 hard / 150 per-H2. Calibrated
  to flag pre-existing bloat (5 hits) without false positives.
- **Bare-filename citations** (`ripple.py:35`, not `src/spyglass/...`)
  are resolved via a built-at-startup `{basename: [paths]}` map.
  Ambiguous (multiple matches) → skip. Missing → skip.
- **Renumber step counters with sed**: the validator's
  `print("[N/18]")` lines are kept in sync by
  `sed -i '' 's|/18]|/19]|g' validate_skill.py`. Not elegant; works.

## Gotchas from this session

- **Amend/rebase may silently fold commits.** Check #2's commit was
  labeled as an eval-tightening commit after the user amended. The
  content is still in-tree; only the message is wrong. Don't amend
  unrelated commits mid-stream.
- **Trailing `()` in backticked identifiers.** `_find_preceding_identifier`
  strips them; match against the source name without parens.
- **Dotted identifiers** (`Foo.bar`) match as either the full string or
  the last segment. Both are tried via `_identifier_candidates`.
- **Indent-cap walk for enclosing scope.** The first attempt only
  looked at the first `def`/`class` at indent ≤ cited. That misses
  cases where a method at indent 4 doesn't match but the outer class
  at indent 0 does. Fixed by tracking a falling `indent_cap` through
  the scan. If you touch `_citation_matches_identifier`, preserve this
  behavior.

## Review cadence

- Commit one check per commit.
- Request code-review individually after #5, #6, and #7.
- #6 is **mandatory review** per Apr 21 plan.
- No bundled review this time (#1–#3 bundled; #4 solo; #5–#7 solo).

## Post-work cleanup

Once #5, #6, #7 are in and reviewed:

1. Delete this file: `rm spyglass/scripts/VALIDATOR_WORK_PENDING.md`.
2. Run the validator one more time; expected 17–20ish warnings, 0
   failures (depending on duplication/key-shape findings).
3. A final prose-cleanup commit may be needed to address the 17
   pre-existing warnings. That's a separate task, not part of this
   block.
