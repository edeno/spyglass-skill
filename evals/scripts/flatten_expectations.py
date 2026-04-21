#!/usr/bin/env python3
"""Regenerate each eval's `expectations` field from its `assertions` buckets.

Skill-creator's stock grader reads a flat `expectations: list[str]` per eval
(`references/schemas.md`). This suite's authoring surface is richer —
`assertions.required_substrings`, `assertions.forbidden_substrings`, and
`assertions.behavioral_checks` — so `expectations` has to be derived, not
hand-maintained.

Run after every edit to `assertions`:

    python3 scripts/flatten_expectations.py          # rewrite in place
    python3 scripts/flatten_expectations.py --check  # exit 1 if stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals.json"


def flatten(eval_obj: dict) -> list[str]:
    """Project one eval's three assertion buckets into a flat list of
    declarative pass/fail statements."""
    a = eval_obj.get("assertions", {})
    out: list[str] = []
    for s in a.get("required_substrings", []):
        out.append(f"Response contains substring `{s}`.")
    for s in a.get("forbidden_substrings", []):
        out.append(f"Response does not contain substring `{s}`.")
    out.extend(a.get("behavioral_checks", []))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 without writing if expectations are out of sync.",
    )
    args = ap.parse_args()

    data = json.loads(EVALS.read_text())
    stale_ids: list[int] = []
    for e in data["evals"]:
        expected = flatten(e)
        if e.get("expectations") != expected:
            stale_ids.append(e["id"])
            e["expectations"] = expected

    if args.check:
        if stale_ids:
            print(
                f"expectations out of sync for eval IDs: {stale_ids}",
                file=sys.stderr,
            )
            print("run: python3 scripts/flatten_expectations.py", file=sys.stderr)
            return 1
        print("expectations in sync")
        return 0

    EVALS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if stale_ids:
        print(f"regenerated expectations for {len(stale_ids)} eval(s): {stale_ids}")
    else:
        print("no changes needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
