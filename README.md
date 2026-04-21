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

Inside Claude Code:

```text
/plugin install https://github.com/edeno/spyglass-skill
```

Or manually, if you prefer a single-skill drop-in install:

```bash
git clone https://github.com/edeno/spyglass-skill.git /tmp/spyglass-skill
cp -r /tmp/spyglass-skill/skills/spyglass ~/.claude/skills/spyglass
```

Restart Claude Code (or start a new session). The skill activates on
Spyglass-related prompts.

## What's in here

```text
.claude-plugin/plugin.json        # plugin manifest
skills/spyglass/                  # the skill itself
  SKILL.md                        # entry point loaded into context
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
