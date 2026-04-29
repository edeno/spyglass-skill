# CLAUDE.md — maintainer guidance for this repo

This file is for Claude working **on** the skill (editing SKILL.md,
references, validator, tests). The skill's own guidance for
*users of Spyglass* lives in [skills/spyglass/SKILL.md](skills/spyglass/SKILL.md)
and is a different audience — do not merge the two.

## Repo shape

- [skills/spyglass/SKILL.md](skills/spyglass/SKILL.md) — entry point loaded into Claude's context when the frontmatter triggers match.
- [skills/spyglass/references/](skills/spyglass/references/) — progressive-disclosure topic files, pulled in on demand.
- [skills/spyglass/scripts/](skills/spyglass/scripts/) — validator (`validate_skill.py`) + runner (`validate_all.sh`).
- [skills/spyglass/tests/](skills/spyglass/tests/) — 58 regression fixtures + opt-in import harness.
- [skills/spyglass/evals/](skills/spyglass/evals/) — behavioral eval cases for skill-creator's optimization loop.

## Editing workflow

After any change to `SKILL.md` or `references/*.md`, run the validator:

```bash
./skills/spyglass/scripts/validate_all.sh --baseline-warnings 3
```

It reads `$SPYGLASS_SRC` (see README.md for how to set it). Exit
status is gated on the main validator + regression suite; the import
harness is informational.

When tightening a check, add a regression fixture first
(see `tests/test_validator_regressions.py`) so the new rule is
permanently pinned. The README in `skills/spyglass/` has the full
procedure.

### Python linting

The repo's Python surface (validator + tests + eval scripts) is
gated by ruff. Config: [ruff.toml](ruff.toml). Run before committing:

```bash
ruff check .
```

CI runs the same command. If you add or edit `.py` files, also
install the pre-commit hook so ruff runs automatically:

```bash
pip install pre-commit && pre-commit install
```

The pre-commit config also wires in the full skill validator,
scoped to content files and graceful about missing Spyglass
checkouts — see [.pre-commit-config.yaml](.pre-commit-config.yaml).

### Python environment for dev testing

**Never install dependencies into the base / system Python** when
trying something out — smoke-testing a script, running tests against
extra packages, probing an import. Use an environment isolated from
base:

- `uvx --with <pkg> ...` or `uv run --with <pkg> ...` — ephemeral
  throwaway environment, auto-cleaned, no base pollution. Preferred
  for one-off checks (`uvx --with pytest --with datajoint pytest
  skills/spyglass/tests/...`).
- A dedicated conda environment (`conda create -n spyglass-dev python=...`
  then activate).
- A project `venv` (`python -m venv .venv && source .venv/bin/activate`).

Base/system Python is for system tooling; polluting it with
Spyglass-adjacent packages (datajoint, pynwb, spikeinterface, …) makes
future env reasoning harder and can break unrelated projects. This
applies equally to subagents running here.

## Size budgets (enforced by the validator)

- Reference files: **500-line soft cap**, **700-line hard cap**.
- Per-H2 subsections: warn above 150 lines.
- SKILL.md has its own word caps checked in `validate_skill.py`.

When a file crosses a budget, **split** (see
`populate_all_common_debugging.md` as a precedent). Do not raise the
cap — the caps exist because context bloat hurts triggering quality.

## Common edits and their gotchas

- **Adding a class to SKILL.md / references**: also add it to `KNOWN_CLASSES` in `validate_skill.py` with its source file, or the method-existence check can't verify it.
- **Citing line numbers (`file.py:123`)**: the validator checks these resolve in the Spyglass source. Update or remove them when Spyglass is bumped.
- **Linking to other skill files**: the validator checks link landing content overlaps with the linking context. Vague links warn.
- **Frontmatter description changes**: re-run skill-creator's description optimization before shipping — triggering accuracy drifts quickly.

## What not to do

- Don't `cat` or `Read` a user's `dj_local_conf.json` / `~/.datajoint_config.json` — they hold DB passwords. Canonical safe-read is `python skills/spyglass/scripts/scrub_dj_config.py` (SKILL.md Core Directive #6); this repo's Claude should follow it too.
- Don't hand-write HTML for eval reviews; use skill-creator's `generate_review.py`.
- Don't commit a personal `$SPYGLASS_SRC` path. Eval sweep artifacts live in a separate repo: [edeno/spyglass-skill-workspace](https://github.com/edeno/spyglass-skill-workspace). Clone it as a sibling of this repo to run the analysis scripts (per-run sweeps under `runs/<run-id>/`). The `skills/spyglass-workspace/` path here is gitignored.
- Don't bypass hooks (`--no-verify`) on commits. If the validator fails, fix the drift — that's the point of the gate.
- When dispatching subagents for a graded eval sweep, use the canonical prompt templates in [skills/spyglass/evals/dispatch_prompts.md](skills/spyglass/evals/dispatch_prompts.md). The without_skill template explicitly prohibits reading `skills/spyglass/` to prevent baseline contamination — see [`spyglass-skill-workspace`'s round-c SUMMARY.md](https://github.com/edeno/spyglass-skill-workspace/blob/main/runs/round-c-2026-04-28/summary/SUMMARY.md) ("Transcript-level caveats and mechanisms") for the empirical evidence motivating that prohibition. Per-sweep artifacts live in the [edeno/spyglass-skill-workspace](https://github.com/edeno/spyglass-skill-workspace) repo under `runs/<run-id>/`; each run directory carries its own `run.json` with skill/source commits and headline results.

## Commit messages

Follow the existing style (see `git log`): topic prefix + lowercase
description, e.g. `destructive_operations: add explicit phase workflow`.
No ticket numbers, no Anthropic-generated trailers unless explicitly
requested.
