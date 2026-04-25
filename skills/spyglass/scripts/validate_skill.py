#!/usr/bin/env python3
"""Validate the Spyglass Claude Code skill against the actual codebase.

Uses AST parsing (no database connection needed) to check:
1. Import statements: does the module exist and export the name?
2. Method references: do documented methods exist on their classes?
3. Method signatures: do documented keyword arguments actually exist?

Usage:
    python3 scripts/validate_skill.py [--spyglass-src PATH]

    # Verbose mode (show passing checks too):
    python3 scripts/validate_skill.py -v

    # (Use `python3` explicitly. On some systems `python` points to Python 2
    # or is missing entirely; the file contains non-ASCII characters and
    # relies on Python 3's default UTF-8 source decoding.)

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

import argparse
import ast
import json
import re
import sys
import textwrap
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
REFERENCES_DIR = SKILL_DIR / "references"

# No hardcoded default — use --spyglass-src or run from the repo root
DEFAULT_SPYGLASS_SRC = None

# Import / method-call / kwarg extraction all now go through the AST walk
# in iter_python_blocks. Regex was retired in the Phase 1 refactor —
# Method-call and kwarg extraction are done via AST walk (see
# iter_python_blocks / resolve_receiver / check_methods / check_kwargs).
# A single AST walker replaces the previous regex-based scan so that aliased
# imports (`from spyglass.common import Session as Sess`) and module-qualified
# receivers (`import spyglass.common as sgc; sgc.Session.fetch()`) — both
# common in real notebooks — resolve correctly to their canonical classes.

# The five merge masters — tables that inherit from `_Merge` in Spyglass.
# Source of truth for check_merge_registry, which cross-checks this tuple
# against (a) the actual `_Merge` subclasses in Spyglass source and
# (b) the registry table in references/merge_methods.md. Adding a class
# here without adding it to merge_methods.md's registry (or vice versa)
# is a test failure; upstream adding a new `_Merge` subclass without
# updating this tuple is also a test failure.
MERGE_MASTERS = (
    "PositionOutput",
    "LFPOutput",
    "SpikeSortingOutput",
    "DecodingOutput",
    "LinearizedPositionOutput",
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
    "UserEnvironment": "spyglass/common/common_user.py",
    "PositionSource": "spyglass/common/common_behav.py",
    "IntervalPositionInfoSelection": "spyglass/common/common_position.py",
    "IntervalPositionInfo": "spyglass/common/common_position.py",
    "SortedSpikesGroup": "spyglass/spikesorting/analysis/v1/group.py",
    "UnitSelectionParams": "spyglass/spikesorting/analysis/v1/group.py",
    "UnitAnnotation": "spyglass/spikesorting/analysis/v1/unit_annotation.py",
    "ImportedSpikeSorting": "spyglass/spikesorting/imported.py",
    "CurationV1": "spyglass/spikesorting/v1/curation.py",
    "BurstPairParams": "spyglass/spikesorting/v1/burst_curation.py",
    "BurstPairSelection": "spyglass/spikesorting/v1/burst_curation.py",
    "BurstPair": "spyglass/spikesorting/v1/burst_curation.py",
    "SortGroup": "spyglass/spikesorting/v1/recording.py",
    "SpikeSorting": "spyglass/spikesorting/v1/sorting.py",
    "SpikeSorterParameters": "spyglass/spikesorting/v1/sorting.py",
    # Ambiguous between v0 and v1 — skill documents v1
    "SpikeSortingRecordingSelection": "spyglass/spikesorting/v1/recording.py",
    "SpikeSortingRecording": "spyglass/spikesorting/v1/recording.py",
    "SpikeSortingSelection": "spyglass/spikesorting/v1/sorting.py",
    "SpikeSortingPreprocessingParameters": "spyglass/spikesorting/v1/recording.py",
    "ArtifactDetectionSelection": "spyglass/spikesorting/v1/artifact.py",
    "WaveformParameters": "spyglass/spikesorting/v1/metric_curation.py",
    "MetricParameters": "spyglass/spikesorting/v1/metric_curation.py",
    "LinearizationParameters": "spyglass/linearization/v1/main.py",
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
    "ClusterlessDecodingSelection": "spyglass/decoding/v1/clusterless.py",
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
    "DLCPoseEstimationSelection": "spyglass/position/v1/position_dlc_pose_estimation.py",
    "DLCSmoothInterp": "spyglass/position/v1/position_dlc_position.py",
    "DLCSmoothInterpSelection": "spyglass/position/v1/position_dlc_position.py",
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
    "ExportSelection": "spyglass/common/common_usage.py",
    "Export": "spyglass/common/common_usage.py",
    "InsertError": "spyglass/common/common_usage.py",
    "FigURLCurationSelection": "spyglass/spikesorting/v1/figurl_curation.py",
    "FigURLCuration": "spyglass/spikesorting/v1/figurl_curation.py",
    # Ambiguous between v0 and v1 — skill documents v1
    "RecordingRecomputeVersions": "spyglass/spikesorting/v1/recompute.py",
}

# Methods to skip — DataJoint builtins, mixin methods, etc.
SKIP_METHODS = {
    # DataJoint builtins — always valid on any table, no point checking
    "fetch", "fetch1", "fetch_nwb", "fetch_pynapple",
    "proj", "aggr", "describe", "heading",
    "parents", "children", "ancestors", "descendants",
    "insert", "insert1",
    "populate", "delete", "drop", "alter",
    # Note: insert_selection is a Spyglass convention (not DataJoint) and IS
    # validated when called on known classes — it's deliberately absent here.
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
    "merge_delete", "merge_delete_parent",
    # AnalysisMixin methods (inherited by AnalysisNwbfile via SpyglassAnalysis,
    # so method resolution via parse_class_from_file finds nothing on the
    # class itself — the real definitions live in utils/mixins/analysis.py)
    "add_nwb_object", "add_units", "build",
    # "create" and "add" are generic names, but within the skill they're
    # only documented on AnalysisNwbfile (inherited from AnalysisMixin).
    # Listed last in this section so the intent stays clear.
    "create", "add",
    # Common builtins
    "append", "extend", "items", "keys", "values",
    "format", "join", "split", "strip",
    "sum", "mean", "max", "min", "plot",
    "set_ylabel", "set_xlabel", "set_title",
    "imshow", "spines",
    # Pandas
    "where", "idxmax",
}

# Uppercase-first identifiers that appear before a `.method(` but are NOT
# Spyglass classes — doc placeholders, generic table stand-ins, or
# dynamic part-table attribute patterns like `PositionOutput.DLCPosV1`
# where the outer Class.Attr chain surfaces the part name as the receiver.
# Without this set, the unresolved-class warning would fire spuriously
# on any of these names. Part table entries used to live in SKIP_METHODS
# alongside method names; pulled out here so the semantic boundary is
# obvious (method-skip vs. class-placeholder-skip).
DOC_PLACEHOLDERS = {
    # Generic doc-example stand-ins
    "Table", "Table1", "Table2", "MergeTable",
    "MyTable", "SomeTable", "UpstreamTable", "UpstreamA", "UpstreamB",
    "ParamTable", "SelectionTable",
    # Part-table names accessed via dynamic attribute on merge masters
    # (e.g., `PositionOutput.DLCPosV1.fetch_nwb()`). Listed here rather
    # than in KNOWN_CLASSES because they're part-table references, not
    # top-level classes the skill documents.
    "CurationV1", "TrodesPosV1", "DLCPosV1", "LFPV1",
    "ImportedSpikeSorting", "CuratedSpikeSorting",
    "ClusterlessDecodingV1", "SortedSpikesDecodingV1",
    "ImportedLFP", "CommonLFP", "CommonPos", "ImportedPose",
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


def extract_fenced_blocks(content):
    """Like extract_code_blocks, but also yields the fence language tag.

    Returns (start_line, lang, body_source_str) triples. `lang` is the string
    after the opening ``` (empty string if the block has no language tag).
    Use this when a check needs to know whether a block is marked as python.
    """
    blocks = []
    in_code = False
    body = []
    block_start = 0
    lang = ""

    for line_num, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                # `textwrap.dedent` is conservative: strips the common leading
                # whitespace of all lines, so list-nested fences (3-space indent)
                # parse under ast.parse. Blocks with mixed indentation get a
                # zero-char common prefix and pass through unchanged.
                blocks.append((block_start, lang, textwrap.dedent("\n".join(body))))
                body = []
                lang = ""
            else:
                lang = stripped[3:].strip()
                block_start = line_num + 1
            in_code = not in_code
            continue
        if in_code:
            body.append(line)

    return blocks


def iter_python_blocks(md_file):
    """Yield (block_start_line, tree) for each ```python block that parses.

    Blocks whose source fails ast.parse() are skipped here (check_python_syntax
    reports those separately). Downstream callers should use this instead of
    regex-scanning code lines — the AST handles multi-line calls natively and
    lets aliased / module-qualified receivers resolve via build_alias_map.
    """
    content = md_file.read_text()
    for block_start, lang, body in extract_fenced_blocks(content):
        if lang != "python":
            continue
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        yield block_start, tree


def build_alias_map(tree):
    """Build {local_name: canonical_name} for spyglass imports in one block.

    Maps:
      from spyglass.X import Name          -> {"Name": "Name"}
      from spyglass.X import Name as Alias -> {"Alias": "Name"}
      import spyglass.X as sgc             -> {"sgc": "<module:spyglass.X>"}
      import spyglass.X                    -> {"spyglass": "<module:spyglass>"}

    The "<module:...>" sentinel tells resolve_receiver that the local name is
    a module binding rather than a class — so `sgc.Session` must go one attr
    deeper to find the class. Non-spyglass imports are ignored.
    """
    alias_map = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith("spyglass"):
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                alias_map[local] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("spyglass"):
                    continue
                if alias.asname:
                    alias_map[alias.asname] = f"<module:{alias.name}>"
                else:
                    # `import spyglass.common` binds `spyglass` locally
                    local = alias.name.split(".")[0]
                    alias_map[local] = f"<module:{alias.name}>"
    return alias_map


def resolve_receiver(call_node, alias_map):
    """Resolve a Call's receiver to (class_name, is_instance_call, lineno).

    Returns None for receivers we intentionally don't validate:
    - BinOp (e.g., `(Table & key).method()` — restriction expressions)
    - complex expressions (lambdas, subscripts, conditional exprs)
    - plain module accesses (`sgc.some_func()` — no class in between)
    - lowercase variable names (instance vars like `sel.start_export`)

    Handled shapes:
    - Class.method()          → ("Class", False)
    - Class().method()        → ("Class", True)
    - alias.method()          → (alias_map[alias], False) if alias is a class
    - module_alias.Class.method()   → ("Class", False)
    - module_alias.Class().method() → ("Class", True)
    """
    if not isinstance(call_node.func, ast.Attribute):
        return None
    method_attr = call_node.func
    receiver = method_attr.value
    instance_call = False

    # Unwrap `Class()` — instance-construction before method call
    if isinstance(receiver, ast.Call):
        instance_call = True
        receiver = receiver.func

    if isinstance(receiver, ast.Name):
        canonical = alias_map.get(receiver.id, receiver.id)
        if canonical.startswith("<module:"):
            return None  # `module.method()` — no class to validate
        return (canonical, instance_call, method_attr.lineno)

    if isinstance(receiver, ast.Attribute):
        # Walk the chain to its root Name. For `sgc.Session.Part` the chain
        # (in traversal order) is ["Part", "Session"] and the root is Name('sgc').
        chain = []
        node = receiver
        while isinstance(node, ast.Attribute):
            chain.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        root = alias_map.get(node.id, node.id)
        if root.startswith("<module:"):
            # module.Class.method() — the outermost attr is the class
            return (chain[0], instance_call, method_attr.lineno)
        # Class.Attr.method() / other rare chain; leave to future work
        return None

    return None


def parse_class_from_file(filepath, class_name, include_inherited=True):
    """Parse a Python file with AST and extract method names + signatures.

    If include_inherited=True, also checks base class files for methods
    defined on known Spyglass mixin/base classes.

    Each method info includes `is_classmethod`/`is_staticmethod` flags so
    callers can check whether `Class.method(...)` (vs `Class().method(...)`) is valid.
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
                    # Check decorators for classmethod/staticmethod
                    decorators = [
                        d.id if isinstance(d, ast.Name)
                        else d.attr if isinstance(d, ast.Attribute)
                        else ""
                        for d in item.decorator_list
                    ]
                    is_classmethod = "classmethod" in decorators
                    is_staticmethod = "staticmethod" in decorators
                    methods[item.name] = {
                        "params": params,
                        "has_kwargs": has_var_keyword,
                        "is_classmethod": is_classmethod,
                        "is_staticmethod": is_staticmethod,
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


def _resolve_module_file(src_root, module_path):
    """Return the .py file or __init__.py that a dotted spyglass module resolves to."""
    parts = module_path.split(".")
    candidates = [
        src_root / "/".join(parts[:-1]) / f"{parts[-1]}.py",
        src_root / "/".join(parts) / "__init__.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def check_imports(src_root, results):
    """Check that all import statements in code blocks are valid.

    AST-based. `from spyglass.x import a, b` is validated by checking each
    imported name exists in the target module; `import spyglass.x[.y]` is
    validated by resolving the dotted module path to a file/package.
    """
    for md_file in collect_md_files():
        for block_start, tree in iter_python_blocks(md_file):
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_path = node.module
                    if not module_path or not module_path.startswith("spyglass"):
                        continue
                    names = [alias.name for alias in node.names]
                    line_num = block_start + node.lineno - 1
                    location = f"{md_file.name}:{line_num}"
                    check_module_exports(
                        src_root, module_path, names, results, location
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if not alias.name.startswith("spyglass"):
                            continue
                        line_num = block_start + node.lineno - 1
                        location = f"{md_file.name}:{line_num}"
                        mod_file = _resolve_module_file(src_root, alias.name)
                        if mod_file is not None:
                            results.ok(
                                f"{location}: import {alias.name} resolves"
                            )
                        else:
                            results.fail(
                                f"{location}: import {alias.name} — "
                                f"module not found"
                            )


def discover_classes(src_root):
    """Walk the spyglass source tree and index every top-level class definition.

    Returns (discovered, collisions) where:
      discovered: {class_name: repo-relative path} — first hit wins
      collisions: {class_name: [path1, path2, ...]} — names defined in >1 file

    Collisions are returned but NOT warned about here; the caller scopes
    warnings to classes the skill actually references, to keep signal strong.
    """
    discovered = {}
    collisions = {}
    pkg_root = src_root / "spyglass"
    if not pkg_root.is_dir():
        return discovered, collisions
    class_pattern = re.compile(r"^class\s+(\w+)\s*[\(:]", re.MULTILINE)
    for py_file in sorted(pkg_root.rglob("*.py")):
        try:
            source = py_file.read_text()
        except Exception:
            continue
        for match in class_pattern.finditer(source):
            name = match.group(1)
            rel = str(py_file.relative_to(src_root))
            if name in discovered:
                collisions.setdefault(name, [discovered[name]]).append(rel)
            else:
                discovered[name] = rel
    return discovered, collisions


_TABLE_SCHEMA_CACHE = {}


def collect_table_schemas(src_root):
    """Extract DataJoint table schemas from every top-level class under src_root.

    Returns {class_name: {
        "pk":          set[str],  # literal primary-key field names
        "attrs":       set[str],  # literal non-PK attribute names
        "parents":     list[str], # names of tables referenced via `->`
        "projections": list[(new_name, source)],  # from `-> Parent.proj(new='src')`
        "parent_projections":    # {parent_name: {src_name: new_name}} per-parent
            dict[str, dict[str, str]],
    }}.

    The extraction is approximate — we look for `class Foo(...): ...
    definition = \"\"\"...\"\"\"` and parse the string with a small grammar.
    False positives (non-DJ classes with a `definition` string attribute)
    are rare in practice. Cached per src_root to amortize the rglob.
    """
    key = str(src_root)
    cached = _TABLE_SCHEMA_CACHE.get(key)
    if cached is not None:
        return cached
    schemas = {}
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        # Top-level classes only — part tables (nested) are intentionally
        # skipped because users reference them as Parent.Part and our
        # dict-restriction check resolves through the Parent anyway.
        for stmt in tree.body:
            if not isinstance(stmt, ast.ClassDef):
                continue
            definition = _extract_definition_string(stmt)
            if definition is None:
                continue
            parsed = _parse_dj_definition(definition)
            # Name-collision disambiguation: Spyglass has v0 and v1 tables
            # that share class names (SpikeSortingRecordingSelection etc).
            # Prefer the file pinned in KNOWN_CLASSES; otherwise first-wins.
            rel = str(py_file.relative_to(src_root))
            pinned = KNOWN_CLASSES.get(stmt.name)
            if pinned:
                if rel == pinned:
                    schemas[stmt.name] = parsed
                # If this file isn't the pinned one, skip — pinned file's
                # definition wins even if encountered later in the walk.
            elif stmt.name not in schemas:
                schemas[stmt.name] = parsed
    _TABLE_SCHEMA_CACHE[key] = schemas
    return schemas


def _extract_definition_string(class_node):
    """Return the `definition = \"\"\"...\"\"\"` string on a class, or None."""
    for stmt in class_node.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name) or target.id != "definition":
            continue
        if (
            isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            return stmt.value.value
    return None


_DJ_PROJ_RE = re.compile(r"(\w+)\s*=\s*['\"](\w+)['\"]")


def _parse_dj_definition(text):
    """Parse a DataJoint definition string into pk/attrs/parents/projections.

    Grammar (approximate):
      <line>     ::= <comment> | <field> | <parent> | "---" | blank
      <field>    ::= <name> [= <default>] ':' <type> [# <comment>]
      <parent>   ::= '-> ' <TableName> [ '.proj(' <kv_list> ')' ]

    `---` separates PK lines (above) from attribute lines (below).

    `parent_projections` maps `parent_name → {src_name: new_name}` so the
    insert-key resolver can exclude renamed-away source fields when walking
    up. Each parent key appears at most once per class (DataJoint schemas
    don't reference the same parent twice).
    """
    pk, attrs = set(), set()
    parents, projections = [], []
    parent_projections = {}
    in_attrs = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comment
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        if line == "---":
            in_attrs = True
            continue
        dest = attrs if in_attrs else pk
        if line.startswith("->"):
            ref = line[2:].strip()
            # Strip DataJoint modifier tokens like `[nullable]`, `[unique]`
            # that appear between `->` and the target table name.
            ref = re.sub(r"^\[[^\]]+\]\s*", "", ref)
            # Strip trailing punctuation / comma (occasionally present)
            ref = ref.rstrip(",")
            if ".proj(" in ref:
                table_part, proj_part = ref.split(".proj(", 1)
                parent_name = table_part.strip()
                parents.append(parent_name)
                renames = {}
                for match in _DJ_PROJ_RE.finditer(proj_part):
                    new_name, source = match.group(1), match.group(2)
                    projections.append((new_name, source))
                    dest.add(new_name)
                    renames[source] = new_name
                if renames:
                    parent_projections[parent_name] = renames
            else:
                parents.append(ref)
        elif ":" in line:
            name_part = line.split(":", 1)[0].strip()
            # Handle `name = default : type` form
            if "=" in name_part:
                name_part = name_part.split("=", 1)[0].strip()
            if name_part and name_part.replace("_", "").isalnum():
                dest.add(name_part)
    return {"pk": pk, "attrs": attrs, "parents": parents,
            "projections": projections,
            "parent_projections": parent_projections}


def resolve_table_fields(class_name, schemas, _seen=None):
    """Return the transitive set of field names accepted by `class_name`.

    Walks `->` parent references to union inherited PKs into the child's
    accepted-field set. Returns None for unknown classes so the caller
    can distinguish "no schema" from "empty schema".

    `_seen` is copied before each sibling recursion so diamond
    inheritance walks correctly: two parents reaching the same ancestor
    must both fully resolve it, not have the second leg truncated by a
    cycle-guard hit from the first leg's walk.
    """
    if _seen is None:
        _seen = set()
    if class_name in _seen:
        return set()  # cycle guard (rare, but possible with circular FKs)
    _seen.add(class_name)
    schema = schemas.get(class_name)
    if schema is None:
        return None
    fields = set(schema["pk"]) | set(schema["attrs"])
    for parent in schema["parents"]:
        parent_fields = resolve_table_fields(parent, schemas, set(_seen))
        if parent_fields is not None:
            fields |= parent_fields
    return fields


def resolve_insert_fields(class_name, schemas, _seen=None):
    """Return the set of field names valid for inserting into `class_name`,
    or None if any transitive parent can't be resolved (fail-open signal).

    Unlike resolve_table_fields, this applies per-parent projection
    renames: a field renamed by `-> Parent.proj(new='src')` has `src`
    excluded from the valid set and `new` included. Critical for
    catching the Apr 21 linearization bug where
    `LinearizationSelection.insert1({"merge_id": ...})` used the
    un-projected parent field instead of `pos_merge_id`.

    Returning None on *any* unresolvable parent (as opposed to a partial
    union) guarantees callers don't emit false positives when only part
    of the parent chain is known — the whole class is skipped instead.

    `_seen` is copied before each sibling recursion (see
    resolve_table_fields for the diamond-inheritance reasoning). The
    correctness cost of *not* copying is higher here than in
    resolve_table_fields: a truncated second-sibling walk would fail
    to apply that sibling's projection renames, leaving both the
    un-renamed source and the renamed new name in the accepted set.
    """
    if _seen is None:
        _seen = set()
    if class_name in _seen:
        return set()  # cycle guard
    _seen.add(class_name)
    schema = schemas.get(class_name)
    if schema is None:
        return None
    fields = set(schema["pk"]) | set(schema["attrs"])
    parent_projections = schema.get("parent_projections", {})
    for parent in schema["parents"]:
        parent_fields = resolve_insert_fields(parent, schemas, set(_seen))
        if parent_fields is None:
            return None  # parent unresolvable — bail conservatively
        parent_fields = set(parent_fields)
        renames = parent_projections.get(parent, {})
        for src in renames:
            parent_fields.discard(src)
        fields |= parent_fields
        fields |= set(renames.values())
    return fields


class _ClassRegistry:
    """Resolve class names to their parsed method signatures.

    Combines the hand-curated KNOWN_CLASSES map (wins on name collisions)
    with auto-discovered classes from src/spyglass/**/*.py. Caches parse
    results so subsequent checks reuse the same data.
    """

    def __init__(self, src_root, results):
        self.src_root = src_root
        self.results = results
        self.auto_registry, self.collisions = discover_classes(src_root)
        self._cache = {}

    def methods(self, class_name):
        if class_name in self._cache:
            return self._cache[class_name]
        rel_path = (
            KNOWN_CLASSES.get(class_name)
            or self.auto_registry.get(class_name)
        )
        if rel_path is None:
            self._cache[class_name] = None
            return None
        filepath = self.src_root / rel_path
        parsed = parse_class_from_file(filepath, class_name)
        self._cache[class_name] = parsed
        return parsed

    def report_referenced_collisions(self):
        """Warn about v0/v1-style collisions only for classes the skill
        actually references. Avoids noise from unreferenced duplicates."""
        referenced = {
            name for name, parsed in self._cache.items()
            if parsed is not None
        }
        for name in sorted(referenced & self.collisions.keys()):
            if name in KNOWN_CLASSES:
                continue  # explicitly disambiguated
            paths = self.collisions[name]
            self.results.warn(
                f"class '{name}' is referenced by the skill but appears in "
                f"multiple files: {', '.join(paths)}. First wins — add to "
                f"KNOWN_CLASSES to pin the intended version."
            )


def _classify_method_call(
    class_name, method_name, instance_call, registry, results, location,
    warn_on_unresolved_class=True, ok_detail=True,
):
    """Shared policy for "Class.method(...)" / "Class().method(...)" validation.

    Used by both check_methods (AST over code blocks) and
    check_evals_content (regex over evals.json prose) so skip-list
    handling, instance-vs-classmethod dispatch, and the unresolved-class
    warning stay in one place. Emits directly into `results` — returns
    None. Returns early (no emission) on any skip reason.

    `warn_on_unresolved_class` is False for the evals prose path outside
    inline-backtick spans (camelcase prose words like "Uses" would
    otherwise trigger false positives on `Uses .fetch()` constructs).
    `ok_detail` toggles the trailing "(instance call)" / "(class/static
    call)" suffix that check_methods wants but check_evals_content does
    not — the two call sites print slightly different success messages
    and preserving that was simpler than changing the message everywhere.
    """
    if method_name in SKIP_METHODS or method_name.startswith("_"):
        return
    methods = registry.methods(class_name)
    if methods is None:
        if (
            warn_on_unresolved_class
            and class_name[:1].isupper()
            and class_name not in DOC_PLACEHOLDERS
        ):
            results.warn(
                f"{location}: unresolved class '{class_name}' in "
                f"'{class_name}.{method_name}()' — typo, or add to "
                f"KNOWN_CLASSES/DOC_PLACEHOLDERS"
            )
        return
    if method_name not in methods:
        results.fail(
            f"{location}: {class_name}.{method_name}() "
            f"NOT FOUND on {class_name}"
        )
        return
    info = methods[method_name]
    if (
        not instance_call
        and not info.get("is_classmethod")
        and not info.get("is_staticmethod")
    ):
        results.fail(
            f"{location}: {class_name}.{method_name}() is an "
            f"instance method — use {class_name}()."
            f"{method_name}(...)"
        )
        return
    if ok_detail:
        kind = "instance" if instance_call else "class/static"
        results.ok(
            f"{location}: {class_name}.{method_name}() valid ({kind} call)"
        )
    else:
        results.ok(f"{location}: {class_name}.{method_name}() valid")


def check_methods(src_root, results, registry=None):
    """Check that documented method calls reference real methods.

    AST-based. Handles aliased imports, module-qualified receivers, and
    multi-line calls — see iter_python_blocks / resolve_receiver. The
    actual method-resolution policy lives in _classify_method_call so
    check_evals_content can share it.
    """
    if registry is None:
        registry = _ClassRegistry(src_root, results)

    for md_file in collect_md_files():
        for block_start, tree in iter_python_blocks(md_file):
            alias_map = build_alias_map(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                method_name = node.func.attr
                if method_name in SKIP_METHODS or method_name.startswith("_"):
                    continue

                resolved = resolve_receiver(node, alias_map)
                if resolved is None:
                    # Unresolvable receiver (BinOp restriction, lowercase var,
                    # complex expression). Match prior regex behavior: skip.
                    continue
                class_name, instance_call, call_line = resolved
                line_num = block_start + call_line - 1
                location = f"{md_file.name}:{line_num}"
                _classify_method_call(
                    class_name, method_name, instance_call,
                    registry, results, location,
                )


def check_kwargs(src_root, results, registry=None):
    """Check that documented keyword arguments exist in method signatures.

    AST-based; shares receiver resolution with check_methods. Uses
    node.keywords directly, so we don't have to re-scan argument text
    with a regex.
    """
    if registry is None:
        registry = _ClassRegistry(src_root, results)

    def get_class_methods(class_name):
        return registry.methods(class_name)

    for md_file in collect_md_files():
        for block_start, tree in iter_python_blocks(md_file):
            alias_map = build_alias_map(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                method_name = node.func.attr
                if method_name in SKIP_METHODS:
                    continue
                if method_name.startswith("_"):
                    continue

                resolved = resolve_receiver(node, alias_map)
                if resolved is None:
                    continue
                class_name, _, call_line = resolved
                line_num = block_start + call_line - 1
                location = f"{md_file.name}:{line_num}"

                methods = get_class_methods(class_name)
                if methods is None or method_name not in methods:
                    continue  # method existence handled by check_methods

                method_info = methods[method_name]
                for kw in node.keywords:
                    if kw.arg is None:  # **kwargs unpacking
                        continue
                    if kw.arg in SKIP_KWARGS:
                        continue
                    if (
                        kw.arg in method_info["params"]
                        or method_info["has_kwargs"]
                    ):
                        results.ok(
                            f"{location}: "
                            f"{class_name}.{method_name}({kw.arg}=) valid"
                        )
                    else:
                        results.fail(
                            f"{location}: "
                            f"{class_name}.{method_name}() has no parameter "
                            f"'{kw.arg}' "
                            f"(has: {method_info['params']})"
                        )


def _extract_arg_list(line, open_paren_idx):
    """Return the text between matched parens starting at open_paren_idx.

    Tracks nested parens/brackets. Returns None if the parens don't close
    within `line` (which for anti-pattern callers is the full block body,
    not a single physical line, so multi-line calls are handled).
    """
    if open_paren_idx >= len(line) or line[open_paren_idx] != "(":
        return None
    depth = 0
    for i in range(open_paren_idx, len(line)):
        ch = line[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return line[open_paren_idx + 1 : i]
    return None


def check_restriction_fields(src_root, results):
    """Warn when a dict restriction uses a key not defined on the table.

    Scans `Class & {"key": ...}` and `Class() & {"key": ...}` expressions in
    python code blocks; compares each literal dict key against the
    transitively-resolved field set from `collect_table_schemas`. Emits a
    warning (not a fail) because the extractor does not cover:

    - part-table references via attribute access (`Parent.Part & {...}`)
    - multi-hop FK inheritance that relies on tables the extractor missed
      (e.g., mixin-provided virtual columns)

    False positives are preferable to noise; every warning is a real
    potential typo worth a human glance. The paradigm case caught: the
    `moseq_model_params_name` typo from the code-review audit — the real
    column is `model_params_name`, and this check would have flagged
    that at skill-write time rather than waiting for a review pass.
    """
    schemas = collect_table_schemas(src_root)
    for md_file in collect_md_files():
        for block_start, tree in iter_python_blocks(md_file):
            alias_map = build_alias_map(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.BinOp):
                    continue
                if not isinstance(node.op, ast.BitAnd):
                    continue
                if not isinstance(node.right, ast.Dict):
                    continue
                # Resolve the left-hand class name. Accept `SomeClass` and
                # `SomeClass()` forms; skip anything else (part-table
                # attribute access, nested BinOps, etc.).
                left = node.left
                if isinstance(left, ast.Call):
                    left = left.func
                if not isinstance(left, ast.Name):
                    continue
                canonical = alias_map.get(left.id, left.id)
                if canonical.startswith("<module:"):
                    continue
                # Merge-table masters have only (merge_id, source); real
                # restrictions go through the underlying part tables,
                # which we can't cheaply resolve statically. Skip to avoid
                # false positives on the canonical
                # `(PositionOutput & {"nwb_file_name": f})` pattern.
                if canonical in MERGE_TABLE_CLASSES:
                    continue
                fields = resolve_table_fields(canonical, schemas)
                if fields is None:
                    continue  # not a known DJ table; skip silently
                line_num = block_start + node.lineno - 1
                location = f"{md_file.name}:{line_num}"
                for key_node in node.right.keys:
                    if not isinstance(key_node, ast.Constant):
                        continue
                    if not isinstance(key_node.value, str):
                        continue
                    key = key_node.value
                    if key not in fields:
                        # Show up to a dozen known fields for context
                        sample = sorted(fields)[:12]
                        hint = ", ".join(sample)
                        if len(fields) > len(sample):
                            hint += ", ..."
                        results.warn(
                            f"{location}: "
                            f"({canonical} & {{\"{key}\": ...}}): "
                            f"field '{key}' not found in schema "
                            f"(known: {hint})"
                        )


# Methods whose first positional arg is an insert-shaped dict (or list of
# dicts). For `populate`, the dict is a restriction — same key-shape check.
# `insert_selection` is a Spyglass convention that mirrors insert1 semantics.
_INSERT_SHAPED_METHODS = frozenset({
    "insert1", "insert", "populate", "insert_selection",
})


def check_insert_key_shape(src_root, results):
    """Warn when `Class.insert1/insert/populate/insert_selection({...})`
    uses dict keys that don't exist in the table's schema (after projections).

    Would have caught the Apr 21 `linearization_pipeline.md` bug:
    `LinearizationSelection.insert1({"merge_id": ..., "interval_list_name": ...})`
    used the un-projected parent field `merge_id` (real name: `pos_merge_id`)
    and an extraneous `interval_list_name` field that isn't in the schema.

    Fail-open: if the class isn't discoverable, any transitive parent can't
    be resolved, or the dict uses `**spread`, the whole call is skipped
    rather than emit a false positive. Warning (not failure) because the
    parser is approximate — see resolve_insert_fields for the projection
    semantics we apply.
    """
    schemas = collect_table_schemas(src_root)
    for md_file in collect_md_files():
        for block_start, tree in iter_python_blocks(md_file):
            alias_map = build_alias_map(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                method_name = node.func.attr
                if method_name not in _INSERT_SHAPED_METHODS:
                    continue
                if not node.args:
                    continue
                resolved = resolve_receiver(node, alias_map)
                if resolved is None:
                    continue
                class_name, _instance_call, call_line = resolved
                valid_fields = resolve_insert_fields(class_name, schemas)
                if valid_fields is None:
                    continue  # unknown class or unresolvable parent → fail-open

                first_arg = node.args[0]
                if isinstance(first_arg, ast.Dict):
                    dicts = [first_arg]
                elif isinstance(first_arg, ast.List):
                    dicts = [
                        elt for elt in first_arg.elts
                        if isinstance(elt, ast.Dict)
                    ]
                else:
                    continue  # variable / query / tuple — can't verify

                for d in dicts:
                    # `**spread` — ast records None as the key. Skip the
                    # whole dict: we can't enumerate what those keys are.
                    if any(k is None for k in d.keys):
                        continue
                    line_num = block_start + call_line - 1
                    location = f"{md_file.name}:{line_num}"
                    for key_node in d.keys:
                        if not isinstance(key_node, ast.Constant):
                            continue
                        if not isinstance(key_node.value, str):
                            continue
                        key = key_node.value
                        if key in valid_fields:
                            continue
                        sample = sorted(valid_fields)[:12]
                        hint = ", ".join(sample)
                        if len(valid_fields) > len(sample):
                            hint += ", ..."
                        results.warn(
                            f"{location}: "
                            f"{class_name}.{method_name}({{\"{key}\": ...}}): "
                            f"key '{key}' not in schema "
                            f"(known: {hint})"
                        )


def check_class_files_exist(src_root, results):
    """Verify all source files in KNOWN_CLASSES exist."""
    checked = set()
    for _class_name, rel_path in sorted(KNOWN_CLASSES.items()):
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


# Pattern for `class Foo(_Merge, ...)` — the canonical shape for Spyglass
# merge masters. Tolerates whitespace and additional base classes. Does NOT
# match `class Foo(Merge, ...)` because merge_masters uniformly use the
# `_Merge` alias; if upstream changes that convention we'll see both
# directions fail in check_merge_registry and can update intentionally.
# Assumes `_Merge` is the FIRST base class — the invariant holds across
# all current Spyglass merge files. A future `class Foo(SpyglassMixin,
# _Merge, ...)` would silently evade this regex; if that style lands
# upstream the check_merge_registry failure mode is a spurious "merge
# master in MERGE_MASTERS but not in source" and the fix is to broaden
# the pattern.
_MERGE_SUBCLASS_RE = re.compile(r"^class\s+(\w+)\s*\(\s*_Merge\s*[,)]", re.M)

# Pattern for `_Merge` imports so we can confirm the alias resolves before
# scanning for subclasses. If upstream drops the alias entirely the grep
# returns nothing and the subsequent mismatch is the correct failure shape.
_MERGE_ALIAS_ASSIGN_RE = re.compile(r"^_Merge\s*=\s*Merge\b", re.M)


def _discover_merge_masters_in_source(src_root):
    """Return the set of class names that inherit `_Merge` in Spyglass source.

    Scans every .py file under src_root/spyglass/. Uses a regex on the
    `class Foo(_Merge, ...)` shape rather than AST parsing — this is
    stable across Spyglass versions (the pattern hasn't changed in years)
    and avoids paying ast.parse cost on every src file. The regex is
    anchored at line start with MULTILINE so nested/sample code in
    docstrings doesn't produce false positives.
    """
    found = set()
    for py in (src_root / "spyglass").rglob("*.py"):
        try:
            text = py.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for m in _MERGE_SUBCLASS_RE.finditer(text):
            found.add(m.group(1))
    return found


def _parse_merge_registry_from_markdown():
    """Extract the claimed merge-master set and the NOT-a-merge set from
    merge_methods.md. Returns (claimed_merges, claimed_non_merges,
    notmerge_marker_found) — the third element lets the caller
    distinguish "marker present, no entries found" (returns `set()`)
    from "marker missing entirely" (the NOT-a-merge subcheck can't run).

    The registry table is recognized by the `## Is this a merge table?`
    heading and is parsed row-by-row; each row's first backticked token
    is the class name. The NOT-a-merge list is parsed from the bullet
    list that follows (`- `... `ClassName` ...`); every backticked
    CamelCase identifier in those bullets counts. The bolded marker
    `**Common lookalikes that are NOT merge tables` is load-bearing —
    if it moves or is renamed the parser signals `marker_found=False`
    so check_merge_registry can fail loudly rather than silently skip.
    """
    merge_md = REFERENCES_DIR / "merge_methods.md"
    if not merge_md.exists():
        return set(), set(), False
    text = merge_md.read_text()

    # Slice to the registry section (through the next H2).
    match = re.search(
        r"##\s+Is this a merge table\?(.*?)(?=\n##\s)",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return set(), set(), False
    section = match.group(1)

    # Split at the NOT-a-merge marker. If the marker isn't in `section`,
    # `split` has length 1 — we preserve that signal via `marker_found`
    # so the caller can fail loudly rather than silently skip check (3).
    split = re.split(r"\*\*Common lookalikes that are NOT merge tables", section)
    marker_found = len(split) > 1
    registry_half = split[0]
    notmerge_half = split[1] if marker_found else ""

    # Registry table rows: `| \`ClassName\` (...) | ...`. Capture the first
    # backticked token per row; skip the header + divider rows by requiring
    # the token start with an uppercase letter and match a bare identifier.
    claimed_merges = set()
    for line in registry_half.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        tokens = re.findall(r"`([A-Z]\w+)`", line)
        if tokens:
            claimed_merges.add(tokens[0])

    # NOT-a-merge bullets: every backticked CamelCase identifier counts.
    claimed_non_merges = set()
    for tok in re.findall(r"`([A-Z]\w+)`", notmerge_half):
        claimed_non_merges.add(tok)

    return claimed_merges, claimed_non_merges, marker_found


def check_merge_registry(src_root, results):
    """Cross-check the merge-table registry three ways.

    1. MERGE_MASTERS tuple ↔ Spyglass source: every listed class must
       inherit `_Merge` upstream; every `_Merge` subclass upstream must be
       in MERGE_MASTERS. Catches renames, deletions, and new merge masters
       added upstream that the skill hasn't picked up yet.

    2. MERGE_MASTERS tuple ↔ merge_methods.md registry table: the two must
       agree. Catches editing one without the other.

    3. merge_methods.md NOT-a-merge list ↔ source: none of those classes
       may actually inherit `_Merge`. Catches the inverse misclassification
       (skill says X isn't a merge, but upstream made it one).

    The `_Merge` alias itself is checked — if it disappears from
    dj_merge_tables.py the subsequent scan returns empty and every
    comparison fails. That's the right shape: the skill's whole mental
    model depends on the alias, so its loss should fail noisily.
    """
    # Sanity: `_Merge = Merge` alias still present in Spyglass?
    alias_file = src_root / "spyglass/utils/dj_merge_tables.py"
    if not alias_file.exists():
        results.fail(
            "merge-registry: dj_merge_tables.py missing — "
            "check_merge_registry cannot run"
        )
        return
    alias_text = alias_file.read_text()
    if not _MERGE_ALIAS_ASSIGN_RE.search(alias_text):
        results.warn(
            "merge-registry: `_Merge = Merge` alias not found in "
            "dj_merge_tables.py — subsequent subclass scan uses the "
            "alias name and may under-count"
        )

    source_merges = _discover_merge_masters_in_source(src_root)
    tuple_merges = set(MERGE_MASTERS)

    # (1) tuple ↔ source
    missing_in_source = tuple_merges - source_merges
    for name in sorted(missing_in_source):
        results.fail(
            f"merge-registry: MERGE_MASTERS lists `{name}` but no "
            f"`class {name}(_Merge, ...)` in Spyglass source — renamed, "
            f"removed, or reclassified upstream"
        )
    extra_in_source = source_merges - tuple_merges
    for name in sorted(extra_in_source):
        results.fail(
            f"merge-registry: `class {name}(_Merge, ...)` exists in "
            f"Spyglass source but is not in MERGE_MASTERS — new merge "
            f"master upstream; update validate_skill.py MERGE_MASTERS "
            f"and merge_methods.md § Is this a merge table?"
        )
    if not missing_in_source and not extra_in_source:
        results.ok(
            f"merge-registry: {len(tuple_merges)} merge masters in "
            f"MERGE_MASTERS match Spyglass source"
        )

    # (2) tuple ↔ merge_methods.md registry table
    (
        claimed_merges,
        claimed_non_merges,
        notmerge_marker_found,
    ) = _parse_merge_registry_from_markdown()
    if not claimed_merges:
        results.fail(
            "merge-registry: could not parse `## Is this a merge table?` "
            "section from merge_methods.md — section renamed or table "
            "format changed"
        )
    else:
        tuple_not_in_md = tuple_merges - claimed_merges
        for name in sorted(tuple_not_in_md):
            results.fail(
                f"merge-registry: `{name}` is in MERGE_MASTERS but missing "
                f"from merge_methods.md registry table"
            )
        md_not_in_tuple = claimed_merges - tuple_merges
        for name in sorted(md_not_in_tuple):
            results.fail(
                f"merge-registry: `{name}` is claimed as a merge master "
                f"in merge_methods.md but not in MERGE_MASTERS"
            )
        if not tuple_not_in_md and not md_not_in_tuple:
            results.ok(
                "merge-registry: merge_methods.md registry table "
                "matches MERGE_MASTERS"
            )

    # (3) NOT-a-merge list ↔ source
    if not notmerge_marker_found:
        results.fail(
            "merge-registry: `**Common lookalikes that are NOT merge "
            "tables` marker missing from merge_methods.md — "
            "check (3) cannot run. Restore the bold marker or update "
            "_parse_merge_registry_from_markdown to use the new shape."
        )
    else:
        for name in sorted(claimed_non_merges):
            if name in source_merges:
                results.fail(
                    f"merge-registry: merge_methods.md lists `{name}` as "
                    f"NOT a merge, but upstream `class {name}(_Merge, "
                    f"...)` exists — skill contradicts source"
                )
        if claimed_non_merges and not (claimed_non_merges & source_merges):
            results.ok(
                f"merge-registry: {len(claimed_non_merges)} NOT-a-merge "
                f"entries confirmed as non-_Merge in source"
            )


def check_prose_assertions(results: ValidationResult):
    """Check a small set of high-risk prose claims for drift.

    These are assertions whose wording matters for LLM correctness but lives
    outside code blocks. Each rule pairs a required statement with an ID so
    reviewers can add/remove rules without hunting for magic strings.

    The `needle` field accepts either a single string (pass if that
    substring is present, case-insensitive) or a list of strings (pass if
    ANY alternative is present). Grouped alternatives let a rule survive
    benign rewording — e.g. the "destructive confirmation" rule can accept
    either "explicit confirmation" or "user confirmation" without
    needing the skill to pick one phrasing forever.
    """
    # (file, rule_id, description, needle: str | list[str])
    # needle is case-insensitive. Use a list when equivalent phrasings
    # should all pass — the rule fires if NONE of the alternatives match.
    required_claims = [
        (
            "SKILL.md", "destructive-list",
            "SKILL.md fences merge-table delete helpers",
            "merge_delete",
        ),
        (
            "SKILL.md", "destructive-confirmation",
            "SKILL.md requires explicit confirmation for destructive ops",
            # Grouped alternatives — any of these wordings satisfies the rule
            ["explicit confirmation", "user confirmation",
             "user confirms", "get user confirmation"],
        ),
        (
            "SKILL.md", "schema-verify",
            "SKILL.md tells LLM to verify schema before querying",
            "table.describe()",
        ),
        (
            "SKILL.md", "pip-install-path",
            "SKILL.md tells pip users how to locate installed source",
            "os.path.dirname(spyglass.__file__)",
        ),
        (
            "references/ingestion.md", "filename-convention",
            "ingestion.md distinguishes raw filename vs copy with trailing _",
            "get_nwb_copy_filename",
        ),
        (
            "references/ingestion.md", "skip-duplicates-warning",
            "ingestion.md warns skip_duplicates=True is not for raw data",
            "appropriate for raw data",
        ),
        (
            "SKILL.md", "authoring-stage",
            "SKILL.md's stage classifier includes pipeline authoring",
            "pipeline authoring",
        ),
        (
            "SKILL.md", "authoring-reference-link",
            "SKILL.md links to custom_pipeline_authoring reference",
            "custom_pipeline_authoring.md",
        ),
        (
            "references/custom_pipeline_authoring.md", "authoring-mixin-rule",
            "authoring ref states SpyglassMixin must be first in inheritance",
            "spyglassmixin",
        ),
        (
            "references/custom_pipeline_authoring.md",
            "authoring-analysisnwbfile",
            "authoring ref teaches AnalysisNwbfile storage pattern",
            "analysisnwbfile",
        ),
        (
            "references/custom_pipeline_authoring.md",
            "authoring-selection-separation",
            "authoring ref enforces params/selection/computed separation",
            "keep parameters, selection, and computed tables separate",
        ),
        (
            "references/custom_pipeline_authoring.md",
            "authoring-merge-guardrail",
            "authoring ref warns against merge tables for single-source pipelines",
            "single-source",
        ),
        (
            "references/custom_pipeline_authoring.md",
            "authoring-devdocs-links",
            "authoring ref links to all five ForDevelopers docs",
            "custompipelines.md",  # just check one; the others are tested below
        ),
    ]

    for rel_path, rule_id, description, needle in required_claims:
        md_file = SKILL_DIR / rel_path
        _evaluate_required_claim(md_file, rel_path, rule_id, description,
                                 needle, results)


def _evaluate_required_claim(
    md_file, rel_path, rule_id, description, needle, results
):
    """Evaluate one required-claim rule against a single file.

    Extracted from the loop body so tests can exercise the real
    alternative-matching logic without having to stage a whole mirror
    of SKILL_DIR. Pass any readable file path; mismatch between that
    file and rel_path is fine — rel_path is display-only here.
    """
    if not md_file.exists():
        results.fail(f"prose[{rule_id}]: file {rel_path} not found")
        return
    content = md_file.read_text().lower()
    alternatives = [needle] if isinstance(needle, str) else list(needle)
    if any(alt.lower() in content for alt in alternatives):
        results.ok(f"prose[{rule_id}]: {description}")
    else:
        shown = alternatives[0] if len(alternatives) == 1 else (
            " | ".join(f"'{a}'" for a in alternatives)
        )
        results.fail(
            f"prose[{rule_id}]: {rel_path} missing required claim "
            f"{shown} ({description})"
        )


def _strip_fenced_blocks(content):
    """Return `content` with all fenced blocks replaced by blank lines.

    Preserves line numbers so regex match offsets still correspond to the
    original file, but removes code examples from prose scans — otherwise
    a `# fixed in PR #1234` comment in an example would trigger prose
    checks that should only apply to narrative text.
    """
    out_lines = []
    in_fence = False
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out_lines.append("\n")  # blank placeholder
            continue
        if in_fence:
            out_lines.append("\n")
        else:
            out_lines.append(line)
    return "".join(out_lines)


# Citations like "PR #1234" in prose. Banned because:
#   1. PR numbers are frozen in time; git history reorganizes across branches.
#   2. Prior audits in this skill twice got the direction of a PR wrong
#      (narrative said "bumped from X" when the PR actually pinned to X).
#   3. Current-state citations ("Spyglass currently pins X") stay accurate
#      without depending on the maintainer's memory of PR ordering.
PR_CITATION_PATTERN = re.compile(r"\bPR\s+#\d+\b")


def check_no_pr_citations(results: ValidationResult):
    """Warn on `PR #nnn` citations in reference prose.

    Code blocks are stripped before scanning so example comments don't
    trigger. SKILL.md and every reference .md are scanned.
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        prose = _strip_fenced_blocks(content)
        for m in PR_CITATION_PATTERN.finditer(prose):
            line_num = prose[: m.start()].count("\n") + 1
            results.warn(
                f"{md_file.name}:{line_num}: avoid `{m.group(0)}` in prose — "
                f"cite current source state (e.g. 'current pyproject.toml pins "
                f"X, earlier releases pinned Y') rather than PR history; PR "
                f"numbers are frozen in time and prior audits twice reversed "
                f"the direction of a PR narrative"
            )


# Duplication detector: 5-line rolling window over stripped, non-import,
# non-blank lines. Catches the "bloat via accumulation" failure mode where
# similar examples leak into multiple references during per-PR review.
DUPLICATION_WINDOW_SIZE = 5


def _normalize_block_lines(body):
    """Return (norm_lines, phys_offsets) for a code block body.

    Drops blank lines and pure `from`/`import` statements (too commonly
    shared to meaningfully flag as duplication). `phys_offsets[i]` is the
    0-indexed offset of `norm_lines[i]` within the original block body so
    callers can map a window back to a physical line in the md file.
    """
    norm, offsets = [], []
    for idx, line in enumerate(body.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("import ", "from ")):
            continue
        norm.append(stripped)
        offsets.append(idx)
    return norm, offsets


def check_duplicated_blocks(results: ValidationResult):
    """Warn when a ≥5-line normalized code window appears in 2+ skill files.

    Uses the tuple of normalized lines as the dict key (not Python's
    randomized `hash()`) so false positives cannot arise from hash
    collisions. Within-file repetition is intentionally ignored — the
    failure mode is cross-file drift, not in-file redundancy.

    Overlapping windows that describe the same duplicated block emit a
    single warning: once we report a hit, the 5 normalized-line positions
    it covers in each file are marked visited, and later windows that
    overlap a visited position are skipped.
    """
    # {window_tuple: [(md_file_name, block_start, phys_offset, norm_idx), ...]}
    index = {}
    for md_file in collect_md_files():
        content = md_file.read_text()
        for block_start, lang, body in extract_fenced_blocks(content):
            if lang != "python":
                continue
            norm_lines, phys_offsets = _normalize_block_lines(body)
            if len(norm_lines) < DUPLICATION_WINDOW_SIZE:
                continue
            for i in range(len(norm_lines) - DUPLICATION_WINDOW_SIZE + 1):
                window = tuple(norm_lines[i : i + DUPLICATION_WINDOW_SIZE])
                phys_line = block_start + phys_offsets[i]
                index.setdefault(window, []).append(
                    (md_file.name, phys_line, i, norm_lines[i : i + 3])
                )

    reported_positions = set()  # (filename, norm_idx) — blocks overlap dedup
    any_dup = False
    for hits in index.values():
        # One entry per distinct file (first-seen wins; preserves ordering
        # from sorted collect_md_files()).
        seen_files = {}
        for name, phys_line, norm_idx, first3 in hits:
            if name not in seen_files:
                seen_files[name] = (phys_line, norm_idx, first3)
        if len(seen_files) < 2:
            continue

        # Skip if any file's hit overlaps an already-reported block.
        already = False
        for name, (_, norm_idx, _) in seen_files.items():
            for j in range(norm_idx, norm_idx + DUPLICATION_WINDOW_SIZE):
                if (name, j) in reported_positions:
                    already = True
                    break
            if already:
                break
        if already:
            continue

        for name, (_, norm_idx, _) in seen_files.items():
            for j in range(norm_idx, norm_idx + DUPLICATION_WINDOW_SIZE):
                reported_positions.add((name, j))

        items = sorted(seen_files.items())
        locations = " — ".join(
            f"{name}:{phys_line}" for name, (phys_line, _, _) in items
        )
        preview = " | ".join(items[0][1][2])
        results.warn(
            f"duplication: {locations}: 5+ line code block appears in "
            f"{len(items)} files; first lines: {preview!r}"
        )
        any_dup = True

    if not any_dup:
        results.ok("duplication: no cross-file code block duplication detected")


# Reference-file size budgets. These are soft caps — a reference that
# grows past them is usually carrying bloat or has earned a split.
#   >500 lines: warn (consider splitting; see runtime_debugging.md → the
#               populate_all_common_debugging.md precedent).
#   >700 lines: fail (hard cap — at this point the reference has stopped
#               being skim-able and the progressive-disclosure property
#               of the skill is degraded).
#   H2 subsection >150 lines: warn (a single subsection that large usually
#               duplicates content or should be its own reference).
# SKILL.md is word-capped separately by check_structure(); excluded here.
# Supplementary files under 80 lines are excluded — short intentionally.
REFERENCE_FILE_WARN_LINES = 500
REFERENCE_FILE_FAIL_LINES = 700
H2_SECTION_WARN_LINES = 150
FILE_EXEMPT_BELOW_LINES = 80


def check_section_budgets(results: ValidationResult):
    """Flag reference files or H2 subsections that exceed size budgets.

    Runs over every reference .md (not SKILL.md). Counts whole-file lines
    and per-H2-subsection lines. Emits warnings for soft-cap violations,
    failures for the hard cap.
    """
    for md_file in collect_md_files():
        if md_file.name == "SKILL.md":
            continue
        content = md_file.read_text()
        lines = content.splitlines()
        total = len(lines)
        if total < FILE_EXEMPT_BELOW_LINES:
            continue

        if total > REFERENCE_FILE_FAIL_LINES:
            results.fail(
                f"{md_file.name}: {total} lines exceeds hard cap of "
                f"{REFERENCE_FILE_FAIL_LINES} — split into focused references"
            )
        elif total > REFERENCE_FILE_WARN_LINES:
            results.warn(
                f"{md_file.name}: {total} lines exceeds soft cap of "
                f"{REFERENCE_FILE_WARN_LINES} — consider splitting"
            )
        else:
            results.ok(f"budget: {md_file.name} is {total} lines")

        # Per-H2-subsection line counts. A subsection spans from one `## `
        # heading to the next (or EOF).
        current_heading = None
        current_start = 0
        in_fence = False
        for i, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if line.startswith("## "):
                if current_heading is not None:
                    span = i - current_start
                    if span > H2_SECTION_WARN_LINES:
                        results.warn(
                            f"{md_file.name}:{current_start}: section "
                            f"'{current_heading}' is {span} lines "
                            f"(warn > {H2_SECTION_WARN_LINES})"
                        )
                current_heading = line[3:].strip()
                current_start = i
        if current_heading is not None:
            span = total - current_start + 1
            if span > H2_SECTION_WARN_LINES:
                results.warn(
                    f"{md_file.name}:{current_start}: section "
                    f"'{current_heading}' is {span} lines "
                    f"(warn > {H2_SECTION_WARN_LINES})"
                )


# Small stopword set tuned for Spyglass skill link text. Deliberately
# conservative — better to skip a questionable link than emit noise.
_LINK_TEXT_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "via", "as",
    "is", "are", "was", "were", "be", "been", "being",
    "see", "this", "that", "these", "those", "here", "there",
    "above", "below", "also", "just", "only", "not", "any", "all",
    "its", "their", "it", "using", "file", "page", "section",
    "md", "py", "ipynb",
})


def _extract_content_words(text):
    """Tokenize link text and drop stopwords, emphasis, and very short tokens.

    Splits on punctuation INCLUDING `.` so `workflows.md` yields two tokens
    (`workflows`, `md`) rather than one unmatchable whole-filename token.
    """
    cleaned = re.sub(r"[`*_]", " ", text.lower())
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return [
        w for w in cleaned.split()
        if w and w not in _LINK_TEXT_STOPWORDS and len(w) > 2
    ]


def check_link_landing(results: ValidationResult):
    """Warn when a `[text](target.md)` link's substantive words don't appear
    in target.md.

    Catches pedagogical mismatches: a link that says 'see the cardinality
    discovery step' but points at a file that doesn't discuss cardinality
    anywhere. Independent of (and runs after) check_markdown_links, which
    only verifies the target exists and the anchor resolves.

    Heuristic, not strict: we only warn when *none* of the content words
    from link text appear in the target. External links, anchor-only
    links, and links whose text reduces to stopwords are skipped.
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in MD_LINK_PATTERN.finditer(content):
            raw_text = m.group(1).strip()
            target = m.group(2).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue

            path_part = target.split("#", 1)[0] if "#" in target else target
            if not path_part:  # pure anchor link — skip
                continue

            # Resolve target path (same logic as check_markdown_links)
            if path_part.startswith("references/"):
                target_file = SKILL_DIR / path_part
            elif md_file.parent.name == "references":
                target_file = REFERENCES_DIR / path_part
            else:
                target_file = md_file.parent / path_part

            if not target_file.exists() or target_file.suffix != ".md":
                continue  # broken link or non-markdown target; not our job

            text_words = _extract_content_words(raw_text)
            if not text_words:
                continue  # text was all stopwords / too short — can't verify

            target_content = target_file.read_text().lower()
            if any(w in target_content for w in text_words):
                results.ok(f"link-landing: {md_file.name} -> {target}")
                continue

            line_num = content[: m.start()].count("\n") + 1
            shown = ", ".join(text_words[:5])
            results.warn(
                f"{md_file.name}:{line_num}: link '{raw_text}' → {target}: "
                f"none of [{shown}] appear in target; target may not cover "
                f"what the link text promises"
            )


# Broader citation pattern than PROSE_CITATION_PATTERN — matches both
# fully-qualified (`src/spyglass/foo.py:N`) and bare-filename (`foo.py:N`)
# cases, single lines or `:N-M` ranges. We explicitly skip comma-lists here;
# the existing check_citation_lines covers their bounds, and extending this
# content check to multi-span citations is pure overhead for the handful
# of cases in current prose that use them.
_CITATION_CONTENT_PATTERN = re.compile(
    r"(?P<path>(?:src/spyglass/[A-Za-z0-9_./-]+|[a-z_][a-z_0-9]*))\.py:"
    r"(?P<lines>\d+(?:\s*[-–]\s*\d+)?)"
)

# Backtick-quoted identifier: `Foo`, `foo_bar`, `Foo.bar`, `foo()`, `Foo.bar()`.
# Parens and dots tolerated; leading digit rejected to avoid matching numbers.
_BACKTICK_IDENT_PATTERN = re.compile(
    r"`([A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*(?:\(\))?)`"
)

# Identifiers we treat as too generic to meaningfully verify against a source
# line — matching `self` anywhere on a cited line proves nothing.
_GENERIC_IDENTIFIERS = frozenset({
    "self", "cls", "key", "data", "name", "params", "kwargs", "args",
    "result", "value", "table", "def", "class", "import", "from", "as",
    "True", "False", "None",
})


def _find_preceding_identifier(content, end_pos, window=120):
    """Return the most recent backtick-quoted identifier in the `window`
    characters before `end_pos`, or None if no usable identifier is present.

    Filters out .py filenames (which the citation itself contains) and the
    _GENERIC_IDENTIFIERS set. Returns the identifier with any trailing `()`
    stripped, since we match against source symbol names.
    """
    snippet = content[max(0, end_pos - window):end_pos]
    matches = list(_BACKTICK_IDENT_PATTERN.finditer(snippet))
    for m in reversed(matches):  # closest-to-citation wins
        ident = m.group(1).rstrip("()")
        if ident.endswith(".py") or ident in _GENERIC_IDENTIFIERS:
            continue
        if len(ident) < 4:  # 3-letter acronyms would match too broadly
            continue
        return ident
    return None


def _identifier_candidates(ident):
    """Yield identifier variants to search for. `Foo.bar` -> ['Foo.bar', 'bar']."""
    yield ident
    if "." in ident:
        yield ident.rsplit(".", 1)[-1]


def check_citation_content(src_root, results: ValidationResult):
    """Warn when a `file.py:N` prose citation's cited line range doesn't
    contain the identifier mentioned in the preceding backticks.

    Complement to check_citation_lines, which only verifies N is in range.
    This check verifies that line N (±8, to tolerate decorators, blank lines,
    and docstrings) *contains* the symbol the prose says is there.

    Heuristic. Skips citations without a backtick identifier in the 120
    preceding characters, bare-filename citations that resolve to multiple
    files (ambiguous), and generic identifiers like `self`/`cls`/`key`.
    """
    # Build a bare-filename -> absolute-path map once. Ambiguous names
    # (same filename in multiple dirs) are dropped from the map.
    bare_to_path = {}
    for p in src_root.rglob("*.py"):
        bare_to_path.setdefault(p.name, []).append(p)

    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in _CITATION_CONTENT_PATTERN.finditer(content):
            path_s = m.group("path")
            lines_s = m.group("lines")

            if path_s.startswith("src/spyglass/"):
                target = src_root.parent / (path_s + ".py")
            else:
                candidates = bare_to_path.get(path_s + ".py", [])
                if len(candidates) != 1:
                    continue  # ambiguous or missing
                target = candidates[0]

            if not target.exists():
                continue

            ident = _find_preceding_identifier(content, m.start())
            if not ident:
                continue  # no verifiable identifier in context

            # Parse endpoints (single int or `lo-hi`)
            endpoints = re.split(r"\s*[-–]\s*", lines_s, maxsplit=1)
            try:
                lo = int(endpoints[0])
                hi = int(endpoints[-1]) if len(endpoints) > 1 else lo
            except ValueError:
                continue

            try:
                all_lines = target.read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            md_line_num = content[:m.start()].count("\n") + 1
            if _citation_matches_identifier(all_lines, lo, hi, ident):
                results.ok(
                    f"cite-content: {md_file.name}:{md_line_num} "
                    f"{path_s}.py:{lines_s} matches `{ident}`"
                )
            else:
                results.warn(
                    f"{md_file.name}:{md_line_num}: citation "
                    f"'{path_s}.py:{lines_s}' does not contain `{ident}` "
                    f"within ±8 lines or inside the enclosing def/class — "
                    f"citation may be stale"
                )


def _citation_matches_identifier(all_lines, lo, hi, ident):
    """Return True if `ident` is plausibly represented at cited line range.

    Two acceptance rules (either suffices):
      (a) Literal substring match within ±8 lines of the cited range.
          Covers direct citations like `merge_delete_parent at :468`.
      (b) The cited line sits INSIDE a `def <ident>(...)` or
          `class <ident>:` block that starts within 60 lines above `lo`.
          Covers citations that point into a function body — e.g. a cite
          of :499 where the enclosing `def merge_delete_parent` is at :468.

    Rule (b) uses indentation to detect the block boundary: we scan upward
    for a `def`/`class` line at indent <= the cited line's indent, and
    accept if that definition's name matches any identifier candidate.
    """
    # Rule (a): direct ±8 substring match.
    start_idx = max(0, lo - 1 - 8)
    end_idx = min(len(all_lines), hi + 8)
    window_text = "\n".join(all_lines[start_idx:end_idx])
    for candidate in _identifier_candidates(ident):
        if candidate in window_text:
            return True

    # Rule (b): walk up the nesting stack. Cited line sits inside zero or
    # more enclosing def/class scopes. We accept if ANY enclosing scope's
    # declared name matches. Scan upward tracking a falling indent cap:
    # a def/class at indent < cap is an outer enclosing scope; its indent
    # becomes the new cap (nested inner defs are skipped as `>= cap`).
    # `lo` is 1-indexed; all_lines is 0-indexed.
    if lo <= 0 or lo > len(all_lines):
        return False
    cited_line = all_lines[lo - 1]
    indent_cap = len(cited_line) - len(cited_line.lstrip()) + 1
    # Bound upward scan to ~120 lines — enough to cover a class wrapping
    # a long method, but small enough to avoid false matches from
    # unrelated defs earlier in the file.
    scan_start = max(0, lo - 1 - 120)
    for idx in range(lo - 2, scan_start - 1, -1):
        line = all_lines[idx]
        stripped = line.lstrip()
        if not stripped.startswith(("def ", "class ", "async def ")):
            continue
        indent = len(line) - len(stripped)
        if indent >= indent_cap:
            continue  # nested inner scope we've already exited
        rest = stripped
        if rest.startswith("async def "):
            rest = rest[len("async def "):]
        elif rest.startswith("def "):
            rest = rest[len("def "):]
        elif rest.startswith("class "):
            rest = rest[len("class "):]
        decl_match = re.match(r"[A-Za-z_][A-Za-z_0-9]*", rest)
        if decl_match:
            decl_name = decl_match.group(0)
            for candidate in _identifier_candidates(ident):
                if decl_name == candidate:
                    return True
        indent_cap = indent
        if indent == 0:
            break  # hit top level; no further enclosing scope exists
    return False


def check_python_syntax(results: ValidationResult):
    """Parse every ```python fenced block with ast.parse().

    Catches syntax drift (unclosed brackets, broken f-strings, bad indentation)
    before the model can learn from the mistake. Unlabeled fences are skipped
    because they may be shell, JSON, or output — only ```python means "this
    is runnable example code."
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        for block_start, lang, body in extract_fenced_blocks(content):
            if lang != "python":
                continue
            location = f"{md_file.name}:{block_start}"
            try:
                ast.parse(body)
                results.ok(f"syntax: {location} parses as Python")
            except SyntaxError as e:
                # e.lineno is within the block — offset to the file line
                file_line = block_start + (e.lineno - 1 if e.lineno else 0)
                results.fail(
                    f"{md_file.name}:{file_line}: python block has "
                    f"SyntaxError: {e.msg}"
                )


# Paths matching these prefixes in prose are expected to exist under the
# spyglass repo root. Ordering matters only for display.
PROSE_PATH_PREFIXES = (
    "src/spyglass/",
    "docs/src/",
    "notebooks/py_scripts/",
    "scripts/",
)
PROSE_PATH_PATTERN = re.compile(
    r"(?:`|\(|\s|^)(?P<p>(?:"
    + "|".join(re.escape(p) for p in PROSE_PATH_PREFIXES)
    + r")[A-Za-z0-9_./*-]+)"
)


def check_prose_paths(src_root, results: ValidationResult):
    """Verify that repo paths mentioned in prose actually exist.

    LLMs treat prose paths as authoritative. A stale `src/spyglass/foo/` from
    an old refactor is more dangerous than a stale code snippet because it
    looks like a pointer to truth. We check paths under the spyglass repo
    root (one level above --spyglass-src).
    """
    repo_root = src_root.parent
    seen = set()  # (file, path) to avoid double-reporting
    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in PROSE_PATH_PATTERN.finditer(content):
            raw = m.group("p")
            # Strip trailing punctuation that often follows inline paths
            path = raw.rstrip(".,:;)")
            key = (md_file.name, path)
            if key in seen:
                continue
            seen.add(key)
            # Skip glob patterns — `src/spyglass/**/*.py` is valid prose but
            # won't resolve via Path.exists()
            if "*" in path:
                continue
            # Find line number for reporting
            line_num = content[: m.start()].count("\n") + 1
            location = f"{md_file.name}:{line_num}"
            target = repo_root / path
            if target.exists():
                results.ok(f"path: {location} -> {path} exists")
            else:
                results.fail(
                    f"{location}: referenced path '{path}' does not "
                    f"exist under {repo_root}"
                )


# Notebook filename pattern: `NN_Word_Word.py`. The prefix number and
# PascalCase-ish tail distinguishes canonical-workflow notebook names from
# arbitrary .py/.ipynb identifiers in prose. Match both suffixes because
# .ipynb is the tutorial users run and .py is the py_scripts/ mirror.
NOTEBOOK_NAME_PATTERN = re.compile(
    r"\b(\d{2}_[A-Za-z][A-Za-z_0-9]*\.(?:py|ipynb))\b"
)


# `src/spyglass/path.py:123`, `:123, 456`, `:90-150`, or mixed `:1-5, 10, 20-30`.
PROSE_CITATION_PATTERN = re.compile(
    r"(?P<path>src/spyglass/[A-Za-z0-9_./-]+\.py):"
    r"(?P<lines>\d+(?:\s*[-,]\s*\d+)*)"
)


def _parse_cited_lines(expr):
    """Expand a citation line-expression into a list of line numbers.

    Accepts comma-separated integers and dash-ranges, in any combination:
      "499"         -> [499]
      "499, 505"    -> [499, 505]
      "88-108"      -> [88, 108]   (both endpoints; bounds-only check)
      "1-5, 10, 20" -> [1, 5, 10, 20]

    We deliberately list only the two range endpoints rather than every
    line in between — upper-bound rot is the failure we care about, and
    exhaustive enumeration would dominate the pass count.
    """
    out = []
    for part in expr.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.append(int(lo.strip()))
            out.append(int(hi.strip()))
        else:
            out.append(int(part))
    return out


def check_citation_lines(src_root, results: ValidationResult):
    """Verify that `file.py:N[, M][, A-B]` citations in prose point at real lines.

    Catches stale citations after refactors: if the skill says
    `dj_merge_tables.py:499, 505` but the file has been truncated or
    rewritten, the citations no longer land on relevant code. Supports
    comma lists and dash ranges — for ranges, both endpoints are checked
    (the classic failure mode is an upper bound that rotted past EOF).
    Semantic accuracy (does line N contain the claimed symbol) is still
    out of scope; bounds only.
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in PROSE_CITATION_PATTERN.finditer(content):
            path = m.group("path")
            lines_str = m.group("lines")
            target = src_root.parent / path
            if not target.exists():
                continue  # check_prose_paths handles missing files
            try:
                line_count = len(target.read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                continue
            md_line_num = content[: m.start()].count("\n") + 1
            location = f"{md_file.name}:{md_line_num}"
            cited = _parse_cited_lines(lines_str)
            out_of_range = [n for n in cited if n < 1 or n > line_count]
            if out_of_range:
                results.fail(
                    f"{location}: citation '{path}:{lines_str}' — "
                    f"line(s) {out_of_range} out of range "
                    f"(file has {line_count} lines)"
                )
            else:
                results.ok(
                    f"{location}: citation '{path}:{lines_str}' in range"
                )


# Pattern matches `ClassName.method(` or `ClassName().method(` appearing in
# eval prose (expected_output, behavioral_checks, required_substrings).
# The leading \b and uppercase requirement on class_name avoid matching
# lowercase variable refs like `rel.fetch()` in a discovery-step example.
_EVAL_METHOD_CALL_PATTERN = re.compile(
    r"\b([A-Z]\w+)\s*(\(\))?\s*\.\s*(\w+)\s*\("
)


def _load_evals_for_check(results, fail_on_parse=False):
    """Load the eval suite for per-eval checks. Returns the list of eval
    entries (or [] if the file is absent / unparseable).

    `check_evals_content` is the canonical parse-error reporter — it runs
    first with `fail_on_parse=True` so any JSON error is surfaced once.
    The hygiene + completeness checks run later and silently skip on a
    parse failure to avoid triple-reporting the same error.
    """
    evals_path = SKILL_DIR / "evals" / "evals.json"
    if not evals_path.exists():
        return []
    try:
        data = json.loads(evals_path.read_text())
    except json.JSONDecodeError as e:
        if fail_on_parse:
            results.fail(f"evals.json: JSON parse error: {e}")
        return []
    return data.get("evals", []) or []


def _looks_code_like(s: str, registry=None) -> bool:
    """True if a required_substring is a code-shaped token (class/method/path/
    flag/kwarg/CLI-flag/dict-key) rather than a bare English word/phrase.

    The substring-hygiene rule (evals/README.md §Substring hygiene) warns
    about bare words ("restart" matches "no need to restart") and
    phrasing-locked bigrams ("recommend v1" fails on "use v1"). This
    helper is the conservative exempt side — anything with code-looking
    punctuation, digits, internal caps, or a known Spyglass class name
    is unlikely to be bare, so the hygiene check skips it.

    Bare-word examples (_looks_code_like returns False — the check will
    warn): `Manual`, `legacy`, `noise`, `Raw`, `derivative`, `restart`,
    `kernel`.
    Code-looking examples (returns True — skipped): `Manual table`
    (has space), `SpikeSorting.populate` (dotted), `raise_err=True`
    (has `=`), `target_sampling_rate` (underscored), `LFPV1` (digit),
    `--dry-run` (CLI flag), `['raw']` (dict-key), `Electrode` (known
    Spyglass class — discriminating even though the string itself looks
    bare).
    """
    if not s:
        return True  # empty = degenerate, skip
    # Any code-punct is a strong signal the substring is a specific
    # identifier / path / call site / CLI flag / dict-key / string
    # literal. Hyphens cover `--dry-run`; brackets+quotes cover
    # `['raw']`; comparison/operator chars cover flags like `<=`.
    if any(c in s for c in "._@/():=&-[]{}'\"<>,;!?*%"):
        return True
    if any(c.isdigit() for c in s):
        return True
    # Internal capitals (LFPBandV1, CamelCase) signal a typed identifier.
    # A lone leading capital ("Nyquist", "Manual") does NOT — those read
    # as ordinary proper nouns or title-cased English.
    if any(c.isupper() for c in s[1:]):
        return True
    # Known Spyglass class names are discriminating by definition even
    # if they look like a single leading-capital word (`Electrode`,
    # `Session`, `Nwbfile`). The registry check lets these through while
    # still catching single English words like `Manual` or `Computed`
    # that aren't class names.
    if registry is not None and registry.methods(s) is not None:
        return True
    return False


def check_eval_required_substring_hygiene(
    src_root, results: ValidationResult, registry=None,
):
    """Warn on required_substrings that are likely to suffer from the
    substring-hygiene traps documented in evals/README.md.

    Two patterns caught:

    1. **Bare single word** — a required_substring that's a single
       alphabetic word with no code-punct or digits. `required_substrings:
       ["Manual"]` passes on "this is not a Manual table" just as well
       as "it IS a Manual table". The README's guidance: pair with a
       disambiguating word or use a phrase.

    2. **Overly-literal formatting** — a required_substring that includes
       literal backticks (`` `Raw` ``), a trailing open-paren
       (`SpikeSorting.populate(`), or other formatting punctuation that
       locks the match to one specific rendering. Correct answers using
       a different code-style would false-fail.

    Both are warnings, not failures — author may intentionally want a
    bare match (e.g., for a rare domain term) or an exact form. Silence
    per-eval by adding `assertions.required_substrings_exempt: [...]`
    with the exact substring. Author-discipline: the exempt list is
    itself audit-worthy — every entry should be a conscious choice that
    the substring discriminates despite being bare.
    """
    if registry is None:
        registry = _ClassRegistry(src_root, results)
    for eval_entry in _load_evals_for_check(results):
        eid = eval_entry.get("id", "?")
        a = eval_entry.get("assertions", {}) or {}
        reqs = a.get("required_substrings", []) or []
        exempt = set(a.get("required_substrings_exempt", []) or [])
        for sub in reqs:
            if not isinstance(sub, str) or sub in exempt:
                continue
            stripped = sub.strip()
            if stripped.startswith("`") or stripped.endswith("`"):
                results.warn(
                    f"evals.json[id={eid}]: required_substring {sub!r} wraps "
                    f"literal backticks — correct answers using a different "
                    f"code-style rendering will false-fail. Drop the backticks "
                    f"or add to required_substrings_exempt if intentional."
                )
                continue
            if stripped.endswith("("):
                results.warn(
                    f"evals.json[id={eid}]: required_substring {sub!r} ends "
                    f"with '(' — locks the match to a specific call form "
                    f"(`.populate()` vs `.populate(key)` vs `.populate` verb). "
                    f"Drop the paren or add to required_substrings_exempt."
                )
                continue
            if " " not in stripped and not _looks_code_like(stripped, registry):
                results.warn(
                    f"evals.json[id={eid}]: required_substring {sub!r} is a "
                    f"bare word (no code-punct, no digits, no internal caps) — "
                    f"matches denial phrasings ('not {stripped}') equally well. "
                    f"Pair with a disambiguating word, use a phrase, or add "
                    f"to required_substrings_exempt if the bare match really "
                    f"is discriminating (rare domain term)."
                )


# Matches CapitalCase identifier tokens in eval expected_output prose —
# what we use to enumerate tables/classes the eval claims are relevant.
# Pattern: starts with uppercase, then 2+ identifier chars. 2-char
# minimum on the tail avoids matching sentence-start words like "It" or
# "In" (too short to be a class). We further filter against the
# Spyglass class registry so ordinary proper nouns don't false-fire.
_EVAL_CAPITAL_TOKEN_PATTERN = re.compile(r"\b[A-Z][a-zA-Z0-9_]{2,}\b")

# Infrastructure classes (mixins, base wrappers) that legitimately appear
# in eval expected_output as context but are never themselves the target
# table a correct answer must enumerate. The completeness check excludes
# these so mentioning `SpyglassMixin` in passing doesn't trigger a
# "missing from required_substrings" warning.
_EVAL_COMPLETENESS_IGNORE = {
    "SpyglassMixin", "SpyglassIngestion", "ExportMixin", "PopulateMixin",
    "TimeIntervalMixin",
}


def check_eval_required_substring_completeness(
    src_root, results: ValidationResult, registry=None,
):
    """Warn when an eval's `expected_output` names a Spyglass class that
    `required_substrings` doesn't require.

    The eval author writes a human-readable `expected_output` describing
    the ideal response, then picks `required_substrings` that a correct
    answer must contain. Those two surfaces can drift — eval 72 originally
    named `SpikeSortingOutput`, `CurationV1`, `WaveformFeaturesParams` in
    `expected_output` but omitted them from `required_substrings`, so a
    grep-pass was possible while missing substantive upstream tables.

    This check extracts CapitalCase tokens from `expected_output`,
    filters to names that resolve against the Spyglass class registry
    (so ordinary English proper nouns don't trip it), then confirms each
    appears as a substring in at least one `required_substring`. Misses
    warn. Silence per-eval via
    `assertions.expected_output_tables_exempt: [...]` — use this when
    `expected_output` mentions a table as context/distractor rather
    than as a token a correct answer must produce.
    """
    if registry is None:
        registry = _ClassRegistry(src_root, results)
    for eval_entry in _load_evals_for_check(results):
        eid = eval_entry.get("id", "?")
        expected = eval_entry.get("expected_output", "") or ""
        if not isinstance(expected, str):
            continue
        a = eval_entry.get("assertions", {}) or {}
        reqs = a.get("required_substrings", []) or []
        exempt = set(a.get("expected_output_tables_exempt", []) or [])
        candidates = set(_EVAL_CAPITAL_TOKEN_PATTERN.findall(expected))
        # Substring-in-substring lets `SpikeSortingOutput` satisfy both
        # itself and a more-specific `SpikeSortingOutput.CurationV1`.
        tables = {
            c for c in candidates
            if registry.methods(c) is not None
            and c not in _EVAL_COMPLETENESS_IGNORE
        }
        req_blob = " ".join(s for s in reqs if isinstance(s, str))
        missing = [
            t for t in tables
            if t not in exempt and t not in req_blob
        ]
        for t in sorted(missing):
            results.warn(
                f"evals.json[id={eid}]: expected_output names Spyglass class "
                f"{t!r} but no required_substring contains it — a grep-pass "
                f"is possible while missing this table. Add {t!r} (or a "
                f"dotted form like `{t}.PartName`) to required_substrings, "
                f"or add to expected_output_tables_exempt if the mention is "
                f"contextual/distractor-only."
            )


def check_evals_content(src_root, results: ValidationResult, registry=None):
    """Scan evals.json for method/class references that don't resolve.

    The same author-discipline failures that the validator catches in
    reference prose and code blocks also happen when writing eval
    expected_output: hallucinated kwargs, nonexistent methods, misspelled
    class names. Previously the validator ignored the evals/ directory
    entirely, so eval 6 shipped twice with bugs that code review caught
    instead of CI (interval_list_name missing, reference_electrodes vs
    reference_electrode_list, etc.).

    This check applies the same method-existence logic to eval prose via
    a regex scan — AST parsing isn't usable here because expected_output
    is narrative English with inline code fragments, not a python source.
    Scans expected_output + behavioral_checks + required_substrings.
    Skips forbidden_substrings (those are intentionally-wrong patterns
    the eval is designed to reject).

    When evals.json is absent the check is a no-op — skills without an
    evals/ directory shouldn't fail validation. Malformed JSON fails hard
    so CI catches edit mistakes.

    Regex-match discipline: matches inside inline-backtick code spans
    (`Class.method()`) are always evaluated. Matches in bare prose are
    evaluated for method-existence and instance-vs-classmethod (high-
    signal failures), but the "unresolved class" warning is suppressed
    outside backticks — camelcase prose words like "Uses" or "Either"
    otherwise trigger false positives on `Uses .fetch()` constructs.
    """
    if registry is None:
        registry = _ClassRegistry(src_root, results)

    for eval_entry in _load_evals_for_check(results, fail_on_parse=True):
        eval_id = eval_entry.get("id", "?")
        assertions = eval_entry.get("assertions", {}) or {}
        # Join the scannable text fields into one blob. Forbidden_substrings
        # is intentionally excluded — those strings are wrong by design.
        parts = [eval_entry.get("expected_output", "")]
        parts.extend(assertions.get("behavioral_checks", []) or [])
        parts.extend(assertions.get("required_substrings", []) or [])
        text = "\n".join(p for p in parts if isinstance(p, str))

        for match in _EVAL_METHOD_CALL_PATTERN.finditer(text):
            class_name = match.group(1)
            instance_call = bool(match.group(2))
            method_name = match.group(3)
            # Matches inside inline-backtick spans are high-confidence code;
            # prose matches are lower-confidence and we suppress the weakest
            # signal (unresolved-class warnings) for them via the
            # `warn_on_unresolved_class` flag below.
            start = match.start()
            in_backticks = start > 0 and text[start - 1] == "`"
            location = f"evals.json[id={eval_id}]"
            _classify_method_call(
                class_name, method_name, instance_call,
                registry, results, location,
                warn_on_unresolved_class=in_backticks,
                ok_detail=False,
            )


def check_notebook_names(src_root, results: ValidationResult):
    """Verify notebook filenames mentioned in prose exist in the spyglass repo.

    The routing table in SKILL.md references canonical workflows by bare
    filename (e.g., `10_Spike_SortingV1.ipynb`). If a notebook is renamed
    upstream, the skill silently ships a dead pointer. We scan all skill
    markdown for the NN_Word.ipynb OR NN_Word.py pattern. The .ipynb
    tutorial is canonical (notebooks/); the .py form in notebooks/py_scripts/
    is a PR-review mirror — accept either suffix as valid.
    """
    nb_dir_ipynb = src_root.parent / "notebooks"
    nb_dir_py = src_root.parent / "notebooks" / "py_scripts"
    if not nb_dir_ipynb.is_dir():
        results.fail(
            f"notebooks: expected {nb_dir_ipynb} to exist for notebook-name "
            f"validation. Pass --spyglass-src pointing at a repo checkout."
        )
        return
    # Stems exist if either the .ipynb in notebooks/ OR the .py in
    # notebooks/py_scripts/ is present.
    stems_ipynb = {p.stem for p in nb_dir_ipynb.glob("*.ipynb")}
    stems_py = (
        {p.stem for p in nb_dir_py.glob("*.py")} if nb_dir_py.is_dir() else set()
    )
    available_stems = stems_ipynb | stems_py
    seen = set()
    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in NOTEBOOK_NAME_PATTERN.finditer(content):
            name = m.group(1)
            key = (md_file.name, name)
            if key in seen:
                continue
            seen.add(key)
            line_num = content[: m.start()].count("\n") + 1
            location = f"{md_file.name}:{line_num}"
            stem = name.rsplit(".", 1)[0]
            if stem in available_stems:
                results.ok(f"notebook: {location} -> {name} exists")
            else:
                results.fail(
                    f"{location}: notebook '{name}' not found in "
                    f"notebooks/ or notebooks/py_scripts/"
                )


# Markdown link pattern: [text](target). Skips http(s) — those are external
# and should be caught by a separate link-checker if needed, not by the
# offline AST validator.
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _slugify_heading(heading):
    """Approximate GitHub's anchor-slug algorithm.

    Rules: lowercase; strip backticks/asterisks; drop non-word non-space
    non-hyphen chars; replace each space with one hyphen. Underscores are
    intentionally preserved — GFM keeps them in slugs (e.g. `SPYGLASS_BASE_DIR`
    → `spyglass_base_dir`). Per-space replacement (not `\\s+` collapse) is
    also intentional: punctuation like `/` removed between words leaves two
    visible spaces → two hyphens, matching GitHub's rendered anchor.
    """
    s = heading.strip().lower()
    s = re.sub(r"[`*]", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = s.replace(" ", "-")
    return s.strip("-")


def check_markdown_links(results: ValidationResult):
    """Verify internal markdown links resolve.

    Checks two kinds of links that rot silently:
    1. File links like `[x](references/y.md)` — target file must exist
    2. Anchor links like `[x](#section)` or `[x](y.md#section)` — anchor
       must correspond to a heading in the target file (after slugifying)

    External http(s) links are not checked (requires network, out of scope).
    """
    # Precompute anchors for each skill md file
    all_anchors = {}
    for md_file in collect_md_files():
        content = md_file.read_text()
        anchors = set()
        for line in content.split("\n"):
            stripped = line.lstrip("#").strip() if line.startswith("#") else ""
            if stripped and line.startswith("#"):
                anchors.add(_slugify_heading(stripped))
        all_anchors[md_file.name] = anchors

    for md_file in collect_md_files():
        content = md_file.read_text()
        for m in MD_LINK_PATTERN.finditer(content):
            target = m.group(2).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            line_num = content[: m.start()].count("\n") + 1
            location = f"{md_file.name}:{line_num}"

            # Split `path#anchor` / `#anchor` / `path`
            if "#" in target:
                path_part, anchor = target.split("#", 1)
            else:
                path_part, anchor = target, None

            # Resolve the target file (relative to the containing md)
            if path_part:
                if path_part.startswith("references/"):
                    target_file = SKILL_DIR / path_part
                elif md_file.parent.name == "references":
                    # Sibling file within references/
                    target_file = REFERENCES_DIR / path_part
                else:
                    target_file = md_file.parent / path_part
                if not target_file.exists():
                    results.fail(
                        f"{location}: broken link target '{target}' "
                        f"(resolved to {target_file})"
                    )
                    continue
                target_name = target_file.name
            else:
                # Same-file anchor
                target_name = md_file.name

            if anchor is not None:
                anchors = all_anchors.get(target_name, set())
                if _slugify_heading(anchor) not in anchors:
                    results.fail(
                        f"{location}: broken anchor '#{anchor}' in "
                        f"'{target}' (target file has no matching heading)"
                    )
                else:
                    results.ok(f"link: {location} -> {target} resolves")
            else:
                results.ok(f"link: {location} -> {target} resolves")


def _iter_insert_sessions_calls(body):
    """Yield (start_offset, args_str) for each insert_sessions(...) call.

    Uses _extract_arg_list for balanced-paren extraction so nested parens
    (tuples, method calls, list comps inside args) don't terminate the match
    early — a simple `[^)]*` regex evades this exact case. Multi-line calls
    are handled because _extract_arg_list walks the full body, not a line.
    """
    for m in re.finditer(r"insert_sessions\s*\(", body):
        paren_idx = m.end() - 1
        args = _extract_arg_list(body, paren_idx)
        if args is not None:
            yield m.start(), args


MERGE_CLASSMETHODS = frozenset({
    "merge_delete", "merge_delete_parent", "merge_restrict",
    "merge_get_part", "merge_get_parent", "merge_view", "merge_html",
})

MERGE_TABLE_CLASSES = frozenset({
    "PositionOutput", "LFPOutput", "SpikeSortingOutput",
    "DecodingOutput", "LinearizedPositionOutput",
})


def _iter_merge_classmethod_discard(body):
    """Yield (offset, desc) for each `(MergeTable & ...).merge_method()`.

    AST-based so we catch multi-line restrictions and nested parens in the
    restriction expression, both of which the prior regex missed. Resolves
    aliased imports via `build_alias_map` so that
    `from ... import PositionOutput as PO; (PO & key).merge_delete()` is
    also caught — the canonical-name check alone would miss that shape.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return
    alias_map = build_alias_map(tree)
    # Prefix-sum of physical-line lengths so we can convert a (lineno,
    # col_offset) pair from the AST into a character offset into `body`.
    lines = body.splitlines(keepends=True)
    prefix = [0]
    for line in lines:
        prefix.append(prefix[-1] + len(line))

    def offset_of(node):
        idx = node.lineno - 1
        if 0 <= idx < len(prefix):
            return prefix[idx] + node.col_offset
        return 0

    def resolve(name):
        """Map a local name through alias_map to its canonical class,
        or return the local name unchanged if not aliased."""
        canonical = alias_map.get(name, name)
        if canonical.startswith("<module:"):
            return None  # module binding, not a class
        return canonical

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in MERGE_CLASSMETHODS:
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.BinOp):
            continue
        if not isinstance(receiver.op, ast.BitAnd):
            continue
        left = receiver.left
        # Bare class: `PositionOutput & key` or `PO & key` (PO aliased)
        if isinstance(left, ast.Name):
            canonical = resolve(left.id)
            if canonical in MERGE_TABLE_CLASSES:
                yield (
                    offset_of(node),
                    f"({left.id} & ...).{node.func.attr}(...)",
                )
        # Instance form: `PositionOutput() & key` or `PO() & key`
        elif isinstance(left, ast.Call) and isinstance(left.func, ast.Name):
            canonical = resolve(left.func.id)
            if canonical in MERGE_TABLE_CLASSES:
                yield (
                    offset_of(node),
                    f"({left.func.id}() & ...).{node.func.attr}(...)",
                )


# Each anti-pattern: (rule_id, description, matcher_fn, scope).
# matcher_fn(body_or_content) -> iterator of (start_offset, matched_repr).
# scope="code": run matcher on ```python block bodies only.
# scope="any": run matcher on the full markdown (prose + code). Avoid this
#   scope when the skill prose legitimately quotes the pattern to warn
#   against it — use scope="code" instead, which is the default.
#
# Note: these matchers are deliberately structural (find `insert_sessions(`
# then inspect balanced args) rather than one flat regex. A flat regex
# using `[^)]*` would evade any call with nested parens in an earlier arg.
ANTI_PATTERNS = [
    (
        "trailing-underscore-nwb",
        "insert_sessions() called with a '_.nwb' copy filename instead of "
        "the raw filename (f-string filenames are not detected)",
        lambda body: [
            (start, args)
            for start, args in _iter_insert_sessions_calls(body)
            if re.search(r'["\'][^"\']*_\.nwb["\']', args)
        ],
        "code",
    ),
    (
        "skip-duplicates-raw-ingestion",
        "skip_duplicates=True used inside an insert_sessions() call "
        "(use reinsert=True for raw re-ingestion)",
        lambda body: [
            (start, args)
            for start, args in _iter_insert_sessions_calls(body)
            if re.search(r"skip_duplicates\s*=\s*True", args)
        ],
        "code",
    ),
    (
        "merge-classmethod-discard",
        "merge-table classmethod called on a restricted relation "
        "(Table & key).method() — Python dispatches classmethod calls "
        "to the class, silently dropping the `& key`. Pass the "
        "restriction as an argument: Table.method(restriction) instead.",
        # AST-based: find Call nodes whose receiver is a BinOp(BitAnd)
        # with a merge-table class on the left and the attr is one of
        # the classmethod names. AST handles multi-line restrictions and
        # nested parens (e.g., `& get_key()`) that the old regex missed;
        # comments don't appear in the AST so no explicit comment filter
        # is needed.
        lambda body: list(_iter_merge_classmethod_discard(body)),
        "code",
    ),
    (
        "spyglassmixin-not-first",
        "class inherits from dj.{Manual,Lookup,Computed,Imported,Part} "
        "without SpyglassMixin/SpyglassMixinPart as the first parent — "
        "required for Spyglass method overrides to work correctly",
        # Match `class Foo(..., dj.Manual):` where SpyglassMixin /
        # SpyglassMixinPart is NOT the first parent. Handles multi-line
        # class declarations — the negative lookahead spans leading
        # whitespace so `class Foo(\n    SpyglassMixin, dj.X):` correctly
        # passes (earlier `(?!SpyglassMixin\b)` at a fixed position would
        # let the engine backtrack `\s*` and sneak past the mixin check).
        lambda body: [
            (m.start(), m.group(0))
            for m in re.finditer(
                r"class\s+\w+\s*\("
                r"(?!\s*(?:SpyglassMixin|SpyglassMixinPart)\b)"
                r"[^)]*\bdj\.(?:Manual|Lookup|Computed|Imported|Part)\b",
                body,
            )
        ],
        "code",
    ),
]


def check_anti_patterns(results: ValidationResult):
    """Fail on patterns that look correct but teach the wrong thing.

    These are things the skill already warns against in prose — the validator
    makes sure no code example slips past and contradicts the guidance.
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        # Precompute code-block spans so we can scope checks to code only
        code_bodies = [
            (start, body)
            for start, lang, body in extract_fenced_blocks(content)
            if lang == "python"
        ]
        for rule_id, description, matcher, scope in ANTI_PATTERNS:
            matched = False
            if scope == "code":
                for start_line, body in code_bodies:
                    for offset_pos, _text in matcher(body):
                        line_offset = body[:offset_pos].count("\n")
                        results.fail(
                            f"{md_file.name}:{start_line + line_offset}: "
                            f"anti-pattern[{rule_id}]: {description}"
                        )
                        matched = True
            elif scope == "any":
                for offset_pos, _text in matcher(content):
                    line_num = content[:offset_pos].count("\n") + 1
                    results.fail(
                        f"{md_file.name}:{line_num}: "
                        f"anti-pattern[{rule_id}]: {description}"
                    )
                    matched = True
            if not matched:
                results.ok(
                    f"anti-pattern[{rule_id}]: {md_file.name} clean"
                    )


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

    # Hard constraints from Anthropic skill-authoring guidance:
    # https://docs.anthropic.com/.../agent-skills/best-practices
    # 1. description must be <= 1024 chars (published cap)
    # 2. description must be third-person (no "I can", "you can", ...)
    desc_body = description[len("description:"):].strip() if description else ""
    if len(desc_body) > 1024:
        results.fail(
            f"description: frontmatter description is {len(desc_body)} chars; "
            f"Anthropic caps it at 1024 (best-practices.md)"
        )
    else:
        results.ok(f"description: length {len(desc_body)}/1024 chars")

    # SKILL.md body size — hard caps. Don't bump without migrating content
    # to references first. Anthropic target is <500 words for frequently-loaded
    # skills; 1200 gives headroom over the realistic post-migration size while
    # still forcing migration rather than unbounded growth.
    body = re.sub(r"^---\n.*?\n---\n", "", skill_content, count=1, flags=re.DOTALL)
    body_words = len(body.split())
    body_lines = body.count("\n") + 1
    WORD_HARD_CAP = 1200
    LINE_HARD_CAP = 500     # Anthropic's explicit cap on SKILL.md body
    if body_words > WORD_HARD_CAP:
        results.fail(
            f"body: SKILL.md body is {body_words} words (hard cap {WORD_HARD_CAP}); "
            f"migrate content to a reference file rather than raising the cap"
        )
    else:
        results.ok(f"body: SKILL.md body {body_words} words (<{WORD_HARD_CAP})")
    if body_lines > LINE_HARD_CAP:
        results.fail(
            f"body: SKILL.md body is {body_lines} lines; "
            f"Anthropic caps it at {LINE_HARD_CAP}"
        )
    else:
        results.ok(f"body: SKILL.md body {body_lines} lines (<{LINE_HARD_CAP})")

    # Over-generalization detector — flag "e.g." in non-code prose. Every past
    # over-generalization bug was introduced via "e.g." lists where a pipeline-
    # specific API got framed as a generic example (e.g. fetch_results on
    # DecodingOutput, which does not exist on other *Output tables). This is a
    # warning, not a fail — forces a human decision rather than silent acceptance.
    body_text_only = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body_text_only = re.sub(r"`[^`]+`", "", body_text_only)  # strip inline code too
    eg_hits = re.findall(r"\be\.g\.,?\s+\S", body_text_only)
    if eg_hits:
        results.warn(
            f"prose: 'e.g.' pattern found in SKILL.md body ({len(eg_hits)} hits) — "
            f"verify no pipeline-specific APIs are implied as generic examples"
        )
    else:
        results.ok("prose: no 'e.g.' patterns in SKILL.md body")

    # First/second person detection — Anthropic guidance says descriptions
    # are injected into the system prompt and must be third-person.
    person_patterns = [
        (r"\bI\s+(can|will|help)\b", "first-person ('I can/will/help')"),
        (r"\byou\s+(can|should|will|may)\b", "second-person ('you can/should/...')"),
        (r"\byour\b", "second-person possessive ('your')"),
    ]
    person_hit = False
    for pat, label in person_patterns:
        if re.search(pat, desc_body, flags=re.IGNORECASE):
            results.fail(
                f"description: contains {label} — must be third-person per "
                f"Anthropic guidance"
            )
            person_hit = True
    if not person_hit:
        results.ok("description: third-person wording")


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
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as failures (exit non-zero on any warning)"
    )
    parser.add_argument(
        "--baseline-warnings", type=int, default=None, metavar="N",
        help=(
            "CI-friendly: exit non-zero only if warnings > N. Lets a tree "
            "with N known-accepted warnings catch *new* warnings without "
            "requiring the old ones to be resolved first. Ignored under "
            "--strict (which fails on any warning)."
        ),
    )
    args = parser.parse_args()

    # Find spyglass source
    src_root = args.spyglass_src
    if src_root is None:
        # Try common locations (cwd-based only, no hardcoded paths)
        candidates = [
            Path.cwd() / "src",
            Path.cwd(),
        ]
        for candidate in candidates:
            if candidate is not None and (candidate / "spyglass").is_dir():
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

    print("\n[1/23] Checking source files and class registry...")
    check_class_files_exist(src_root, results)

    print("[2/23] Checking import statements in skill files...")
    check_imports(src_root, results)

    # Build the class registry once and share it across method + kwarg checks
    registry = _ClassRegistry(src_root, results)

    print("[3/23] Checking method references...")
    check_methods(src_root, results, registry=registry)

    print("[4/23] Checking keyword arguments...")
    check_kwargs(src_root, results, registry=registry)

    print("[5/23] Checking skill structure...")
    check_structure(results)

    print("[6/23] Checking prose assertions...")
    check_prose_assertions(results)

    print("[7/23] Parsing Python code blocks (ast.parse)...")
    check_python_syntax(results)

    print("[8/23] Verifying prose path references exist in repo...")
    check_prose_paths(src_root, results)

    print("[9/23] Verifying notebook names exist in repo...")
    check_notebook_names(src_root, results)

    print("[10/23] Verifying internal markdown links and anchors...")
    check_markdown_links(results)

    print("[11/23] Scanning for documented anti-patterns...")
    check_anti_patterns(results)

    print("[12/23] Checking dict-restriction field names against schemas...")
    check_restriction_fields(src_root, results)

    print("[13/23] Verifying citation line numbers are in range...")
    check_citation_lines(src_root, results)

    print("[14/23] Scanning evals.json for hallucinated class/method refs...")
    check_evals_content(src_root, results, registry=registry)

    print("[15/23] Scanning prose for banned PR-number citations...")
    check_no_pr_citations(results)

    print("[16/23] Enforcing reference-file and section size budgets...")
    check_section_budgets(results)

    print("[17/23] Checking markdown link-landing content overlap...")
    check_link_landing(results)

    print("[18/23] Verifying citation lines contain cited identifiers...")
    check_citation_content(src_root, results)

    print("[19/23] Detecting duplicated code blocks across references...")
    check_duplicated_blocks(results)

    print("[20/23] Checking DataJoint insert/populate key shape...")
    check_insert_key_shape(src_root, results)

    print("[21/23] Cross-checking merge-table registry against source...")
    check_merge_registry(src_root, results)

    print("[22/23] Checking eval required_substring hygiene (bare-word / literal-format)...")
    check_eval_required_substring_hygiene(src_root, results, registry=registry)

    print("[23/23] Checking eval required_substring completeness vs expected_output tables...")
    check_eval_required_substring_completeness(src_root, results, registry=registry)

    # Scoped collision report: only warn about v0/v1 duplicates for classes
    # the skill actually references. Avoids noise from unreferenced dupes.
    registry.report_referenced_collisions()

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

    # Exit status:
    #   failures → exit 1
    #   warnings + --strict → exit 1 (any warning)
    #   warnings + --baseline-warnings N → exit 1 only if count > N
    #   warnings alone → exit 0, but message distinguishes from clean
    #
    # --strict wins over --baseline-warnings when both are passed; the
    # baseline is a CI-friendly middle ground for trees with known-accepted
    # warnings, and --strict's zero-tolerance is a stronger statement.
    has_failures = bool(results.failed)
    warn_count = len(results.warnings)

    if has_failures:
        print("\nSome checks failed — review and fix the skill files.")
        return 1
    if warn_count:
        if args.strict:
            print(f"\nPassed with {warn_count} warning(s) "
                  "(--strict: treated as failure) — review above.")
            return 1
        if args.baseline_warnings is not None:
            if warn_count > args.baseline_warnings:
                print(f"\n{warn_count} warning(s) exceeds baseline of "
                      f"{args.baseline_warnings} — new warnings detected. "
                      "Fix them or raise --baseline-warnings.")
                return 1
            print(f"\nPassed with {warn_count} warning(s) "
                  f"(≤ baseline of {args.baseline_warnings}) — review above.")
            return 0
        print(f"\nPassed with {warn_count} warning(s) — review above.")
        return 0
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
