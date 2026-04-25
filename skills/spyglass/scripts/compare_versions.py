#!/usr/bin/env python3
"""Compare class/method surface across version directories of a Spyglass pipeline.

Many Spyglass pipelines ship multiple versions side-by-side
(``spyglass/<pipeline>/v0/``, ``v1/``, eventually ``v2/``). The versions
are *partial* refactors: a method present on v0 ``SortGroup`` may be
absent from v1 ``SortGroup`` (and vice versa). Memorizing which methods
differ is brittle; the source itself is the source of truth.

Run this script before naming a method on a versioned pipeline if you're
unsure whether the symmetry holds. It AST-parses each version directory
and prints which classes / methods exist in one version but not the
other, against the pinned Spyglass source.

Usage::

    # Compare v0 and v1 (auto-discover all version siblings if you omit them)
    python compare_versions.py spikesorting v0 v1
    python compare_versions.py spikesorting

    # Single class focus
    python compare_versions.py spikesorting v0 v1 --class SortGroup

    # Override the Spyglass source root (defaults to $SPYGLASS_SRC)
    python compare_versions.py lfp v0 v1 --src /path/to/spyglass/src

Exit code is always 0 (this is a discovery tool, not a gate).

Limits worth knowing:
  - Detects same-class same-name presence/absence asymmetries. Does NOT
    detect cases where v0 functionality was moved to a *different* class
    in v1 (e.g., v0 ``LFPSelection.set_lfp_electrodes`` -> v1
    ``LFPElectrodeGroup.create_lfp_electrode_group``). For structural
    redesigns you still need to read the source.
  - Skips private methods (``_*``) by default; ``--show-private`` to include.
"""

import argparse
import ast
import os
import sys
from collections import defaultdict
from pathlib import Path


def _resolve_src_root(arg_src: str | None) -> Path:
    """Pick the Spyglass src/ directory: --src flag wins, else $SPYGLASS_SRC."""
    if arg_src:
        return Path(arg_src).resolve()
    env = os.environ.get("SPYGLASS_SRC")
    if env:
        return Path(env).resolve()
    sys.exit(
        "ERROR: pass --src PATH or set $SPYGLASS_SRC to your Spyglass src/ "
        "directory (the one containing the `spyglass/` package)."
    )


def _list_pipelines(src_root: Path) -> list[str]:
    """Top-level subpackages of `spyglass/` — the candidate pipeline names."""
    pkg_root = src_root / "spyglass"
    if not pkg_root.is_dir():
        return []
    return sorted(
        p.name
        for p in pkg_root.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


def _list_versions(src_root: Path, pipeline: str) -> list[str]:
    """Version subdirectories under `spyglass/<pipeline>/` matching `v<N>`."""
    pipe_root = src_root / "spyglass" / pipeline
    if not pipe_root.is_dir():
        return []
    return sorted(
        p.name
        for p in pipe_root.iterdir()
        if p.is_dir() and len(p.name) >= 2 and p.name[0] == "v" and p.name[1:].isdigit()
    )


def _scan_version(version_root: Path, show_private: bool) -> dict[str, dict]:
    """Walk a version directory, AST-parse each .py, collect class -> info.

    Returns a dict of ``class_name -> {"methods": set[str], "files": list[str]}``.
    Method set is body-level ``def`` only (no nested defs); files list shows
    every module that defines a class with that name (typically one).
    """
    classes: dict[str, dict] = defaultdict(lambda: {"methods": set(), "files": []})
    for py_file in sorted(version_root.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel_path = py_file.relative_to(version_root.parent)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            entry = classes[node.name]
            entry["files"].append(str(rel_path))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = child.name
                    if not show_private and name.startswith("_"):
                        continue
                    entry["methods"].add(name)
    return classes


def _print_section(title: str, items: list[str]) -> None:
    """Print a header + bulleted item list, or '(none)' if empty."""
    print(f"\n{title}")
    if not items:
        print("  (none)")
        return
    for item in items:
        print(f"  {item}")


def _diff_versions(
    pipeline: str, va: str, vb: str, ca: dict, cb: dict, focus_class: str | None
) -> None:
    """Print a v_a vs v_b diff: classes only-in-each, then per-shared-class method diffs."""
    print(f"\n=== {pipeline} {va} vs {vb} ===")

    if focus_class:
        # Single-class focus mode: skip the all-classes header, just diff the one.
        in_a = focus_class in ca
        in_b = focus_class in cb
        if not in_a and not in_b:
            print(f"\nClass {focus_class!r} not found in either {va} or {vb}.")
            return
        if not in_a:
            print(f"\nClass {focus_class!r} is only in {vb} (file: {cb[focus_class]['files']}).")
            return
        if not in_b:
            print(f"\nClass {focus_class!r} is only in {va} (file: {ca[focus_class]['files']}).")
            return
        ma, mb = ca[focus_class]["methods"], cb[focus_class]["methods"]
        only_a = sorted(ma - mb)
        only_b = sorted(mb - ma)
        print(f"\n{focus_class}:")
        print(f"  only in {va}: {', '.join(only_a) if only_a else '(none)'}")
        print(f"  only in {vb}: {', '.join(only_b) if only_b else '(none)'}")
        return

    only_a_classes = sorted(set(ca) - set(cb))
    only_b_classes = sorted(set(cb) - set(ca))

    _print_section(
        f"Classes only in {va}:",
        [f"{name}  (file: {ca[name]['files'][0]})" for name in only_a_classes],
    )
    _print_section(
        f"Classes only in {vb}:",
        [f"{name}  (file: {cb[name]['files'][0]})" for name in only_b_classes],
    )

    shared = sorted(set(ca) & set(cb))
    differing = []
    identical_count = 0
    for name in shared:
        ma = ca[name]["methods"]
        mb = cb[name]["methods"]
        if ma == mb:
            identical_count += 1
            continue
        only_a = sorted(ma - mb)
        only_b = sorted(mb - ma)
        differing.append((name, only_a, only_b))

    print("\nClass methods that differ (same class name, different methods):")
    if not differing:
        print("  (none)")
    for name, only_a, only_b in differing:
        print(f"  {name}")
        print(f"    only in {va}: {', '.join(only_a) if only_a else '(none)'}")
        print(f"    only in {vb}: {', '.join(only_b) if only_b else '(none)'}")

    print(
        f"\nIdentical class signatures (no methods differ): {identical_count} "
        f"of {len(shared)} shared classes"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See module docstring for full usage and limits.",
    )
    parser.add_argument(
        "pipeline",
        help="Pipeline name under spyglass/ (e.g. spikesorting, lfp, position).",
    )
    parser.add_argument(
        "versions",
        nargs="*",
        help=(
            "Version directories to compare (e.g. v0 v1). Pass two for a "
            "single diff, or omit to auto-discover all and diff each "
            "consecutive pair."
        ),
    )
    parser.add_argument(
        "--src",
        default=None,
        help="Path to Spyglass src/ directory (overrides $SPYGLASS_SRC).",
    )
    parser.add_argument(
        "--class",
        dest="focus_class",
        default=None,
        help="Restrict the diff to a single class name.",
    )
    parser.add_argument(
        "--show-private",
        action="store_true",
        help="Include _-prefixed methods (default: skip).",
    )
    args = parser.parse_args()

    src_root = _resolve_src_root(args.src)
    if not (src_root / "spyglass").is_dir():
        sys.exit(
            f"ERROR: {src_root} does not contain a `spyglass/` package. "
            f"Pass --src pointing at the src/ dir of a Spyglass checkout."
        )

    versions = list(args.versions)
    if not versions:
        versions = _list_versions(src_root, args.pipeline)
        if not versions:
            available = _list_pipelines(src_root)
            sys.exit(
                f"ERROR: no version directories found under "
                f"spyglass/{args.pipeline}/. Available pipelines: "
                f"{', '.join(available) if available else '(none)'}."
            )
        if len(versions) < 2:
            print(
                f"Only one version present under spyglass/{args.pipeline}/: "
                f"{versions[0]}. No comparison possible."
            )
            return 0
        print(
            f"Auto-discovered versions under spyglass/{args.pipeline}/: "
            f"{', '.join(versions)}"
        )

    if len(versions) < 2:
        sys.exit("ERROR: need at least two versions to compare.")

    # Validate every named version exists before scanning anything.
    for v in versions:
        vroot = src_root / "spyglass" / args.pipeline / v
        if not vroot.is_dir():
            available = _list_versions(src_root, args.pipeline)
            sys.exit(
                f"ERROR: spyglass/{args.pipeline}/{v}/ does not exist. "
                f"Available: {', '.join(available) if available else '(none)'}."
            )

    scans = {
        v: _scan_version(
            src_root / "spyglass" / args.pipeline / v, args.show_private
        )
        for v in versions
    }

    for va, vb in zip(versions, versions[1:]):
        _diff_versions(args.pipeline, va, vb, scans[va], scans[vb], args.focus_class)

    return 0


if __name__ == "__main__":
    sys.exit(main())
