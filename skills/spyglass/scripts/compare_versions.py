#!/usr/bin/env python3
"""Compare class/method surface across version directories of a Spyglass pipeline.

Many Spyglass pipelines ship multiple versions side-by-side
(``spyglass/<pipeline>/v0/``, ``v1/``, eventually ``v2/``). The versions
are *partial* refactors: a method present on v0 ``SortGroup`` may be
absent from v1 ``SortGroup`` (and vice versa). Memorizing which methods
differ is brittle; the source itself is the source of truth.

Run this script before naming a method on a *same-named* class across
versions if you're unsure whether the symmetry holds. It AST-parses
each version directory and prints which classes / methods exist in one
version but not the other, against the pinned Spyglass source.

Usage::

    # Compare v0 and v1 (auto-discover all version siblings if you omit them)
    python compare_versions.py spikesorting v0 v1
    python compare_versions.py spikesorting

    # Single class focus
    python compare_versions.py spikesorting v0 v1 --class SortGroup

    # Override the Spyglass source root (defaults to $SPYGLASS_SRC)
    python compare_versions.py spikesorting v0 v1 --src /path/to/spyglass/src

Exit code is always 0 (this is a discovery tool, not a gate).

What this script catches well:
  - Classes present in one version directory but absent from the other.
    Example: v0 ``Curation`` (only in spikesorting/v0/spikesorting_curation.py),
    v1 ``CurationV1`` (only in spikesorting/v1/curation.py).
  - Public methods added to or removed from a *same-named* class.
    Example: v0 ``SortGroup.set_group_by_electrode_group`` and
    ``set_reference_from_list`` are absent from v1 ``SortGroup``, which
    only exposes ``set_group_by_shank``.

What this script does NOT catch (load these out of the source instead):

  1. Cross-class redesigns within a pipeline. v0 ``Curation.insert_curation``
     and v1 ``CurationV1.insert_curation`` look identical to set-math
     because the class names differ — the script reports them as
     "only in v0" / "only in v1" without drawing the link. Read both
     source files when a class is replaced rather than evolved.

  2. Cross-pipeline redesigns. v0 position info lives in
     ``common/common_position.py`` (``IntervalPositionInfo``); v1 lives
     under ``position/v1/``. The script only diffs within one pipeline
     directory, so cross-pipeline moves are invisible. Check ``common/``
     and ``<pipeline>/<pipeline>_merge.py`` for moved surfaces.

  3. Method-signature changes. Same-name methods may have diverged
     signatures (added required kwarg, switched ``self``→``cls``,
     changed default). Example: v0 ``Curation.insert_curation`` takes
     ``sorting_key: dict``; v1 ``CurationV1.insert_curation`` takes
     ``sorting_id: str`` and adds required ``apply_merge``. The script
     reports both have ``insert_curation`` and stops there. Use
     ``inspect.signature(Class.method)`` to compare signatures.

  4. Behavioral changes inside method bodies. v0 ``SpikeSorting.make_compute``
     and v1 ``SpikeSorting.make_compute`` have completely different
     bodies and SI integration paths despite sharing the name. Read the
     source when behavior matters.

  5. Class tier / mixin changes. v0 ``WaveformParameters`` is
     ``dj.Manual``; v1 is ``dj.Lookup``. ``dj.Lookup`` auto-populates
     from ``contents`` on schema declaration; ``dj.Manual`` does not.
     The script counts ``def`` children, not ``bases``. Check
     ``Class.__bases__`` or read the class declaration line.

  6. DataJoint ``definition`` string changes. v0
     ``SpikeSortingRecordingSelection.definition`` keys on
     ``(SortGroup, SortInterval, SpikeSortingPreprocessingParameters,
     LabTeam)``; v1 keys on ``recording_id: uuid`` only. The script
     ignores ``Assign`` nodes entirely. Use ``Table.heading`` or
     ``Table.describe()`` (or read the ``definition`` string).

  7. Module-level functions, not methods. The script only walks
     ``ClassDef`` body. ``_get_artifact_times`` and similar top-level
     helpers in ``spikesorting/v*/artifact.py`` (and the entire
     ``common/common_behav.py`` helper surface) are invisible. Use
     ``grep -n "^def " <version_dir>/`` for module-level helpers.

  8. Private methods (``_*``) skipped by default. Use ``--show-private``
     to include them. Even with the flag, the seven categories above
     remain blind spots.

  9. Re-exports / aliases (theoretical today). If a future v2 imports
     a v1 class via ``from .v1 import X``, the set math will report X
     as "only in v1" because the v2 file has no ``ClassDef`` node for
     it. Verify with the source if a "only in v_N" hit looks suspicious.

For the categories above, the script's silence is not a guarantee of
symmetry — it's a guarantee that *one specific shape* of asymmetry is
absent. Read the source when answer correctness matters.
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
    """Version subdirectories under `spyglass/<pipeline>/` matching `v<N>`.

    Sorted *numerically* by N so v9 sorts before v10. Lexicographic sort
    would put v10 before v9, which would break consecutive-pair diffing
    once a pipeline reaches double-digit versions.
    """
    pipe_root = src_root / "spyglass" / pipeline
    if not pipe_root.is_dir():
        return []
    candidates = [
        p.name
        for p in pipe_root.iterdir()
        if p.is_dir() and len(p.name) >= 2 and p.name[0] == "v" and p.name[1:].isdigit()
    ]
    return sorted(candidates, key=lambda x: int(x[1:]))


def _scan_version(version_root: Path, show_private: bool) -> dict[str, dict]:
    """Walk a version directory, AST-parse each .py, collect class -> info.

    Returns a dict of ``class_name -> {"methods": set[str], "files": list[str]}``.
    Method set is body-level ``def`` only (no nested defs); files list shows
    every module that defines a class with that name (typically one).

    Same-class-name across multiple files in one version directory unions
    the method sets. This is intentional for the typical case of a class
    declared once with a sibling re-export, but it can over-report if two
    files genuinely declare different same-named classes.
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


def _version_has_python_files(version_root: Path) -> bool:
    """True if the directory has at least one parseable .py file.

    Catches the position/v2 case where the version dir exists but holds
    only stale __pycache__/*.pyc — a true scan would silently report
    every class in the *other* version as "only in <other>", which is
    misleading. Better to surface "no python files found" up front.
    """
    return any(version_root.rglob("*.py"))


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
            files_b = ", ".join(cb[focus_class]["files"])
            print(f"\nClass {focus_class!r} is only in {vb} (file: {files_b}).")
            return
        if not in_b:
            files_a = ", ".join(ca[focus_class]["files"])
            print(f"\nClass {focus_class!r} is only in {va} (file: {files_a}).")
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

    # Validate every named version exists and contains parseable python before
    # scanning. An empty version dir (e.g. position/v2/ with only stale .pyc)
    # would otherwise produce a misleading 100%-other-version-only diff.
    empty_versions = []
    for v in versions:
        vroot = src_root / "spyglass" / args.pipeline / v
        if not vroot.is_dir():
            available = _list_versions(src_root, args.pipeline)
            sys.exit(
                f"ERROR: spyglass/{args.pipeline}/{v}/ does not exist. "
                f"Available: {', '.join(available) if available else '(none)'}."
            )
        if not _version_has_python_files(vroot):
            empty_versions.append(v)

    if empty_versions:
        nonempty = [v for v in versions if v not in empty_versions]
        print(
            f"\nNOTICE: spyglass/{args.pipeline}/ has no parseable .py files in: "
            f"{', '.join(empty_versions)}. These versions are likely unborn or "
            f"excised package shells (e.g. only __pycache__/*.pyc remains). "
            f"Skipping them to avoid a misleading diff."
        )
        if len(nonempty) < 2:
            print(
                f"After skipping, only {nonempty or '(no)'} version(s) remain "
                f"with python files. No comparison possible."
            )
            return 0
        versions = nonempty

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
