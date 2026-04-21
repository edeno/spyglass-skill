# spyglass-skill

A Claude Code plugin providing the `spyglass` skill — guidance for the
[LorenFrankLab Spyglass](https://github.com/LorenFrankLab/spyglass)
neurophysiology framework (DataJoint + NWB).

The skill activates automatically when Claude is working on code that
imports `spyglass.*`, touches `SpyglassMixin` / V1 pipeline classes, or
otherwise mentions Spyglass. See [`skills/spyglass/SKILL.md`](skills/spyglass/SKILL.md)
for the skill content itself and [`skills/spyglass/README.md`](skills/spyglass/README.md)
for detailed notes on the validator, regression fixtures, and skill
layout.

## Install

The skill uses the `SKILL.md` format, which Claude Code, OpenAI
Codex CLI, and Gemini CLI all read natively (as of early 2026). Only
the install location differs per tool.

### Claude Code

```text
/plugin install https://github.com/edeno/spyglass-skill
```

Or manually:

```bash
git clone https://github.com/edeno/spyglass-skill.git /tmp/spyglass-skill
cp -r /tmp/spyglass-skill/skills/spyglass ~/.claude/skills/spyglass
```

### OpenAI Codex CLI

```bash
git clone https://github.com/edeno/spyglass-skill.git /tmp/spyglass-skill
cp -r /tmp/spyglass-skill/skills/spyglass ~/.codex/skills/spyglass
```

Or scope the skill to a single project by copying into
`.agents/skills/spyglass/` at that project's root — Codex scans up
from the working directory.

### Gemini CLI

Consult the
[Gemini CLI skills docs](https://geminicli.com/docs/cli/skills/)
for the current install path; the `skills/spyglass/` directory is
format-compatible.

### After install

Restart the agent (or start a new session). The skill activates
automatically when the task involves Spyglass imports, `SpyglassMixin`,
V1 pipeline classes, or related topics — see the
[frontmatter description](skills/spyglass/SKILL.md) for the full
activation rules.

## What's in here

```text
.claude-plugin/plugin.json        # Claude Code plugin manifest
skills/spyglass/                  # the skill itself (SKILL.md + references)
  SKILL.md                        # entry point, loaded into context on match
  references/                     # progressive-disclosure topic files
  scripts/                        # validator + convenience runner
  tests/                          # regression fixtures + import harness
  evals/                          # behavioral eval cases
  README.md                       # maintainer notes
```

## Reviewing the skill

If you're reviewing this for correctness rather than using it, start at
[`skills/spyglass/SKILL.md`](skills/spyglass/SKILL.md) for the
user-facing guidance and [`skills/spyglass/references/`](skills/spyglass/references/)
for the detailed topic references. The validator in
[`skills/spyglass/scripts/validate_skill.py`](skills/spyglass/scripts/validate_skill.py)
gates skill quality against a live Spyglass checkout — see the skill's
own README for how to run it.

Issues and PRs welcome at [github.com/edeno/spyglass-skill](https://github.com/edeno/spyglass-skill).

## License

MIT — see [LICENSE](LICENSE).
