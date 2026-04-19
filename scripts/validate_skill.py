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
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
REFERENCES_DIR = SKILL_DIR / "references"

# No hardcoded default — use --spyglass-src or run from the repo root
DEFAULT_SPYGLASS_SRC = None

# Patterns to extract from markdown (inside code blocks only)
IMPORT_PATTERN = re.compile(
    r"from\s+(spyglass[\w.]+)\s+import\s+([^#\n]+)"
)
# Plain module imports: `import spyglass.x.y` or `import spyglass.x.y as alias`
PLAIN_IMPORT_PATTERN = re.compile(
    r"import\s+(spyglass[\w.]*)(?:\s+as\s+\w+)?"
)
# Match method calls: capture whether `()` was used before the method
# Group 1: class name; Group 2: "()" if instance-call, "" if bare class access; Group 3: method name
METHOD_CALL_PATTERN = re.compile(
    r"(\w+)(\(\))?\.(\w+)\s*\("
)
# Keyword-argument extraction is done in two stages: locate the method call
# (METHOD_CALL_PATTERN above), then scan all `name=value` pairs inside its
# argument list with KWARG_SCAN. The two-stage approach avoids the single-regex
# pitfall of only matching the first kwarg per call.
# Matches a bare `name=` (but not `==`, `<=`, `>=`, `!=`), capturing the name.
KWARG_SCAN = re.compile(r"(?<![=!<>])\b(\w+)\s*=(?!=)")

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
    "delete_downstream_parts",  # set on SpyglassMixin dynamically
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

# Uppercase-first identifiers that appear before a `.method(` but are NOT
# Spyglass classes — doc placeholders, generic table stand-ins. Without this
# list, the unresolved-class warning would fire spuriously on them.
DOC_PLACEHOLDERS = {
    "Table", "Table1", "Table2", "MergeTable",
    "MyTable", "SomeTable", "UpstreamTable", "UpstreamA", "UpstreamB",
    "ParamTable", "SelectionTable",
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
    """Extract code block contents with line numbers.

    Returns a list of (start_line, [(line_num, line)]) tuples. Callers that
    need to match multi-line expressions should also consider join_logical_lines
    which fuses lines that continue inside open brackets/parens.
    """
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
                blocks.append((block_start, lang, "\n".join(body)))
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


def join_logical_lines(block_lines):
    """Fuse physical lines into logical lines across open brackets/parens.

    Returns a list of (start_line_num, joined_source) tuples. The line number
    is the line where the logical line begins, so failures can be reported at
    a sensible location even when the offending call spans multiple lines.
    """
    joined = []
    buf = []
    buf_start = None
    depth = 0

    for line_num, line in block_lines:
        if buf_start is None:
            buf_start = line_num
        buf.append(line)
        # Count unmatched opening brackets on this line to decide continuation
        # Simple counter; strings with brackets are rare in the skill examples
        # and the validator is regex-based anyway so minor miscounts are
        # self-correcting on the next closing line
        for ch in line:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
        if depth == 0:
            joined.append((buf_start, " ".join(buf)))
            buf = []
            buf_start = None

    # Flush any remaining buffer (unbalanced — shouldn't happen for valid code)
    if buf:
        joined.append((buf_start, " ".join(buf)))

    return joined


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

    Handles both `from spyglass.x import a, b, c` and
    plain `import spyglass.x[.y] [as alias]` forms, using join_logical_lines
    so multiline imports are matched as a single logical line.
    """
    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in join_logical_lines(block_lines):
                # from spyglass.x import a, b, c
                for match in IMPORT_PATTERN.finditer(line):
                    module_path = match.group(1)
                    raw_names = match.group(2)
                    names = []
                    for n in raw_names.split(","):
                        n = n.strip().rstrip(",").rstrip(")").lstrip("(")
                        if not n or n.startswith("#"):
                            continue
                        # Strip `as alias` — we validate the original name
                        n = n.split(" as ")[0].strip()
                        names.append(n)
                    location = f"{md_file.name}:{line_num}"
                    check_module_exports(
                        src_root, module_path, names, results, location
                    )
                # import spyglass.x[.y] [as alias]
                for match in PLAIN_IMPORT_PATTERN.finditer(line):
                    module_path = match.group(1)
                    location = f"{md_file.name}:{line_num}"
                    mod_file = _resolve_module_file(src_root, module_path)
                    if mod_file is not None:
                        results.ok(
                            f"{location}: import {module_path} resolves"
                        )
                    else:
                        results.fail(
                            f"{location}: import {module_path} — "
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
    """Check that documented method calls reference real methods."""
    if registry is None:
        registry = _ClassRegistry(src_root, results)

    def get_class_methods(class_name):
        return registry.methods(class_name)

    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in join_logical_lines(block_lines):
                for match in METHOD_CALL_PATTERN.finditer(line):
                    class_name = match.group(1)
                    instance_call = bool(match.group(2))  # True if "()" used
                    method_name = match.group(3)

                    if method_name in SKIP_METHODS:
                        continue
                    if method_name.startswith("_"):
                        continue

                    methods = get_class_methods(class_name)
                    location = f"{md_file.name}:{line_num}"
                    if methods is None:
                        # Heuristic: uppercase-first identifiers that don't
                        # resolve are probably typos or classes missing from
                        # the registry. Lowercase names are instance vars
                        # (e.g. `sel.start_export`) — skip those silently.
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
    """Check that documented keyword arguments exist in method signatures."""
    if registry is None:
        registry = _ClassRegistry(src_root, results)

    def get_class_methods(class_name):
        return registry.methods(class_name)

    for md_file in collect_md_files():
        content = md_file.read_text()
        blocks = extract_code_blocks(content)

        for block_start, block_lines in blocks:
            for line_num, line in join_logical_lines(block_lines):
                # Find each method call, then scan its full arg list for kwargs
                for match in METHOD_CALL_PATTERN.finditer(line):
                    class_name = match.group(1)
                    method_name = match.group(3)

                    if method_name in SKIP_METHODS:
                        continue
                    if method_name.startswith("_"):
                        continue

                    methods = get_class_methods(class_name)
                    if methods is None:
                        continue
                    if method_name not in methods:
                        continue  # Caught by check_methods

                    method_info = methods[method_name]
                    arg_list = _extract_arg_list(line, match.end() - 1)
                    if arg_list is None:
                        continue

                    for kmatch in KWARG_SCAN.finditer(arg_list):
                        kwarg_name = kmatch.group(1)
                        if kwarg_name in SKIP_KWARGS:
                            continue
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


def _extract_arg_list(line, open_paren_idx):
    """Return the text between matched parens starting at open_paren_idx.

    Tracks nested parens/brackets. Returns None if the parens don't close
    within the line (join_logical_lines usually handles that upstream).
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
    """
    # (file, rule_id, description, required_substring (case-insensitive))
    required_claims = [
        (
            "SKILL.md", "destructive-list",
            "SKILL.md fences merge-table delete helpers",
            "merge_delete",
        ),
        (
            "SKILL.md", "destructive-confirmation",
            "SKILL.md requires explicit confirmation for destructive ops",
            "explicit confirmation",
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
        if not md_file.exists():
            results.fail(f"prose[{rule_id}]: file {rel_path} not found")
            continue
        content = md_file.read_text().lower()
        if needle.lower() in content:
            results.ok(f"prose[{rule_id}]: {description}")
        else:
            results.fail(
                f"prose[{rule_id}]: {rel_path} missing required claim "
                f"'{needle}' ({description})"
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

    Rules we cover: lowercase, strip markdown symbols, replace spaces with
    hyphens, drop characters that aren't [a-z0-9_-]. Backticks and periods
    are dropped too. Good enough for the skill's actual headings — we
    don't try to handle every edge case GitHub handles.
    """
    s = heading.strip().lower()
    s = re.sub(r"[`*_]", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
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
        # Match `(SomeMergeTable & anything).merge_xxx(` where xxx is one
        # of the known _Merge classmethods. Bracket-balanced `[^)]*` in
        # the restriction expression works for typical one-line cases.
        # Skip matches whose line already contains `#` before the match —
        # those are demonstration comments explaining the bad pattern,
        # not runnable code.
        lambda body: [
            (m.start(), m.group(0))
            for m in re.finditer(
                r"\(\s*\w+\s*&[^)]+\)\s*\."
                r"(?:merge_delete|merge_delete_parent|merge_restrict"
                r"|merge_get_part|merge_get_parent|merge_view|merge_html)"
                r"\s*\(",
                body,
            )
            if "#" not in body[body.rfind("\n", 0, m.start()) + 1 : m.start()]
        ],
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

    # SKILL.md body size — Anthropic guidance says frequently-loaded skills
    # should aim for <500 words. A routing-heavy skill like this one with
    # many pipeline references won't hit that, but a soft cap prevents bloat.
    body = re.sub(r"^---\n.*?\n---\n", "", skill_content, count=1, flags=re.DOTALL)
    body_words = len(body.split())
    body_lines = body.count("\n") + 1
    WORD_SOFT_CAP = 1700    # router-heavy skill with feedback loops + merge-tables precision
    LINE_HARD_CAP = 500     # Anthropic's explicit cap on SKILL.md body
    if body_words > WORD_SOFT_CAP:
        results.warn(
            f"body: SKILL.md body is {body_words} words "
            f"(soft cap {WORD_SOFT_CAP}; Anthropic target <500 for "
            f"frequently-loaded skills). Consider migrating content to references."
        )
    else:
        results.ok(f"body: SKILL.md body {body_words} words (<{WORD_SOFT_CAP})")
    if body_lines > LINE_HARD_CAP:
        results.fail(
            f"body: SKILL.md body is {body_lines} lines; "
            f"Anthropic caps it at {LINE_HARD_CAP}"
        )
    else:
        results.ok(f"body: SKILL.md body {body_lines} lines (<{LINE_HARD_CAP})")

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

    print("\n[1/11] Checking source files and class registry...")
    check_class_files_exist(src_root, results)

    print("[2/11] Checking import statements in skill files...")
    check_imports(src_root, results)

    # Build the class registry once and share it across method + kwarg checks
    registry = _ClassRegistry(src_root, results)

    print("[3/11] Checking method references...")
    check_methods(src_root, results, registry=registry)

    print("[4/11] Checking keyword arguments...")
    check_kwargs(src_root, results, registry=registry)

    print("[5/11] Checking skill structure...")
    check_structure(results)

    print("[6/11] Checking prose assertions...")
    check_prose_assertions(results)

    print("[7/11] Parsing Python code blocks (ast.parse)...")
    check_python_syntax(results)

    print("[8/11] Verifying prose path references exist in repo...")
    check_prose_paths(src_root, results)

    print("[9/11] Verifying notebook names exist in repo...")
    check_notebook_names(src_root, results)

    print("[10/11] Verifying internal markdown links and anchors...")
    check_markdown_links(results)

    print("[11/11] Scanning for documented anti-patterns...")
    check_anti_patterns(results)

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
