#!/usr/bin/env python3
"""Validate the Spyglass Claude Code skill against the actual codebase.

Uses AST parsing (no database connection needed) to check:
1. Import statements: does the module exist and export the name?
2. Method references: do documented methods exist on their classes?
3. Method signatures: do documented keyword arguments actually exist?

Usage:
    python scripts/validate_skill.py [--spyglass-src PATH]

    # Verbose mode (show passing checks too):
    python scripts/validate_skill.py -v

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

import argparse
import ast
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
REFERENCES_DIR = SKILL_DIR / "references"

# Default spyglass source location — override with --spyglass-src
DEFAULT_SPYGLASS_SRC = Path(__file__).parent.parent.parent.parent.parent / "Documents/GitHub/spyglass/src"

# Patterns to extract from markdown (inside code blocks only)
IMPORT_PATTERN = re.compile(
    r"from\s+(spyglass[\w.]+)\s+import\s+([^#\n]+)"
)
# Match method calls: Table.method( or Table().method(
METHOD_CALL_PATTERN = re.compile(
    r"(\w+)(?:\(\))?\.(\w+)\s*\("
)
# Match keyword arguments: .method(kwarg=
KWARG_PATTERN = re.compile(
    r"(\w+)(?:\(\))?\.(\w+)\s*\([^)]*?(\w+)\s*="
)

# Known classes and the module file that defines them
# Format: "ClassName": "dotted.module.path" (relative to spyglass src)
KNOWN_CLASSES = {
    "PositionOutput": "spyglass/position/position_merge.py",
    "LFPOutput": "spyglass/lfp/lfp_merge.py",
    "SpikeSortingOutput": "spyglass/spikesorting/spikesorting_merge.py",
    "DecodingOutput": "spyglass/decoding/decoding_merge.py",
    "LinearizedPositionOutput": "spyglass/linearization/merge.py",
    "Session": "spyglass/common/common_session.py",
    "IntervalList": "spyglass/common/common_interval.py",
    "Nwbfile": "spyglass/common/common_nwbfile.py",
    "AnalysisNwbfile": "spyglass/common/common_nwbfile.py",
    "ElectrodeGroup": "spyglass/common/common_ephys.py",
    "Electrode": "spyglass/common/common_ephys.py",
    "Raw": "spyglass/common/common_ephys.py",
    "FirFilterParameters": "spyglass/common/common_filter.py",
    "BrainRegion": "spyglass/common/common_region.py",
    "Subject": "spyglass/common/common_subject.py",
    "SortedSpikesGroup": "spyglass/spikesorting/analysis/v1/group.py",
    "UnitSelectionParams": "spyglass/spikesorting/analysis/v1/group.py",
    "UnitAnnotation": "spyglass/spikesorting/analysis/v1/unit_annotation.py",
    "ImportedSpikeSorting": "spyglass/spikesorting/imported.py",
    "CurationV1": "spyglass/spikesorting/v1/curation.py",
    "SortGroup": "spyglass/spikesorting/v1/recording.py",
    "SpikeSorting": "spyglass/spikesorting/v1/sorting.py",
    "SpikeSorterParameters": "spyglass/spikesorting/v1/sorting.py",
    "ArtifactDetection": "spyglass/spikesorting/v1/artifact.py",
    "ArtifactDetectionParameters": "spyglass/spikesorting/v1/artifact.py",
    "MetricCuration": "spyglass/spikesorting/v1/metric_curation.py",
    "LFPElectrodeGroup": "spyglass/lfp/lfp_electrode.py",
    "LFPV1": "spyglass/lfp/v1/lfp.py",
    "LFPBandV1": "spyglass/lfp/analysis/v1/lfp_band.py",
    "LFPArtifactDetection": "spyglass/lfp/v1/lfp_artifact.py",
    "LFPArtifactDetectionParameters": "spyglass/lfp/v1/lfp_artifact.py",
    "TrodesPosParams": "spyglass/position/v1/position_trodes_position.py",
    "TrodesPosV1": "spyglass/position/v1/position_trodes_position.py",
    "DLCPosV1": "spyglass/position/v1/position_dlc_selection.py",
    "ImportedPose": "spyglass/position/v1/imported_pose.py",
    "DLCSmoothInterpParams": "spyglass/position/v1/position_dlc_position.py",
    "DLCCentroidParams": "spyglass/position/v1/position_dlc_centroid.py",
    "DLCOrientationParams": "spyglass/position/v1/position_dlc_orient.py",
    "ClusterlessDecodingV1": "spyglass/decoding/v1/clusterless.py",
    "SortedSpikesDecodingV1": "spyglass/decoding/v1/sorted_spikes.py",
    "DecodingParameters": "spyglass/decoding/v1/core.py",
    "PositionGroup": "spyglass/decoding/v1/core.py",
    "RippleTimesV1": "spyglass/ripple/v1/ripple.py",
    "RippleParameters": "spyglass/ripple/v1/ripple.py",
    "RippleLFPSelection": "spyglass/ripple/v1/ripple.py",
    "MuaEventsV1": "spyglass/mua/v1/mua.py",
    "MuaEventsParameters": "spyglass/mua/v1/mua.py",
    "PoseGroup": "spyglass/behavior/v1/core.py",
    "TrackGraph": "spyglass/linearization/v1/main.py",
    "BodyPart": "spyglass/position/v1/position_dlc_project.py",
    "DLCProject": "spyglass/position/v1/position_dlc_project.py",
    "DLCPoseEstimation": "spyglass/position/v1/position_dlc_pose_estimation.py",
    "DLCSmoothInterp": "spyglass/position/v1/position_dlc_position.py",
    "DLCSmoothInterpCohort": "spyglass/position/v1/position_dlc_cohort.py",
    "DLCCentroid": "spyglass/position/v1/position_dlc_centroid.py",
    "DLCOrientation": "spyglass/position/v1/position_dlc_orient.py",
    "DLCPosSelection": "spyglass/position/v1/position_dlc_selection.py",
    "DLCModel": "spyglass/position/v1/position_dlc_model.py",
    "WaveformFeaturesParams": "spyglass/decoding/v1/waveform_features.py",
    "UnitWaveformFeatures": "spyglass/decoding/v1/waveform_features.py",
    "UnitWaveformFeaturesGroup": "spyglass/decoding/v1/clusterless.py",
    "KacheryZone": "spyglass/sharing/sharing_kachery.py",
    "AnalysisNwbfileKachery": "spyglass/sharing/sharing_kachery.py",
    "LFPBandSelection": "spyglass/lfp/analysis/v1/lfp_band.py",
    "LFPSelection": "spyglass/lfp/v1/lfp.py",
}

# Methods to skip — DataJoint builtins, mixin methods, etc.
SKIP_METHODS = {
    "fetch", "fetch1", "fetch_nwb", "fetch_pynapple",
    "proj", "aggr", "describe", "heading",
    "parents", "children", "insert", "insert1",
    "populate", "delete", "drop",
    "restrict", "restrict_by",
    "merge_view", "merge_restrict", "merge_fetch",
    "merge_get_part", "merge_get_parent",
    "fetch1_dataframe",
    "cautious_delete", "super_delete", "file_like",
    "restrict_by_list", "find_insert_fail",
    "get_fully_defined_key", "ensure_single_entry",
    "load_shared_schemas", "delete_orphans",
    "check_threads", "get_table_storage_usage",
    "get_params_blob_from_key",
    # _Merge methods (inherited, hard to resolve via AST)
    "merge_get_parent_class", "parts", "merge_populate",
    # Part table access patterns (dynamic attributes)
    "CurationV1", "TrodesPosV1", "DLCPosV1", "LFPV1",
    "ImportedSpikeSorting", "CuratedSpikeSorting",
    "ClusterlessDecodingV1", "SortedSpikesDecodingV1",
    "ImportedLFP", "CommonLFP", "CommonPos", "ImportedPose",
    # Common builtins
    "append", "extend", "items", "keys", "values",
    "format", "join", "split", "strip",
    "sum", "mean", "max", "min", "plot",
    "set_ylabel", "set_xlabel", "set_title",
    "imshow", "spines",
    # Pandas
    "where", "idxmax",
}

SKIP_KWARGS = {
    "as_dict", "limit", "format", "log_export",
    "return_restr", "key", "restriction",
    # Matplotlib
    "alpha", "linewidth", "label", "figsize",
    "aspect", "extent", "origin", "cmap",
    "sharex",
}


class ValidationResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []

    def ok(self, msg):
        self.passed.append(msg)

    def fail(self, msg):
        self.failed.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    @property
    def success(self):
        return len(self.failed) == 0


def collect_md_files():
    """Collect all markdown files in the skill directory."""
    files = [SKILL_DIR / "SKILL.md"]
    files.extend(sorted(REFERENCES_DIR.glob("*.md")))
    return files


def extract_code_blocks(content):
    """Extract code block contents with line numbers."""
    blocks = []
    in_code = False
    block_lines = []
    block_start = 0

    for line_num, line in enumerate(content.split("\n"), 1):
        if line.strip().startswith("```"):
            if in_code:
                blocks.append((block_start, block_lines))
                block_lines = []
            else:
                block_start = line_num + 1
            in_code = not in_code
            continue
        if in_code:
            block_lines.append((line_num, line))

    return blocks


def parse_class_from_file(filepath, class_name, include_inherited=True):
    """Parse a Python file with AST and extract method names + signatures.

    If include_inherited=True, also checks base class files for methods
    defined on known Spyglass mixin/base classes.
    """
    try:
        source = filepath.read_text()
        tree = ast.parse(source)
    except (SyntaxError, FileNotFoundError):
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            methods = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    params = []
                    for arg in item.args.args:
                        params.append(arg.arg)
                    for arg in item.args.kwonlyargs:
                        params.append(arg.arg)
                    has_var_keyword = item.args.kwarg is not None
                    methods[item.name] = {
                        "params": params,
                        "has_kwargs": has_var_keyword,
                    }

            if include_inherited:
                # Also check known base class files for inherited methods
                base_files = [
                    ("_Merge", "spyglass/utils/dj_merge_tables.py"),
                    ("SpyglassMixin", "spyglass/utils/dj_mixin.py"),
                    ("CautiousDeleteMixin", "spyglass/utils/mixins/cautious_delete.py"),
                    ("ExportMixin", "spyglass/utils/mixins/export.py"),
                    ("FetchMixin", "spyglass/utils/mixins/fetch.py"),
                    ("HelperMixin", "spyglass/utils/mixins/helpers.py"),
                    ("PopulateMixin", "spyglass/utils/mixins/populate.py"),
                    ("RestrictByMixin", "spyglass/utils/mixins/restrict_by.py"),
                ]
                src_root = filepath
                # Walk up to find src root (parent of "spyglass" dir)
                for _ in range(10):
                    src_root = src_root.parent
                    if (src_root / "spyglass").is_dir():
                        break

                for base_name, base_rel_path in base_files:
                    base_path = src_root / base_rel_path
                    base_methods = parse_class_from_file(
                        base_path, base_name, include_inherited=False
                    )
                    if base_methods:
                        for mname, minfo in base_methods.items():
                            if mname not in methods:
                                methods[mname] = minfo

            return methods
    return None


def _search_name_in_file(src_root, filepath, name, depth=0):
    """Recursively check if name is defined or re-exported from a file."""
    if depth > 5 or not filepath.exists():
        return False
    try:
        source = filepath.read_text()
    except Exception:
        return False

    escaped = re.escape(name)

    # Direct definition
    if (
        re.search(rf"class\s+{escaped}\b", source)
        or re.search(rf"def\s+{escaped}\b", source)
        or re.search(rf"^\s*{escaped}\s*=", source, re.MULTILINE)
    ):
        return True

    # Direct import: from X import name (including multi-line imports)
    if re.search(rf"import\s+.*\b{escaped}\b", source):
        return True
    # Multi-line import: name appears on its own line inside a from...import(...)
    if re.search(rf"^\s*{escaped}\s*[,)]?\s*$", source, re.MULTILINE):
        return True

    # Star import: from X import * — follow into X
    for star_match in re.finditer(
        r"from\s+([\w.]+)\s+import\s+\*", source
    ):
        star_module = star_match.group(1)
        star_parts = star_module.split(".")
        # Try as module file
        star_file = src_root / "/".join(star_parts[:-1]) / f"{star_parts[-1]}.py"
        if not star_file.exists():
            star_file = src_root / "/".join(star_parts) / "__init__.py"
        if _search_name_in_file(src_root, star_file, name, depth + 1):
            return True

    return False


def check_module_exports(src_root, module_path, names, results, location):
    """Check that a module exports the given names."""
    parts = module_path.split(".")
    # Try as module file, then as package __init__
    candidates = [
        src_root / "/".join(parts[:-1]) / f"{parts[-1]}.py",
        src_root / "/".join(parts) / "__init__.py",
    ]
    mod_file = None
    for c in candidates:
        if c.exists():
            mod_file = c
            break

    if mod_file is None:
        for name in names:
            if name and name.isidentifier():
                results.fail(
                    f"{location}: module {module_path} not found"
                )
        return

    for name in names:
        if not name or not name.isidentifier():
            continue
        if _search_name_in_file(src_root, mod_file, name):
            results.ok(f"{location}: {name} found in {module_path}")
        else:
            results.fail(f"{location}: '{name}' NOT FOUND in {module_path}")


def check_imports(src_root, results):
    """Check that all import statements in code blocks are valid."""
    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in block_lines:
                for match in IMPORT_PATTERN.finditer(line):
                    module_path = match.group(1)
                    raw_names = match.group(2)
                    # Handle multi-line imports and trailing comments
                    names = [
                        n.strip().rstrip(",").rstrip(")")
                        for n in raw_names.split(",")
                        if n.strip() and not n.strip().startswith("#")
                    ]
                    location = f"{md_file.name}:{line_num}"
                    check_module_exports(
                        src_root, module_path, names, results, location
                    )


def check_methods(src_root, results):
    """Check that documented method calls reference real methods."""
    # Cache parsed classes
    class_cache = {}

    def get_class_methods(class_name):
        if class_name in class_cache:
            return class_cache[class_name]
        if class_name not in KNOWN_CLASSES:
            class_cache[class_name] = None
            return None
        filepath = src_root / KNOWN_CLASSES[class_name]
        methods = parse_class_from_file(filepath, class_name)
        class_cache[class_name] = methods
        return methods

    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in block_lines:
                for match in METHOD_CALL_PATTERN.finditer(line):
                    class_name = match.group(1)
                    method_name = match.group(2)

                    if method_name in SKIP_METHODS:
                        continue
                    if method_name.startswith("_"):
                        continue

                    methods = get_class_methods(class_name)
                    if methods is None:
                        continue  # Unknown class

                    location = f"{md_file.name}:{line_num}"
                    if method_name in methods:
                        results.ok(
                            f"{location}: {class_name}.{method_name}() exists"
                        )
                    else:
                        results.fail(
                            f"{location}: {class_name}.{method_name}() "
                            f"NOT FOUND on {class_name}"
                        )


def check_kwargs(src_root, results):
    """Check that documented keyword arguments exist in method signatures."""
    class_cache = {}

    def get_class_methods(class_name):
        if class_name in class_cache:
            return class_cache[class_name]
        if class_name not in KNOWN_CLASSES:
            class_cache[class_name] = None
            return None
        filepath = src_root / KNOWN_CLASSES[class_name]
        methods = parse_class_from_file(filepath, class_name)
        class_cache[class_name] = methods
        return methods

    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in block_lines:
                for match in KWARG_PATTERN.finditer(line):
                    class_name = match.group(1)
                    method_name = match.group(2)
                    kwarg_name = match.group(3)

                    if method_name in SKIP_METHODS:
                        continue
                    if kwarg_name in SKIP_KWARGS:
                        continue
                    if method_name.startswith("_"):
                        continue

                    methods = get_class_methods(class_name)
                    if methods is None:
                        continue

                    if method_name not in methods:
                        continue  # Caught by check_methods

                    method_info = methods[method_name]
                    location = f"{md_file.name}:{line_num}"

                    if (
                        kwarg_name in method_info["params"]
                        or method_info["has_kwargs"]
                    ):
                        results.ok(
                            f"{location}: "
                            f"{class_name}.{method_name}({kwarg_name}=) valid"
                        )
                    else:
                        results.fail(
                            f"{location}: "
                            f"{class_name}.{method_name}() has no parameter "
                            f"'{kwarg_name}' "
                            f"(has: {method_info['params']})"
                        )


def check_class_files_exist(src_root, results):
    """Verify all source files in KNOWN_CLASSES exist."""
    checked = set()
    for class_name, rel_path in sorted(KNOWN_CLASSES.items()):
        filepath = src_root / rel_path
        if rel_path in checked:
            continue
        checked.add(rel_path)

        if filepath.exists():
            results.ok(f"source: {rel_path} exists")
        else:
            results.fail(f"source: {rel_path} NOT FOUND")

    # Also check that each class is defined in its file
    for class_name, rel_path in sorted(KNOWN_CLASSES.items()):
        filepath = src_root / rel_path
        if not filepath.exists():
            continue
        try:
            source = filepath.read_text()
            if re.search(rf"class\s+{class_name}\b", source):
                results.ok(f"registry: {class_name} defined in {rel_path}")
            else:
                results.fail(
                    f"registry: {class_name} NOT DEFINED in {rel_path}"
                )
        except Exception as e:
            results.fail(f"registry: cannot read {rel_path}: {e}")


def check_structure(results: ValidationResult):
    """Check structural conventions: TOCs, ref links, trigger precision."""
    # Check that long reference files have a Contents section
    for md_file in sorted(REFERENCES_DIR.glob("*.md")):
        content = md_file.read_text()
        line_count = content.count("\n") + 1
        if line_count > 100 and "## Contents" not in content:
            results.fail(
                f"structure: {md_file.name} is {line_count} lines "
                f"but has no '## Contents' section"
            )
        elif line_count > 100:
            results.ok(f"structure: {md_file.name} has Contents section")

    # Check that every ref file is linked from SKILL.md
    skill_content = (SKILL_DIR / "SKILL.md").read_text()
    for md_file in sorted(REFERENCES_DIR.glob("*.md")):
        ref_name = f"references/{md_file.name}"
        if ref_name in skill_content:
            results.ok(f"structure: {ref_name} linked from SKILL.md")
        else:
            results.fail(
                f"structure: {ref_name} NOT linked from SKILL.md"
            )

    # Check frontmatter for overly broad trigger phrases
    broad_phrases = [
        "neural data analysis",
        "NWB files",
        "DataJoint tables",
        "neuroscience data",
    ]
    # Extract description from frontmatter
    skill_lines = skill_content.split("\n")
    in_frontmatter = False
    description = ""
    for line in skill_lines:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and line.startswith("description:"):
            description = line

    for phrase in broad_phrases:
        if phrase.lower() in description.lower():
            results.warn(
                f"trigger: frontmatter description contains broad phrase "
                f"'{phrase}' which may cause false activations"
            )
        else:
            results.ok(f"trigger: no broad phrase '{phrase}'")


def main():
    parser = argparse.ArgumentParser(
        description="Validate Spyglass skill against codebase (no DB needed)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show passing checks too"
    )
    parser.add_argument(
        "--spyglass-src", type=Path, default=None,
        help="Path to spyglass src/ directory"
    )
    args = parser.parse_args()

    # Find spyglass source
    src_root = args.spyglass_src
    if src_root is None:
        # Try common locations
        candidates = [
            DEFAULT_SPYGLASS_SRC,
            Path.cwd() / "src",
            Path.cwd(),
        ]
        for candidate in candidates:
            if (candidate / "spyglass").is_dir():
                src_root = candidate
                break

    if src_root is None or not (src_root / "spyglass").is_dir():
        print(
            "ERROR: Cannot find spyglass source. "
            "Use --spyglass-src PATH or run from the repo root.",
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("Spyglass Skill Validation (AST-based, no DB needed)")
    print(f"Source: {src_root}")
    print("=" * 60)

    results = ValidationResult()

    print("\n[1/5] Checking source files and class registry...")
    check_class_files_exist(src_root, results)

    print("[2/5] Checking import statements in skill files...")
    check_imports(src_root, results)

    print("[3/5] Checking method references...")
    check_methods(src_root, results)

    print("[4/5] Checking keyword arguments...")
    check_kwargs(src_root, results)

    print("[5/5] Checking skill structure...")
    check_structure(results)

    # Report
    print("\n" + "=" * 60)

    if args.verbose and results.passed:
        print(f"\nPASSED ({len(results.passed)}):")
        for msg in results.passed:
            print(f"  [ok] {msg}")

    if results.warnings:
        print(f"\nWARNINGS ({len(results.warnings)}):")
        for msg in results.warnings:
            print(f"  [warn] {msg}")

    if results.failed:
        print(f"\nFAILED ({len(results.failed)}):")
        for msg in results.failed:
            print(f"  [FAIL] {msg}")

    print(
        f"\nSummary: {len(results.passed)} passed, "
        f"{len(results.warnings)} warnings, "
        f"{len(results.failed)} failed"
    )

    if results.success:
        print("\nAll checks passed.")
    else:
        print("\nSome checks failed — review and fix the skill files.")

    return 0 if results.success else 1


if __name__ == "__main__":
    sys.exit(main())
