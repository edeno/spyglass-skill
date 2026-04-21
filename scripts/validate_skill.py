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
    "ExportSelection": "spyglass/common/common_usage.py",
    "Export": "spyglass/common/common_usage.py",
    "FigURLCurationSelection": "spyglass/spikesorting/v1/figurl_curation.py",
    "FigURLCuration": "spyglass/spikesorting/v1/figurl_curation.py",
}

# Methods to skip — DataJoint builtins, mixin methods, etc.
SKIP_METHODS = {
    # DataJoint builtins — always valid on any table, no point checking
    "fetch", "fetch1", "fetch_nwb", "fetch_pynapple",
    "proj", "aggr", "describe", "heading",
    "parents", "children", "insert", "insert1",
    "populate", "delete", "drop",
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
    """
    pk, attrs = set(), set()
    parents, projections = [], []
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
                parents.append(table_part.strip())
                for match in _DJ_PROJ_RE.finditer(proj_part):
                    new_name, source = match.group(1), match.group(2)
                    projections.append((new_name, source))
                    dest.add(new_name)
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
            "projections": projections}


def resolve_table_fields(class_name, schemas, _seen=None):
    """Return the transitive set of field names accepted by `class_name`.

    Walks `->` parent references to union inherited PKs into the child's
    accepted-field set. Returns None for unknown classes so the caller
    can distinguish "no schema" from "empty schema".
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
        parent_fields = resolve_table_fields(parent, schemas, _seen)
        if parent_fields is not None:
            fields |= parent_fields
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


def check_methods(src_root, results, registry=None):
    """Check that documented method calls reference real methods.

    AST-based. Handles aliased imports, module-qualified receivers, and
    multi-line calls — see iter_python_blocks / resolve_receiver.
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
                    # Unresolvable receiver (BinOp restriction, lowercase var,
                    # complex expression). Match prior regex behavior: skip.
                    continue
                class_name, instance_call, call_line = resolved
                line_num = block_start + call_line - 1
                location = f"{md_file.name}:{line_num}"

                methods = get_class_methods(class_name)
                if methods is None:
                    # Uppercase-first identifier that isn't registered —
                    # probably a typo or a missing entry. Lowercase names
                    # (instance vars) never reach this branch because
                    # resolve_receiver returns a bare Name's id unchanged
                    # and the registry has no lowercase keys.
                    if (
                        class_name[:1].isupper()
                        and class_name not in DOC_PLACEHOLDERS
                    ):
                        results.warn(
                            f"{location}: unresolved class "
                            f"'{class_name}' in '{class_name}."
                            f"{method_name}()' — typo, or add to "
                            f"KNOWN_CLASSES/DOC_PLACEHOLDERS"
                        )
                    continue

                if method_name not in methods:
                    results.fail(
                        f"{location}: {class_name}.{method_name}() "
                        f"NOT FOUND on {class_name}"
                    )
                    continue

                info = methods[method_name]
                # Instance-only method called on bare class?
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
                else:
                    results.ok(
                        f"{location}: {class_name}.{method_name}() valid "
                        f"({'instance' if instance_call else 'class/static'} call)"
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
    evals_path = SKILL_DIR / "evals" / "evals.json"
    if not evals_path.exists():
        return
    try:
        data = json.loads(evals_path.read_text())
    except json.JSONDecodeError as e:
        results.fail(f"evals.json: JSON parse error: {e}")
        return

    for eval_entry in data.get("evals", []):
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
            # signal (unresolved-class warnings) for them below.
            start = match.start()
            in_backticks = start > 0 and text[start - 1] == "`"

            if method_name in SKIP_METHODS or method_name.startswith("_"):
                continue

            methods = registry.methods(class_name)
            location = f"evals.json[id={eval_id}]"

            if methods is None:
                if (
                    in_backticks
                    and class_name[:1].isupper()
                    and class_name not in DOC_PLACEHOLDERS
                ):
                    results.warn(
                        f"{location}: unresolved class '{class_name}' in "
                        f"'{class_name}.{method_name}()' — typo, or add to "
                        f"KNOWN_CLASSES/DOC_PLACEHOLDERS"
                    )
                continue

            if method_name not in methods:
                results.fail(
                    f"{location}: {class_name}.{method_name}() "
                    f"NOT FOUND on {class_name}"
                )
                continue

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
            else:
                results.ok(
                    f"{location}: {class_name}.{method_name}() valid"
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
    # skills; 1150 gives headroom over the realistic post-migration size while
    # still forcing migration rather than unbounded growth.
    body = re.sub(r"^---\n.*?\n---\n", "", skill_content, count=1, flags=re.DOTALL)
    body_words = len(body.split())
    body_lines = body.count("\n") + 1
    WORD_HARD_CAP = 1150
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

    print("\n[1/16] Checking source files and class registry...")
    check_class_files_exist(src_root, results)

    print("[2/16] Checking import statements in skill files...")
    check_imports(src_root, results)

    # Build the class registry once and share it across method + kwarg checks
    registry = _ClassRegistry(src_root, results)

    print("[3/16] Checking method references...")
    check_methods(src_root, results, registry=registry)

    print("[4/16] Checking keyword arguments...")
    check_kwargs(src_root, results, registry=registry)

    print("[5/16] Checking skill structure...")
    check_structure(results)

    print("[6/16] Checking prose assertions...")
    check_prose_assertions(results)

    print("[7/16] Parsing Python code blocks (ast.parse)...")
    check_python_syntax(results)

    print("[8/16] Verifying prose path references exist in repo...")
    check_prose_paths(src_root, results)

    print("[9/16] Verifying notebook names exist in repo...")
    check_notebook_names(src_root, results)

    print("[10/16] Verifying internal markdown links and anchors...")
    check_markdown_links(results)

    print("[11/16] Scanning for documented anti-patterns...")
    check_anti_patterns(results)

    print("[12/16] Checking dict-restriction field names against schemas...")
    check_restriction_fields(src_root, results)

    print("[13/16] Verifying citation line numbers are in range...")
    check_citation_lines(src_root, results)

    print("[14/16] Scanning evals.json for hallucinated class/method refs...")
    check_evals_content(src_root, results, registry=registry)

    print("[15/16] Scanning prose for banned PR-number citations...")
    check_no_pr_citations(results)

    print("[16/16] Enforcing reference-file and section size budgets...")
    check_section_budgets(results)

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
    #   warnings + --strict → exit 1
    #   warnings alone → exit 0, but message distinguishes from clean
    has_failures = bool(results.failed)
    has_warnings = bool(results.warnings)

    if has_failures:
        print("\nSome checks failed — review and fix the skill files.")
        return 1
    if has_warnings:
        suffix = " (--strict: treated as failure)" if args.strict else ""
        print(f"\nPassed with {len(results.warnings)} warning(s){suffix} — "
              "review above.")
        return 1 if args.strict else 0
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
