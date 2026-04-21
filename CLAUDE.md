# CLAUDE.md — maintainer guidance for this repo

This file is for Claude working **on** the skill (editing SKILL.md,
references, validator, tests). The skill's own guidance for
*users of Spyglass* lives in [skills/spyglass/SKILL.md](skills/spyglass/SKILL.md)
and is a different audience — do not merge the two.

## Repo shape

- [skills/spyglass/SKILL.md](skills/spyglass/SKILL.md) — entry point loaded into Claude's context when the frontmatter triggers match.
- [skills/spyglass/references/](skills/spyglass/references/) — progressive-disclosure topic files, pulled in on demand.
- [skills/spyglass/scripts/](skills/spyglass/scripts/) — validator (`validate_skill.py`) + runner (`validate_all.sh`).
- [skills/spyglass/tests/](skills/spyglass/tests/) — 46 regression fixtures + opt-in import harness.
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

- Don't `cat` or `Read` a user's `dj_local_conf.json` / `~/.datajoint_config.json` — they hold DB passwords. SKILL.md teaches a scrubbed-read pattern; this repo's Claude should follow it too.
- Don't hand-write HTML for eval reviews; use skill-creator's `generate_review.py`.
- Don't commit a personal `$SPYGLASS_SRC` path or anything under `*-workspace/` (gitignored).
- Don't bypass hooks (`--no-verify`) on commits. If the validator fails, fix the drift — that's the point of the gate.

## Commit messages

Follow the existing style (see `git log`): topic prefix + lowercase
description, e.g. `destructive_operations: add explicit phase workflow`.
No ticket numbers, no Anthropic-generated trailers unless explicitly
requested.
