#!/usr/bin/env python3
"""Runnable-example import harness for the Spyglass skill.

For every ```python block in the skill's .md files, parses AST and
checks every `Import` / `ImportFrom` node. An import fails the harness
when the top-level package IS installed but the specific module or
attribute doesn't resolve — that's a real bug in the skill's example.
Imports are skipped (not failed) when the top-level package isn't
installed or the import raises a non-ModuleNotFoundError at runtime;
those are environment issues, not authoring errors.

Deliberately separate from validate_skill.py: that validator runs on
offline AST data and must not require spyglass (or its optional extras
like DLC/moseq) to be importable. This harness DOES import the target
modules, so it runs as an opt-in check:

    python3 spyglass/tests/test_runnable_imports.py --spyglass-src PATH

Exit codes:
    0: every import either resolved or was skipped as env noise
    1: at least one import resolved to a real missing module or attr
"""

import argparse
import ast
import importlib
import importlib.util
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REFERENCES_DIR = SKILL_DIR / "references"


def collect_md_files():
    """Return [SKILL.md, *sorted(references/*.md)] — same order as the validator."""
    files = [SKILL_DIR / "SKILL.md"]
    files.extend(sorted(REFERENCES_DIR.glob("*.md")))
    return files


def extract_python_blocks(md_path):
    """Yield (block_start_line, body_str) for each ```python block.

    Mirrors validate_skill.py's extract_fenced_blocks but scoped to
    this harness so the two files can be run / edited independently.
    block_start is the 1-indexed line number of the first line inside
    the fence (i.e., the line after ```python).
    """
    content = md_path.read_text()
    in_code = False
    body_lines = []
    block_start = 0
    lang = ""
    for line_num, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                if lang == "python":
                    yield (block_start, "\n".join(body_lines))
                body_lines = []
                lang = ""
            else:
                lang = stripped[3:].strip()
                block_start = line_num + 1
            in_code = not in_code
            continue
        if in_code:
            body_lines.append(line)


def _top_level_installed(module_path):
    """True if the first dotted segment of `module_path` is importable.

    Used to distinguish "env doesn't have spyglass at all — skip" from
    "env has spyglass but example references a missing submodule —
    fail". Wrapped in try/except because find_spec itself can raise
    (e.g., parent package import side effects) and we treat all those
    as env noise.
    """
    top = module_path.split(".")[0]
    try:
        return importlib.util.find_spec(top) is not None
    except Exception:
        return False


def _classify_import_error(module_path, err):
    """Return "fail" if `err` means the submodule genuinely doesn't exist,
    "skip" if it looks like environment noise (config error, missing
    extra, etc.).

    Heuristic: ModuleNotFoundError whose message names a spyglass.*
    submodule suggests a typo/rename in the skill example. Any other
    exception (or ModuleNotFoundError about an unrelated third-party
    package like `sklearn_crfsuite`) indicates the target package's
    own deps aren't installed — the skill wouldn't fail in a properly
    configured env, so don't block on it here.
    """
    if not isinstance(err, ModuleNotFoundError):
        return "skip"
    # ModuleNotFoundError.name is the missing module's dotted path
    missing = getattr(err, "name", None) or ""
    # If the error is about the module we asked for (or a parent of it),
    # the skill's example references something that genuinely doesn't
    # exist. If the error is about a different package, it's a missing
    # extra / optional dep, and the skill isn't at fault.
    if missing and (missing == module_path
                    or module_path.startswith(missing + ".")):
        return "fail"
    return "skip"


def _check_import_from(node, block_start, md_name, results):
    """Handle `from X import Y1, Y2, ...` at `node`."""
    module_path = node.module
    line_num = block_start + node.lineno - 1
    location = f"{md_name}:{line_num}"
    if not module_path:
        return  # relative import; not meaningful here
    if not _top_level_installed(module_path):
        results["skipped"].append(
            f"{location}: skipped — top-level package "
            f"'{module_path.split('.')[0]}' not installed"
        )
        return
    try:
        module = importlib.import_module(module_path)
    except Exception as err:
        verdict = _classify_import_error(module_path, err)
        if verdict == "fail":
            results["failed"].append(
                f"{location}: module '{module_path}' not found "
                f"(top-level installed): {type(err).__name__}: {err}"
            )
        else:
            results["skipped"].append(
                f"{location}: skipped — import of '{module_path}' "
                f"raised {type(err).__name__}: {err}"
            )
        return
    for alias in node.names:
        name = alias.name
        if name == "*":
            continue
        if hasattr(module, name):
            results["ok"].append(
                f"{location}: from {module_path} import {name}"
            )
        else:
            results["failed"].append(
                f"{location}: '{name}' NOT exported from '{module_path}'"
            )


def _check_import(node, block_start, md_name, results):
    """Handle `import X[, Y, ...]` and `import X.Y.Z` at `node`."""
    line_num = block_start + node.lineno - 1
    location = f"{md_name}:{line_num}"
    for alias in node.names:
        module_path = alias.name
        if not _top_level_installed(module_path):
            results["skipped"].append(
                f"{location}: skipped — top-level package "
                f"'{module_path.split('.')[0]}' not installed"
            )
            continue
        try:
            importlib.import_module(module_path)
        except Exception as err:
            verdict = _classify_import_error(module_path, err)
            if verdict == "fail":
                results["failed"].append(
                    f"{location}: module '{module_path}' not found "
                    f"(top-level installed): {type(err).__name__}: {err}"
                )
            else:
                results["skipped"].append(
                    f"{location}: skipped — import of '{module_path}' "
                    f"raised {type(err).__name__}: {err}"
                )
            continue
        results["ok"].append(f"{location}: import {module_path}")


def check_imports_in_block(body, block_start, md_name, results):
    """AST-walk a python block body and check every Import / ImportFrom."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        # Broken block — validate_skill.py's check_python_syntax reports
        # these, so stay silent here rather than double-flag.
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            _check_import_from(node, block_start, md_name, results)
        elif isinstance(node, ast.Import):
            _check_import(node, block_start, md_name, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spyglass-src", type=Path, default=None,
        help="Path to spyglass src/ directory (prepended to sys.path)",
    )
    parser.add_argument(
        "--show-skipped", action="store_true",
        help="Show all skip messages (default: collapsed summary only)",
    )
    args = parser.parse_args()

    if args.spyglass_src is not None:
        if not (args.spyglass_src / "spyglass").is_dir():
            print(
                f"ERROR: {args.spyglass_src} is not a spyglass src/ dir",
                file=sys.stderr,
            )
            return 1
        sys.path.insert(0, str(args.spyglass_src))

    results = {"ok": [], "failed": [], "skipped": []}
    for md_file in collect_md_files():
        for block_start, body in extract_python_blocks(md_file):
            check_imports_in_block(body, block_start, md_file.name, results)

    print(
        f"Runnable-import harness: {len(results['ok'])} ok, "
        f"{len(results['failed'])} failed, "
        f"{len(results['skipped'])} skipped"
    )

    if results["failed"]:
        print("\nFAILED:")
        for msg in results["failed"]:
            print(f"  [FAIL] {msg}")

    if results["skipped"]:
        if args.show_skipped:
            print(f"\nSKIPPED ({len(results['skipped'])}):")
            for msg in results["skipped"]:
                print(f"  [skip] {msg}")
        else:
            # Collapsed summary: one line per distinct top-level package
            from collections import Counter
            packages = Counter()
            for msg in results["skipped"]:
                # "... 'pkg' not installed" or "... raised X: ..."
                if "not installed" in msg:
                    # extract the 'pkg' after "'"
                    start = msg.rfind("package '") + len("package '")
                    end = msg.index("'", start)
                    packages[msg[start:end]] += 1
                else:
                    packages["<other import-time error>"] += 1
            print("\nSKIPPED (summary; rerun with --show-skipped for detail):")
            for pkg, count in packages.most_common():
                print(f"  [skip] {pkg}: {count} import(s)")

    return 1 if results["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
