---
title: "Spyglass drift: weekly validation is failing"
labels: drift, ci
---

The weekly drift-detection workflow failed against a fresh checkout of
`LorenFrankLab/spyglass` master. The skill's prose has drifted from the
live Spyglass source, or Spyglass introduced a change the validator
flags as a break.

## Details

- **Spyglass revision under test:** `{{ env.SPYGLASS_SHA }}`
- **Upstream commit subject:** {{ env.SPYGLASS_SUBJECT }}
- **Failed run:** [view logs]({{ env.RUN_URL }})

## Triage

1. Open the failed run and scroll to the first FAIL line. The validator
   prints the check number, the file, and the specific assertion that
   failed (e.g. `method 'LFPV1.populate' not found`).
2. Diff Spyglass between the last known-green SHA and
   `{{ env.SPYGLASS_SHA }}` on the relevant file:
   ```bash
   cd ../spyglass
   git log --oneline <last-green-sha>..{{ env.SPYGLASS_SHA }} -- path/to/file.py
   ```
3. If the change is intentional on Spyglass's side, update the skill
   content (SKILL.md / references / KNOWN_CLASSES) and run the validator
   locally:
   ```bash
   export SPYGLASS_SRC=/path/to/spyglass/src
   ./skills/spyglass/scripts/validate_all.sh --baseline-warnings 4
   ```
4. If the drift reveals a real Spyglass bug, file it upstream and pin
   this issue with a link.
5. Close this issue once CI goes green.

## Notes

- This issue is reused across runs: subsequent weekly failures update
  the body in place rather than opening duplicates, so check the
  "updated" timestamp to see the latest revision under test.
- Closing the issue resets it — the next failure opens a fresh issue.
