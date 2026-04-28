# Implementation plan — schema-fact validator (Option E: lint + verify)

**Date:** 2026-04-24
**Status:** **Not executing — audit found zero drift.** Kept as historical context + design reference for future revisit.
**Decision date:** 2026-04-24 (same session; see outcome block below).
**Scope:** Would add a `check_schema_facts` step to `skills/spyglass/scripts/validate_skill.py` that (1) lints catalog-style class entries in references for the presence of a structured PK declaration, and (2) verifies the structured declaration matches the actual class definition in Spyglass source.

This is **option E** from the design discussion: hybrid lint + verify. Closes the false-confidence gap of pure verify-only by enforcing that catalog entries opt into the checkable form.

**Supersedes** an earlier draft of this file that described option A (verify-only). The audit results below explain why option E became the chosen design. See [Alternatives considered](#alternatives-considered) for the explicit option F (audit-only) comparison.

## Outcome (2026-04-24, prereq-check session)

Before starting Phase 1 the three prerequisites were re-run against current state. Two of them changed the decision:

1. **`resolve_table_fields` exists** (`validate_skill.py:769`) — intact. ✅
2. **Five known reference bugs** (Phase 0, §Commit 1.1 + 1.3) — verified against source using the production parser. **All 5 are throwaway-parser false positives caused by projection-alias mis-resolution.**
   - `preproc_param_name`, `artifact_param_name`, `sorter_param_name`: these are the *actual* singular PK field names in source (`spikesorting/v1/recording.py:99`, `artifact.py:27`, `sorting.py:84`). Plan's claim of plural `_params_name` was wrong.
   - `spikesorting_merge_id` in `UnitAnnotation`: `-> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')` renames the FK field locally; reference correctly uses `spikesorting_merge_id` as the PK field name.
   - `CurationV1` → reference says `sorting_id, curation_id`. Source transitive PK resolves to exactly that (`-> SpikeSorting` → `-> SpikeSortingSelection` → `sorting_id`, plus own `curation_id`). Plan's "9-field PK" claim was wrong.
   - The plan's own caveat at §Source-side AST resolution line 144 ("throwaway script didn't handle projection aliases") applies to all 5, not just the LFP tables it named.
3. **Phase 0 audit replay with production parser:** 76 catalog entries / 42 with PK / 34 without (of which ~10 use prose `Primary key:` syntax not counted) / **0 real drift**.

### Revised cost-benefit

| Dimension | Plan claim | Post-audit reality |
| --- | --- | --- |
| Phase 1 cost | ~3 hrs | ~0 hrs (no drift to fix) |
| Phase 2 cost | ~2 hrs | ~2-3 hrs (~20 real missing-PK entries + ~10 prose-syntax normalizations) |
| Phase 3 cost | ~3-5 hrs | ~3-5 hrs (unchanged) |
| Past bugs caught | 7 (plan: 5 audit + 2 historical) | 2 historical only |
| Future drift prevention | real | real |

The value proposition shrinks from "catches 7 known bug patterns" to "prevents a failure mode that has occurred ~2 times in the skill's lifetime." Estimated per-incident saving vs. human review: ~15-30 min/year. Against a 4-5 hr one-time cost, payback is 10-20 years.

### Why not execute

- **Zero demonstrated drift.** The audit proved the references are currently clean. That fact is the real deliverable from this exercise.
- **Opportunity cost.** 4-5 hrs here displaces higher-leverage work: improving the skill's content (eval 61 showed skill-documentation gaps are the upstream cause of eval mistakes), the eval-failure-mode-coverage draft plan, adding evals to thin tiers.
- **Insurance pricing is wrong.** 4-5 hrs buys insurance against a failure mode with ~0 observed annual rate. Human review already catches the two historical instances the plan cited.

### When to revisit

- If a catalog-entry PK drift actually ships to users (discovered via eval failure, user report, or a Spyglass version bump invalidating a reference). At that point the full Option E (or the lighter Option B / "presence-only lint") becomes cheap insurance against the now-demonstrated pattern.
- If the reference corpus grows substantially (e.g., Spyglass adds 10+ new pipelines with catalog entries), pure human review will scale poorly and the lint half of Option E becomes justifiable on forcing-function grounds alone.

The sections below are the design as of plan drafting; treat everything after this outcome block as historical context. Phase 0 audit numbers (59 / 40 / 19 / 12 / 5) were based on the throwaway parser and are superseded by the production-parser replay above.

---

## Phase 0 audit (already complete — findings baked in)

A throwaway parser was run against the current 25-file `references/` dir on 2026-04-24. Results:

- **59 catalog entries** identified across 10 reference files (H3 backtick headers + bold-paren-tier lead-ins).
- **40 have structured PK declarations**; 19 do not.
- Of the 40 with declarations: **28 clean, 12 drift**.

Of the 12 drifts: **5 are genuine reference bugs**, 5 are parser limitations to be fixed during implementation, 2 are borderline (prose-only "inherits from X" hedges).

Specific drift items already enumerated in the per-phase sections below; the audit script is reproducible (~70 lines of Python; included as Phase 1 step).

## Goals and non-goals

**Goals.**

- Enforce that every catalog-style class entry declares its PK in a canonical pattern (presence check) OR marks itself exempt with reason.
- Verify each structured declaration matches the actual class definition in Spyglass source.
- Land with **zero new validator failures** by remediating discovered drift in the same commit chain (no baseline ratcheting).
- Catch the 5 known existing reference bugs surfaced by the Phase 0 audit.
- Produce concise, copy-pasteable failure messages naming the exact line and the exact mismatch.

**Non-goals.**

- Verifying secondary-attribute fields (only PK fields, part-table sets, direct dependencies). Secondary attrs change too often.
- Verifying field types (`varchar(80)` vs `varchar(64)`). Brittle across Spyglass versions.
- Verifying transitive dependency chains. Stays in eval-suite (evals 72, 73).
- Importing Spyglass at validator runtime. AST-only, same as existing validator.
- Auto-fix mode. Surface drift as failures; let humans decide.

## Repo layout changes

```text
skills/spyglass/
├── scripts/
│   ├── validate_skill.py           # modified — add check_schema_facts step
│   └── _schema_facts.py            # NEW — pure helper module (parse + verify + lint)
└── tests/
    └── test_validator_regressions.py  # modified — add 10 fixtures
```

## `_schema_facts.py` — parser + verifier + lint helper

### Why a helper module

`validate_skill.py` is already 2000+ lines. Schema-fact handling has enough surface (two markdown patterns, AST extraction with projection-alias support, transitive PK resolution, presence lint, three diff-format helpers) to warrant its own module. Keeps `validate_skill.py` from sprawling and makes the new logic unit-testable in isolation.

### Public surface

```python
# Markdown extraction
def extract_catalog_entries(md_text: str, file_path: str) -> list[CatalogEntry]: ...
def extract_pk_claims(md_text: str, file_path: str) -> list[PkClaim]: ...
def extract_part_table_claims(md_text: str, file_path: str) -> list[PartTableClaim]: ...

# Source-side resolution (pure, AST-only)
def source_pk_for(class_name: str, registry: ClassRegistry) -> list[str] | None: ...
def source_parts_for(class_name: str, registry: ClassRegistry) -> list[str] | None: ...

# Lint (presence check)
def lint_catalog_entries(entries: list[CatalogEntry]) -> list[str]:
    """Return failure strings for entries that lack a PK declaration AND
    no schema-exempt annotation."""

# Verify (correctness check)
def compare_pk(claim: PkClaim, source_pk: list[str]) -> list[str]: ...
def compare_parts(claim: PartTableClaim, source_parts: list[str]) -> list[str]: ...
```

### Dataclass shapes

```python
@dataclass(frozen=True)
class CatalogEntry:
    class_name: str
    file_path: str
    line: int
    has_pk_decl: bool
    has_exempt: bool
    block_text: str        # the ~10 lines following the entry header

@dataclass(frozen=True)
class PkClaim:
    class_name: str
    fields: tuple[str, ...]
    file_path: str
    line: int
    is_partial: bool       # True when "Key: includes ..." phrasing seen
```

`PartTableClaim` and `DepClaim` follow the same shape with type-appropriate `fields`.

### Markdown extraction — the two catalog patterns

**Pattern A — `### \`ClassName\`` block** (used in [common_tables.md](../../skills/spyglass/references/common_tables.md)):

```markdown
### `Electrode`

- **Primary Key**: `nwb_file_name`, `electrode_group_name`, `electrode_id`
```

**Pattern B — `**ClassName** (Tier)` block** (used in pipeline references):

```markdown
**LFPSelection** (Manual)

- Key: `nwb_file_name`, `lfp_electrode_group_name`, `target_interval_list_name`, `filter_name`, `filter_sampling_rate`
```

The class name comes from the H3 header / bold lead-in. Tier annotation in parens is informational, not parsed.

### Field extraction rules — derived from Phase 0 audit

The audit revealed several parser hazards. Bake the corresponding rules in from day 1:

1. **CamelCase tokens are not field names.** Class names that appear inside backticks within a PK line (e.g., `(inherits from \`ElectrodeGroup\`)`) must be filtered out. Heuristic: a field name starts with a lowercase letter or underscore; tokens starting with an uppercase ASCII letter are skipped.
   - Caught: `Electrode` ref bug — was extracting `ElectrodeGroup` from the inheritance aside.

2. **Parenthetical asides are stripped before tokenization.** Anything between `(` and `)` after the colon is dropped before backtick extraction.
   - Caught: `PositionSource` ref — extracted `Session`, `IntervalList` from "(Session, IntervalList)" parens.

3. **`Key: includes ...` triggers partial mode.** When `includes` appears in the PK line, set `is_partial=True`. In compare: only fail on extras (claim has a non-PK field), not on missing (claim omits a real PK field).
   - Tolerated: `LFPBandSelection` ref legitimately abbreviates with "includes".

4. **Backticked tokens that are obviously code (contain `.`, `(`, `=`) are not field names.** E.g., `\`fetch_nwb()\`` in a sentence after the PK line.

### Source-side AST resolution — REUSE existing parsers

**Critical: do not write a new DJ-definition parser.** [validate_skill.py:704-766](../../skills/spyglass/scripts/validate_skill.py) already has `_parse_dj_definition`, `resolve_table_fields`, and `_DJ_PROJ_RE` — robust handlers for `[nullable]`, projection renames (`Class.proj(alias='orig')`), comments, and the `---` PK/attr split. These are the production parser the rest of the validator already uses.

`_schema_facts.py` MUST import and reuse these primitives. The only new parsing in this plan is the **markdown-side** extractor (catalog entries + PK claim text). Source-side resolution is a pass-through to the existing helpers.

The audit's "false drift" findings on `LFPSelection`, `LFPBandSelection`, `Raw` were caused by my throwaway script not using the production parser — it didn't handle projection aliases. Once `source_pk_for(class_name)` delegates to `resolve_table_fields(class_name)`, those false drifts disappear automatically.

```python
# In _schema_facts.py:
from .validate_skill import resolve_table_fields  # NOT a re-implementation

def source_pk_for(class_name: str, registry: ClassRegistry) -> list[str] | None:
    """Pure pass-through to the production parser. Returns PK field list,
    transitively resolved with projection-alias support."""
    return resolve_table_fields(class_name, registry, pk_only=True)
```

If `resolve_table_fields` doesn't currently expose a `pk_only=True` mode, that's a small one-line extension of the existing helper, not a new parser. Either way: zero new DJ-definition parsing logic.

**Why this matters:** two parsers handling the same syntax will drift. The validator already maintains the production parser as Spyglass syntax evolves; the new module piggybacks on that maintenance. Reduces Phase 3 effort from ~6 hours to ~3 hours and eliminates an entire class of bugs.

### Lint — the presence check

For each `CatalogEntry`:

- If `has_pk_decl=True` → pass (verify will check correctness later).
- If `has_exempt=True` → pass (explicit opt-out — but the annotation must satisfy the **exempt grammar** below; abuse-resistant placeholders fail).
- Otherwise → fail with copy-pasteable suggestion:

  ```text
  common_tables.md:179: RawPosition entry lacks structured PK declaration
    Add within the entry block:
    - **Primary Key**: `field1`, `field2`, ...
    Or mark as exempt with category + reason (min 20 chars after colon):
    <!-- schema-exempt[upstream-pinned]: blocked on Spyglass issue #N — schema in flux -->
  ```

### Exempt annotation grammar

To prevent silencing-by-laziness (`<!-- schema-exempt: TODO -->`), the lint enforces:

```text
<!-- schema-exempt[<category>]: <reason text ≥ 20 chars> -->
```

**Required category** (in `[brackets]`, one of):

- `upstream-pinned` — waiting on a Spyglass-side schema change; track issue # in reason.
- `not-a-table` — entry is conceptual / doc-only and has no real schema (e.g., `heading` in spyglassmixin_methods.md).
- `derived-pk` — PK is verbatim a parent class's PK; documenting separately is redundant. Reason names the parent.
- `under-review` — author isn't sure what the PK should be; flagged for human follow-up. Reason names the follow-up date or issue.

**Rejected reasons** (lint fails the entry):

- Empty reason (just whitespace after the colon)
- Reasons matching `/^\s*(TODO|FIXME|XXX|TBD)\s*$/i`
- Reasons under 20 characters (forces the author to actually explain)
- Missing category brackets

Validator emits the rejection clearly:

```text
common_tables.md:179: schema-exempt annotation rejected
  reason: "TODO" — too short and matches the placeholder denylist
  required form: <!-- schema-exempt[<category>]: <≥20-char explanation> -->
  valid categories: upstream-pinned | not-a-table | derived-pk | under-review
```

### Comparator output

```text
common_tables.md:144: Electrode primary key mismatch
  reference says: nwb_file_name, electrode_id
  source says:    nwb_file_name, electrode_group_name, electrode_id
  diff:           +electrode_group_name (missing from reference)
  source: spyglass/common/common_ephys.py:73
```

PK fields treated as a set, not a sequence (order doesn't matter; missing/extra do).

## `validate_skill.py` extension — `check_schema_facts`

### Where to call it

Add as step 22 in the existing numbered pipeline (`[22/22] Verifying schema facts ...`). After step 21 (merge-table registry), before the summary.

### Function shape

```python
def check_schema_facts(results: ValidationResult, registry: ClassRegistry) -> None:
    """Lint + verify structured schema claims in references against
    actual class definitions in Spyglass source.

    Catches silent drift (the Electrode-PK pre-req fix in commit 84b5425
    and the Probe-parts addition in commit 5b8b9b7 are the canonical examples)
    AND enforces presence — every catalog entry must declare its PK or be
    marked exempt with reason.
    """
    from . import _schema_facts as sf

    for ref in REFERENCES_DIR.glob("*.md"):
        text = ref.read_text()
        rel = str(ref.relative_to(SKILL_DIR.parent))

        # Lint: presence check
        entries = sf.extract_catalog_entries(text, rel)
        for failure in sf.lint_catalog_entries(entries):
            results.fail(failure)

        # Verify: PK correctness
        for claim in sf.extract_pk_claims(text, rel):
            source = sf.source_pk_for(claim.class_name, registry)
            if source is None:
                results.warn(
                    f"{rel}:{claim.line}: PK check skipped — "
                    f"class '{claim.class_name}' not in registry"
                )
                continue
            for diff in sf.compare_pk(claim, source):
                results.fail(diff)

        # Verify: part-table correctness (same shape)
        for claim in sf.extract_part_table_claims(text, rel):
            source = sf.source_parts_for(claim.class_name, registry)
            if source is None:
                results.warn(...)
                continue
            for diff in sf.compare_parts(claim, source):
                results.fail(diff)
```

### Failure-vs-warning policy

- **Fail** (counts toward exit-1): structured claim disagrees with source; catalog entry missing PK declaration.
- **Warn** (counts toward `--baseline-warnings`): unparseable claim; class name not resolvable in registry.

## Phase 1 — drift remediation (specific list from audit)

Run BEFORE landing the validator change. Each drift item gets a remediation commit, grouped by reference file:

### Commit 1.1 — `references: fix spikesorting_v1_pipeline.md PK typos and CurationV1 stale doc`

Five changes in one commit (single file, related concern):

| Line | Change | Source verification |
| --- | --- | --- |
| 192 | `preproc_param_name` → `preproc_params_name` | `spikesorting/v1/recording.py` SpikeSortingPreprocessingParameters |
| 233 | `artifact_param_name` → `artifact_params_name` | `spikesorting/v1/artifact.py` ArtifactDetectionParameters |
| 249 | `sorter_param_name` → `sorter_params_name` | `spikesorting/v1/sorting.py` SpikeSorterParameters |
| 426 | `spikesorting_merge_id` → `merge_id` | `spikesorting/analysis/v1/unit_annotation.py` UnitAnnotation |
| 268 | CurationV1 PK rewrite — investigate stale doc | `spikesorting/v1/curation.py` CurationV1 (currently 9-field PK) |

The CurationV1 rewrite is the only judgment-call item. **Decision rule** (so a fresh agent can execute autonomously):

1. `git blame skills/spyglass/references/spikesorting_v1_pipeline.md | grep CurationV1` to find when the 2-field doc was added.
2. If blame predates 2024-06: the doc was likely written for the v0 schema or an early v1; default to "fix the docs to match current source" (rewrite to 9-field PK, add a note that this changed during v1 stabilization).
3. If blame is recent (post 2024-06): the doc was deliberately abbreviated; check the commit message for rationale. If the rationale was "users only need sorting_id and curation_id for fetching", convert to a `<!-- schema-exempt[derived-pk]: full PK matches CurationV1 source; users typically restrict by sorting_id+curation_id — see spikesorting/v1/curation.py -->` annotation and keep the abbreviated form in prose.
4. If neither (blame is ambiguous): rewrite to source PK (rule #2 default) and flag the commit for human review in the commit message.

Either way: ~30 min including the blame check.

### Commit 1.2 — `references: fix common_tables.md parens-aside extraction (Electrode, PositionSource)`

Two changes — restructure the parens-aside that the parser misreads as PK fields. Move the inheritance explanation to a separate sentence:

```markdown
### `Electrode`

- **Primary Key**: `nwb_file_name`, `electrode_group_name`, `electrode_id`
- Inherits the first two PK fields from ElectrodeGroup; adds own `electrode_id`.
- Channel-level metadata (coordinates, region, probe position).
```

(Was: PK line had a parens-aside with backticked class names.)

### Commit 1.3 — `references: fix common_tables.md Raw PK and AnalysisNwbfile entry`

`Raw` claims `(nwb_file_name, interval_list_name)` but Raw inherits only `nwb_file_name` from Session. **Decision rule:** rewrite the PK line to source-truth (`nwb_file_name` only), then add a follow-up bullet noting that `interval_list_name` is the per-record runtime convention (not a schema PK). The audit's flagging of this drift is correct; the remediation is mechanical once you've separated PK-fact from convention.

`AnalysisNwbfile`: my audit reported `analysis_file_name` as "extra" — but this is almost certainly a Phase 0 throwaway-parser bug (it didn't load `common_nwbfile.py`'s class). **Decision rule:** verify by running the production parser (Phase 3.1's `source_pk_for("AnalysisNwbfile")`). If it returns `['analysis_file_name']`, the reference is correct and no change needed. If it returns `None` (class still unresolvable), file an issue and skip with `<!-- schema-exempt[under-review]: ... -->`.

### Commit 1.4 — `references: clarify TrodesPosV1 inherits-from-Selection PK in position_pipeline.md`

The reference says `Key: inherits from TrodesPosSelection`. Either:

- (a) Itemize the inherited fields explicitly (preserves the validator's verify check), OR
- (b) Use `<!-- schema-exempt: PK is identical to TrodesPosSelection above; documented inline only -->` annotation.

Default to (a) for consistency.

### Commit 1.5 — `references: handle projection-alias PK declarations cleanly (LFPSelection, LFPBandSelection)`

These were flagged as drift by my naive parser, but the reference is actually CORRECT — it lists projected aliases. The fix is in `_schema_facts.py` (Commit 3.x), not the references. **No reference-side change in this commit.** Listed here as a placeholder for the design link.

## Phase 2 — missing PK declarations

Run BEFORE landing the validator change. 19 catalog entries lack structured PK lines. Each needs either an added line or an exempt annotation.

### Commit 2.1 — `references: add structured PK declarations to decoding_pipeline.md` (5 entries)

| Line | Class | Source PK (from definition) |
| --- | --- | --- |
| 228 | UnitWaveformFeatures | TBD — check `decoding/v1/waveform_features.py` |
| 238 | ClusterlessDecodingSelection | `nwb_file_name, ..., decoding_param_name, ...` (verify in source) |
| 244 | ClusterlessDecodingV1 | inherits from ClusterlessDecodingSelection |
| 296 | SortedSpikesDecodingSelection | TBD |
| 301 | SortedSpikesDecodingV1 | inherits |

For each: read the source class, write the canonical PK line. ~5 min per entry.

### Commit 2.2 — `references: add structured PK declarations to lfp_pipeline.md` (3 entries)

LFPV1 (line 124), LFPArtifactDetection (line 177), LFPBandV1 (line 201). Each inherits from its Selection table; itemize the inherited fields.

### Commit 2.3 — `references: add structured PK declarations to spikesorting_v1_pipeline.md` (4 entries)

SpikeSortingRecording (line 196), SpikeSorting (line 256), MetricParameters (line 303), MetricCuration (line 308).

### Commit 2.4 — `references: add structured PK declarations to remaining files` (7 entries)

- `linearization_pipeline.md`: LinearizationSelection (90), LinearizedPositionV1 (94)
- `mua_pipeline.md`: MuaEventsParameters (42)
- `ripple_pipeline.md`: RippleParameters (55)
- `setup_config.md`: AnalysisNwbfileKachery (294) — likely exempt
- `spyglassmixin_methods.md`: heading (149) — exempt; this is a method ref, not a class catalog entry
- `common_tables.md`: RawPosition (179)

Some of these may legitimately be exempt rather than declarative — apply judgment per entry.

## Phase 3 — validator integration + tests

### Commit 3.1 — `_schema_facts: add parser + lint + verify module with unit tests`

Module is dead code at this point — no caller in `validate_skill.py` yet. Includes:

- All public functions per the surface spec above
- 10 unit fixtures in `test_validator_regressions.py`:
  1. `fixture_pk_match` — claim matches source → no failure
  2. `fixture_pk_missing_field` — fails with "missing from reference" diff
  3. `fixture_pk_extra_field` — fails with "not a PK in source" diff
  4. `fixture_pk_inherited` — `-> ParentClass` resolves transitively
  5. `fixture_pk_includes_phrasing` — "includes" allows partial match
  6. `fixture_pk_parens_aside_filtered` — backticked CamelCase in parens stripped
  7. `fixture_pk_projection_alias` — `IntervalList.proj(alias='orig')` rename works
  8. `fixture_part_tables_missing` — source has nested Part not in ref → fails
  9. `fixture_unresolved_class_warns` — class not in registry → warn
  10. `fixture_catalog_entry_missing_pk_fails` — entry without PK line → fail
  11. `fixture_catalog_entry_with_exempt_passes` — `<!-- schema-exempt: ... -->` opt-out

### Commit 3.1.5 — shadow run (no commit; verification step)

Before flipping the gate (3.2), exercise `_schema_facts.py` as dead code against the full reference set:

```bash
python3 -c "
from skills.spyglass.scripts import _schema_facts as sf
from skills.spyglass.scripts.validate_skill import build_registry
import pathlib, sys
registry = build_registry(spyglass_src='/path/to/spyglass/src')
fail_count = 0
for ref in sorted(pathlib.Path('skills/spyglass/references').glob('*.md')):
    text = ref.read_text()
    for failure in sf.lint_catalog_entries(sf.extract_catalog_entries(text, str(ref))):
        print(failure); fail_count += 1
    for claim in sf.extract_pk_claims(text, str(ref)):
        source = sf.source_pk_for(claim.class_name, registry)
        if source is None: continue
        for diff in sf.compare_pk(claim, source):
            print(diff); fail_count += 1
print(f'shadow run: {fail_count} failures')
" > shadow_run_report.txt
```

**Pass criteria:** zero failures. If non-zero:

- A failure on a remediated reference means Phase 1 or Phase 2 missed something. Fix the reference, re-run.
- A failure on a reference NOT touched in Phases 1/2 means the production parser found drift the throwaway audit missed (likely projection-alias related). Add a Phase 1.6 commit for it.
- A failure that looks like a parser bug (false-positive) means `_schema_facts.py` needs a fix before integration. Iterate Commit 3.1.

Only land Commit 3.2 once the shadow run is clean. The shadow run is NOT a commit; it's a manual verification gate the executing agent runs and reports on.

### Commit 3.2 — `validate_skill: integrate check_schema_facts as step 22`

Adds the call site. Phases 1, 2, and the shadow run (3.1.5) must already be complete; CI fails otherwise.

### Commit 3.3 — `evals/README.md: document the schema-fact validator and exempt annotation`

User-facing doc update. Explain:

- What the validator checks
- The canonical PK pattern
- The exempt annotation syntax and when to use it
- How to interpret failure messages
- Pointer to the helper module for parser internals

## Cross-cutting validation and rollout

### Per-step gate

After every Phase 1 / 2 / 3 commit:

```bash
SPYGLASS_SRC=/Users/edeno/Documents/GitHub/spyglass/src \
  ./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
python3 skills/spyglass/evals/scripts/flatten_expectations.py --check
ruff check .
```

After Phase 3.2 lands, the validator's new `check_schema_facts` step must produce zero failures (Phases 1 + 2 land all the prerequisites).

### Commit ordering (strict)

1. Phase 1.1–1.5 (drift remediation, ~5 commits)
2. Phase 2.1–2.4 (missing PK declarations, ~4 commits)
3. Phase 3.1 (helper module + unit tests, validator not yet integrated)
4. Phase 3.2 (validator integration — the gate-flipping commit)
5. Phase 3.3 (user-facing README update)

11 commits total. Phase 1 and Phase 2 commits can interleave (different files, no conflicts). Phase 3 must come after both are complete.

### Rollback

Each commit is atomic. Phase 3.2 is the gate-flipping commit; revert it to disable the new check without touching the helper module. Phase 1 and 2 commits make references more accurate independently of the validator; reverting them re-introduces drift but doesn't break anything functional.

### Pre-commit-hook impact

The existing `scripts/pre-commit-validate.sh` already runs `validate_all.sh` on changes to `references/*.md` and `evals.json`. No change needed — the new check piggybacks on the existing wrapper. Authors will start seeing the new failures once Phase 3.2 lands.

## Edge cases / known limitations

### What the validator catches

- PK field-set drift (missing or extra fields in reference)
- Part-table set drift
- Catalog entries missing PK declaration entirely

### What the validator does NOT catch

- Schema facts in prose paragraphs (option E only enforces structure where catalog patterns are used)
- Field types
- Field ordering (treated as a set)
- Transitive dependency chains
- Method-level behavior changes
- Documentation prose drift ("use this for X")

### Spyglass-version coupling

When Spyglass legitimately changes a PK upstream, the validator will fire on every reference documenting the old PK. Remediation lockstep is part of the cost. If this becomes painful in practice, two mitigations:

1. Bump the validator's failure-vs-warning policy on individual claims via the `<!-- schema-exempt: pinned to spyglass v0.5; track upstream issue #N -->` annotation.
2. Pin a `SPYGLASS_VERSION` field in the reference frontmatter and have the validator compare against the matching source ref. (Not in scope for this plan.)

### Author friction

Every new catalog entry now requires the structured PK line. Authors learn it once. The exempt annotation provides an escape hatch for legitimate stub entries.

## Alternatives considered

The design discussion considered four shapes; this plan picks Option E. Documenting the comparison so the trade-off is auditable and so a future executor (or revisitor) can see why the cheaper alternative was passed over.

| Option | What it does | Cost | Captures past bugs | Captures future drift |
| --- | --- | --- | --- | --- |
| **A** — verify-only | Parse known PK/parts patterns; verify against source. No presence enforcement. | ~1 day | Yes (when patterns are used) | Partial — only where authors used the canonical pattern; silent in prose |
| **D** — defer entirely | Rely on schema-introspection evals 74-78. | ~0 hours | Only those covered by 74-78 | At eval-run time, not commit time |
| **E** — lint + verify (this plan) | A + presence enforcement on catalog entries. | ~1.5-2 days | Yes (Phase 1+2) | Yes (Phase 3) |
| **F** — audit-only, no validator | Phase 1 + Phase 2 from this plan. Skip Phase 3. | ~5 hours | Yes | No (rely on Option D for forward) |

### Why not Option F

Option F captures the **5 known reference bugs** and adds the **19 missing PK declarations** without building the validator. ~30% of Option E's cost. Reasonable middle ground.

The case AGAINST Option F (and FOR going to Option E):

1. **Drift recurs.** Two historical instances (Electrode PK in commit `84b5425`, Probe parts in `5b8b9b7`) plus 5 audit-found bugs = 7 known instances over the skill's lifetime. Without an automated check, the next instance lands silently and stays until someone happens to write a contradicting eval. Option E catches it pre-commit.
2. **Marginal cost is moderate, not large.** Option E's marginal cost over Option F is ~5-7 hours (Phase 3 only; helper module reuses existing parsers). One-time.
3. **References will grow.** Each new pipeline added to Spyglass adds catalog entries to the references. Without enforcement, missing-PK-line is undetectable; with enforcement, it's a pre-commit fail.

The case FOR Option F (against Option E):

1. **Bug rate is unclear.** 7 instances over the skill's lifetime might mean "rare" or "we just haven't noticed". No way to know future rate from the past.
2. **Maintenance burden.** Each Spyglass version bump may produce drift remediation work. A validator that's wrong-too-often becomes a chore.
3. **One-time audit value is captured by F.** The big bug-catching value (the Phase 0 audit finding 5 real bugs) is delivered by F alone.

### Decision

Going with Option E because: (a) the marginal cost is small after parser-reuse, (b) drift WILL recur as Spyglass evolves and the bug-detection-time gap is real, (c) the schema-exempt grammar gives a clean escape hatch for legitimate Spyglass-version drift. If maintenance burden proves painful in practice, the validator integration commit (3.2) can be reverted independently — Option E gracefully degrades to Option F.

Option F remains the right call if the user values minimal infrastructure over automated detection. **The user explicitly chose Option C (full Option E build-out) after seeing this comparison; the option is auditable here for revisiting.**

## Eval consideration

Should we add an eval for this work? Three candidate shapes:

1. **User hits the lint failure, asks for help interpreting it.** Skill should explain the canonical PK pattern + the exempt annotation grammar.
2. **User asks "how do I document a new table I'm adding?"** Skill should mention the structured PK declaration as required.
3. **User asks "how does the validator check schema facts?"** Meta-eval testing skill comprehension of its own infrastructure.

**Recommendation: add ONE eval (#1) as eval 79 in the workflow-position tier**, slotted alongside evals 70 and 71. Rationale:

- Eval #1 is the only candidate that tests a real failure mode a user will actually hit. They run pre-commit, get the new lint failure, ask Claude for help. The skill needs to know about the new rule.
- It verifies that Commit 3.3 (the README update) is good enough that the skill can answer about it. Without an eval, that documentation update is unverified.
- Eval #2 overlaps with eval 8 (custom-pipeline authoring) which already covers "how do I document tables". Marginal value too low.
- Eval #3 is too meta — users don't ask Claude to explain validator internals; they ask why a specific failure happened.

The new eval slots cleanly into the existing pattern:

- **id:** 79
- **stage / tier / difficulty:** `runtime-debugging` / `workflow-position` / `easy`
- **prompt:** "I just edited common_tables.md to add a new class entry and the pre-commit hook fails with `[FAIL] common_tables.md:200: NewSorting entry lacks structured PK declaration`. What do I need to add?"
- **required_substrings:** `**Primary Key**:`, `schema-exempt[`, `category`
- **behavioral_checks:**
  - Names the canonical PK pattern (`- **Primary Key**: \`field1\`, ...`)
  - Mentions the exempt annotation as the explicit opt-out path
  - References the four valid categories OR points the user to evals/README.md for the full grammar

Land eval 79 as Commit 3.4 (immediately after the user-facing README update in 3.3). Total commit count goes from 11 to 12.

**Cost:** ~15 minutes. Minor scope increase. The eval's grader-time runtime cost is negligible. Captures real value: documentation isn't useful if the skill can't surface it under user pressure.

## Open questions deferred to execution

1. **CurationV1 PK investigation** (Phase 1.1, line 268). Could be: stale v0 doc, intentional simplification, or just always wrong. Need to read git history of `spikesorting_v1_pipeline.md:268` and the source `spikesorting/v1/curation.py` to decide whether the rewrite is "fix the docs to match current source" or "the source needs a constraint we should add". Default: fix the docs to match current source; flag for human review if the source state itself looks suspicious.
2. **`AnalysisNwbfile` audit anomaly** (Phase 1.3). My naive parser reported `analysis_file_name` as "extra" relative to source. Either source has different PK, or my parser failed to resolve the class. Investigate during execution; fix accordingly.
3. **`schema-exempt` annotation grammar** (Phase 3.1). Current proposal: `<!-- schema-exempt: <reason> -->`. Should reasons be free-form or structured (e.g., `reason="upstream-pinned"` with enumerated reasons)? Free-form is simpler; structured enables aggregate-reason reporting. Default to free-form; revisit if reasons proliferate.

## Estimated effort

- Phase 0 (audit): **DONE** during plan drafting (~30 min).
- Phase 1 (drift remediation): ~3 hours (5 commits × ~30 min each, including source verification per item).
- Phase 2 (missing PK declarations): ~2 hours (19 entries × ~5 min, batched into 4 commits).
- Phase 3 (validator integration + tests): **~3-5 hours** (was estimated higher; cut substantially because Commit 3.1 reuses the existing `_parse_dj_definition` / `resolve_table_fields` helpers — no new DJ-syntax parser to write). Most effort now: markdown extractor + exempt-annotation grammar + 11 unit fixtures. The shadow-run step (3.1.5) adds ~1 hour for run + iteration.

Total: **~9-11 hours of focused work**, roughly 1.5 days. Could be split across two sessions; Phase 1+2 in session 1, Phase 3 in session 2.

Reviewer floor estimate (assuming parser edge cases multiply): ~14 hours / 2 days. Realistic range: 1.5-2 days.

## Success criteria

1. `validate_all.sh --baseline-warnings 3` passes after every commit in the chain (no baseline ratcheting).
2. After Phase 3.2 lands, the new `check_schema_facts` step produces zero failures on the current reference state.
3. The 5 known existing reference bugs (4 typos + CurationV1 mismatch) are corrected.
4. Adding a new class entry to any reference file now requires either a structured PK line or an explicit exempt annotation.
5. A future Spyglass-source schema change (PK addition) is caught at pre-commit time on the next reference edit, not by random user discovery or eval failure.
