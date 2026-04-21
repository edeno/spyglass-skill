# Spyglass skill

A Claude Code skill for the [LorenFrankLab Spyglass](https://github.com/LorenFrankLab/spyglass)
neurophysiology framework (DataJoint + NWB). Loaded automatically when the
frontmatter description matches what Claude is working on; see [SKILL.md](SKILL.md)
for the skill itself and [references/](references/) for progressive-disclosure
topics.

This README is for people maintaining the skill, not for readers of the
skill's guidance — that audience is served by SKILL.md being loaded into
Claude's context directly.

## Layout

```
SKILL.md                       # entry point (always loaded into context)
references/                    # progressive-disclosure topic files
scripts/validate_skill.py      # static validator (AST over .md files)
scripts/validate_all.sh        # one-command runner for all checks
tests/test_validator_regressions.py   # 46 regression fixtures
tests/test_runnable_imports.py        # opt-in live-import harness
evals/evals.json               # behavioral eval cases
evals/README.md                # eval authoring notes
```

## Checking the skill

The validator runs AST-based checks over the skill's markdown — no database,
no spyglass install required. 20 numbered checks plus a 21st standalone
import harness that lives outside the main validator (because it requires
spyglass + its deps to be importable).

**Single command (recommended):**

```bash
spyglass/scripts/validate_all.sh --spyglass-src /path/to/spyglass/src
```

This runs the main validator, the regression fixtures, and the import
harness in sequence. The first two gate exit status; the harness is
informational.

**Individual commands:**

```bash
# Main validator — AST checks against a spyglass checkout
python3 spyglass/scripts/validate_skill.py --spyglass-src PATH

# Regression fixtures — self-contained synthetic test cases
python3 spyglass/tests/test_validator_regressions.py --spyglass-src PATH

# Import harness — actually imports modules; needs spyglass env
/path/to/conda/env/bin/python spyglass/tests/test_runnable_imports.py \
    --spyglass-src PATH
```

**Useful flags on the main validator:**

- `-v` — show passing checks alongside warnings/failures
- `--strict` — treat any warning as a failure
- `--baseline-warnings N` — CI-friendly: fail only if warnings > N
  (lets a tree with N known-accepted warnings catch *new* ones)

## What the validator checks

Checks are numbered in `validate_skill.py`'s `main()` output. Broadly:

| Dimension | Checks |
|---|---|
| Instruction correctness | import resolution, method existence, kwarg validity, DataJoint anti-patterns, dict-restriction fields, insert/populate key shape |
| Freshness / drift | file path existence, notebook names, markdown links, citation line numbers, citation identifier match, link-landing content overlap |
| Size / shape | SKILL.md word caps, reference file line budgets, per-H2 subsection budgets |
| Hygiene | Python syntax in code blocks, third-person description, banned PR-number citations, cross-file code duplication |
| Evals | evals.json hallucinated class/method references |

See `validate_skill.py` for the full policy. Warnings are for approximate
checks (false-positive risk); failures are for bugs the AST can prove.

## Adding a regression fixture

When a real bug slips past the validator and you're tightening a check to
catch it in the future, add a synthetic fixture first:

1. Write the fixture in `tests/test_validator_regressions.py`. It should
   construct the bug as a minimal synthetic md, run the relevant check
   against it, and `_assert_contains` / `_assert_warn_contains` on the
   expected message.
2. Register it in the `FIXTURES` list.
3. Run `python3 spyglass/tests/test_validator_regressions.py --spyglass-src PATH`
   and confirm your fixture shows up in the output.
4. Then tighten the check in `validate_skill.py` until the fixture passes.

Existing fixtures cover the 7 session-added checks densely and the older
checks sparsely — gaps in coverage are a good place to start if you're
looking for drive-by maintenance.

## Working on the skill content itself

Edit `SKILL.md` or `references/*.md`, then run the validator. A clean run
is 1450+ passed, ≤17 warnings, 0 failed. The 17 warnings are pre-existing
accepted signal being drained in prose-cleanup passes — new warnings
should not push that count up.

Size budgets are enforced: reference files have a 500-line soft cap and
700-line hard cap (hard = CI fail). H2 subsections warn above 150 lines.
When a file crosses a budget, the right response is usually to split
(see `populate_all_common_debugging.md` as a precedent), not to raise
the cap.

## Evals

`evals/evals.json` holds behavioral eval cases for `run_loop.py`-style
optimization. See `evals/README.md` for authoring conventions. The
validator's check #14 scans eval prose for hallucinated method references
— a clean validator run is a precondition for trusting eval results.
