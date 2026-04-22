#!/usr/bin/env python3
"""Verify a Spyglass environment is ready to populate.

Runs seven one-shot checks an agent or user can invoke at session
start (or when something mysteriously breaks):

1. dj_config_loaded         — `datajoint` imports; `dj.config` has
                              database.host and database.user.
2. spyglass_importable      — `import spyglass` succeeds.
3. base_dir_resolved        — SPYGLASS_BASE_DIR is discoverable via
                              dj.config["custom"]["spyglass_dirs"]["base"]
                              or the $SPYGLASS_BASE_DIR env var.
4. base_dir_exists_writable — the resolved path exists and accepts a
                              touch-then-unlink (not `os.access`, which
                              lies on some filesystems).
5. subdirs_exist_writable   — raw / analysis / recording / sorting /
                              waveforms / temp all exist under base
                              and are writable.
6. dj_connection            — `dj.conn().ping()` with a hard timeout
                              (default 10s). Traceback is NOT printed
                              on failure — connection strings can
                              leak through it.
7. version_pins             — installed versions of datajoint, pynwb,
                              spikeinterface, hdmf, ndx-franklab-novela,
                              and trodes-to-nwb are within the pins
                              Spyglass's pyproject.toml declares. Drift
                              is warn-only; missing packages warn too.

Output: status glyph + message per check (or JSON via --json).
Exit codes: 0 on no fails (and no warns under --strict); 1 otherwise.
Skips do NOT cause non-zero exit — they indicate the check couldn't
run, not that something's wrong.

Spyglass already ships scripts/validate.py covering checks 1, 2, and
a timeout-less variant of 6. This script duplicates minimal check
logic so it runs against any pip-install (no source checkout
required), and adds checks 3-5, 7, plus the DB timeout and JSON
output upstream doesn't have yet. Lifecycle: prototype; upstream
candidate is a fleshed-out `spyglass.utils.diagnostics` module that
supersedes both `scripts/validate.py` and this wrapper.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["ok", "warn", "fail", "skip"]

_GLYPHS = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "·"}

_PIN_PACKAGES = (
    "datajoint",
    "pynwb",
    "spikeinterface",
    "hdmf",
    "ndx-franklab-novela",
    "trodes-to-nwb",
)

# Fallback list used when SpyglassConfig isn't importable. Names match
# the keys in dj.config["custom"]["spyglass_dirs"] and the attribute
# shape of spyglass.settings.SpyglassConfig.
_FALLBACK_SUBDIRS = (
    "raw",
    "analysis",
    "recording",
    "sorting",
    "waveforms",
    "temp",
)


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_dj_config_loaded() -> CheckResult:
    try:
        import datajoint as dj
    except ImportError:
        return CheckResult(
            name="dj_config_loaded",
            status="skip",
            message="datajoint not installed (pip install datajoint)",
        )
    host = dj.config.get("database.host")
    user = dj.config.get("database.user")
    if not host or not user:
        return CheckResult(
            name="dj_config_loaded",
            status="fail",
            message=(
                "dj.config missing database.host / database.user — see "
                "setup_config.md for the canonical config shape"
            ),
            evidence={"host_set": bool(host), "user_set": bool(user)},
        )
    return CheckResult(
        name="dj_config_loaded",
        status="ok",
        message=f"host={host}  user={user}",
        evidence={"host": host, "user": user},
    )


def check_spyglass_importable() -> CheckResult:
    try:
        import spyglass
    except ImportError:
        return CheckResult(
            name="spyglass_importable",
            status="skip",
            message="spyglass not installed (pip install spyglass-neurodata)",
        )
    version = getattr(spyglass, "__version__", "unknown")
    file_attr = getattr(spyglass, "__file__", None)
    path = Path(file_attr).parent if file_attr else Path("<unknown>")
    return CheckResult(
        name="spyglass_importable",
        status="ok",
        message=f"spyglass {version} at {path}",
        evidence={"version": version, "path": str(path)},
    )


def check_base_dir_resolved() -> CheckResult:
    base, source = _resolve_base_dir()
    if not base:
        return CheckResult(
            name="base_dir_resolved",
            status="fail",
            message=(
                "SPYGLASS_BASE_DIR not set in dj.config['custom']"
                "['spyglass_dirs']['base'] or the environment — see "
                "setup_config.md"
            ),
        )
    return CheckResult(
        name="base_dir_resolved",
        status="ok",
        message=f"{base}  (source: {source})",
        evidence={"base_dir": base, "source": source},
    )


def check_base_dir_exists_writable() -> CheckResult:
    base, _ = _resolve_base_dir()
    if base is None:
        return CheckResult(
            name="base_dir_exists_writable",
            status="skip",
            message="base dir not resolved (see base_dir_resolved)",
        )
    path = Path(base)
    if not path.exists():
        return CheckResult(
            name="base_dir_exists_writable",
            status="fail",
            message=f"{path} does not exist",
            evidence={"path": str(path)},
        )
    ok, reason = _test_writable(path)
    if not ok:
        return CheckResult(
            name="base_dir_exists_writable",
            status="fail",
            message=f"{path} exists but write test failed: {reason}",
            evidence={"path": str(path), "reason": reason},
        )
    return CheckResult(
        name="base_dir_exists_writable",
        status="ok",
        message=str(path),
        evidence={"path": str(path)},
    )


def check_subdirs_exist_writable() -> CheckResult:
    base, _ = _resolve_base_dir()
    if not base:
        return CheckResult(
            name="subdirs_exist_writable",
            status="skip",
            message="base dir not resolved (see base_dir_resolved)",
        )

    subdirs = _expected_subdirs()
    per_subdir: dict[str, str] = {}
    missing: list[str] = []
    not_writable: list[str] = []

    for name in subdirs:
        p = Path(base) / name
        if not p.exists():
            missing.append(name)
            per_subdir[name] = "missing"
            continue
        ok, _ = _test_writable(p)
        if not ok:
            not_writable.append(name)
            per_subdir[name] = "not_writable"
        else:
            per_subdir[name] = "ok"

    total = len(subdirs)
    writable_count = total - len(missing) - len(not_writable)

    if missing or not_writable:
        return CheckResult(
            name="subdirs_exist_writable",
            status="fail",
            message=(
                f"{writable_count}/{total} writable "
                f"(missing: {missing or '-'}  "
                f"not_writable: {not_writable or '-'})"
            ),
            evidence={
                "subdirs": per_subdir,
                "missing": missing,
                "not_writable": not_writable,
            },
        )
    return CheckResult(
        name="subdirs_exist_writable",
        status="ok",
        message=f"{total}/{total} writable",
        evidence={"subdirs": per_subdir},
    )


def check_dj_connection(timeout: int = 10) -> CheckResult:
    """Connect with a hard wall-clock timeout.

    Uses a daemon thread instead of ``signal.alarm`` for portability
    (alarm is Unix-only and can't interrupt a socket-level hang
    reliably). If the connection hangs past ``timeout``, the check
    reports fail and returns — the underlying thread is abandoned
    (daemon=True) so it doesn't block process exit.
    """
    try:
        import datajoint as dj
    except ImportError:
        return CheckResult(
            name="dj_connection",
            status="skip",
            message="datajoint not installed",
        )

    result: dict = {}

    def _attempt() -> None:
        try:
            started = time.monotonic()
            conn = dj.conn()
            conn.ping()
            result["duration_s"] = time.monotonic() - started
            result["ok"] = True
        except Exception as exc:  # noqa: BLE001 — class-only reporting
            # Never include str(exc) — DataJoint exception messages can
            # include the full connection string with credentials.
            result["error"] = type(exc).__name__

    worker = threading.Thread(target=_attempt, daemon=True)
    worker.start()
    worker.join(timeout=timeout)

    if worker.is_alive():
        return CheckResult(
            name="dj_connection",
            status="fail",
            message=f"timed out after {timeout}s (server unreachable?)",
            evidence={"timeout_s": timeout},
        )
    if "error" in result:
        return CheckResult(
            name="dj_connection",
            status="fail",
            message=f"connection failed: {result['error']}",
            evidence={"error_class": result["error"]},
        )
    duration = result.get("duration_s", 0.0)
    return CheckResult(
        name="dj_connection",
        status="ok",
        message=f"connected in {duration:.2f}s",
        evidence={"duration_s": duration},
    )


def check_version_pins() -> CheckResult:
    try:
        import spyglass  # noqa: F401
    except ImportError:
        return CheckResult(
            name="version_pins",
            status="skip",
            message="spyglass not installed",
        )

    try:
        requires = importlib.metadata.requires("spyglass-neurodata") or []
    except importlib.metadata.PackageNotFoundError:
        return CheckResult(
            name="version_pins",
            status="skip",
            message="could not read spyglass-neurodata package metadata",
        )

    try:
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return CheckResult(
            name="version_pins",
            status="skip",
            message=(
                "`packaging` not available — pip install packaging "
                "to enable version-pin checks"
            ),
        )

    # Map each package we care about to its pin string (if any).
    pins: dict[str, str | None] = dict.fromkeys(_PIN_PACKAGES, None)
    for req_str in requires:
        try:
            req = Requirement(req_str)
        except Exception:  # noqa: BLE001 — requires strings are noisy
            continue
        name = req.name.lower()
        if name in pins:
            pins[name] = str(req.specifier) if req.specifier else None

    per_pkg: dict[str, dict] = {}
    outside_pin: list[str] = []
    missing: list[str] = []

    for pkg, pin in pins.items():
        try:
            installed = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            if pin is None:
                # Spyglass doesn't pin this package (e.g. trodes-to-nwb
                # is an optional neighbor, not in pyproject.toml).
                # "Not installed and no declared pin" is not drift —
                # just report as skipped rather than noisy `missing`.
                per_pkg[pkg] = {"installed": None, "pin": None, "status": "skipped"}
                continue
            per_pkg[pkg] = {"installed": None, "pin": pin, "status": "missing"}
            missing.append(pkg)
            continue
        if pin:
            try:
                ok = Version(installed) in SpecifierSet(pin)
            except InvalidVersion:
                # Conservative: if the version string can't be parsed
                # (e.g. git-local dev build), don't flag it.
                per_pkg[pkg] = {
                    "installed": installed,
                    "pin": pin,
                    "status": "unparseable",
                }
                continue
        else:
            ok = True
        if not ok:
            per_pkg[pkg] = {
                "installed": installed,
                "pin": pin,
                "status": "outside",
            }
            outside_pin.append(f"{pkg} {installed} (pin: {pin})")
        else:
            per_pkg[pkg] = {
                "installed": installed,
                "pin": pin,
                "status": "ok",
            }

    # Drift is warn-only — pins are guidelines; the DB may still accept
    # a near-pin version. A hard fail would be too noisy given how
    # often labs pin slightly ahead for reasons.
    if outside_pin or missing:
        parts = []
        if outside_pin:
            parts.append("outside pin: " + "; ".join(outside_pin))
        if missing:
            parts.append("not installed: " + ", ".join(missing))
        return CheckResult(
            name="version_pins",
            status="warn",
            message="; ".join(parts),
            evidence={
                "packages": per_pkg,
                "outside_pins": outside_pin,
                "missing": missing,
            },
        )
    return CheckResult(
        name="version_pins",
        status="ok",
        message=f"{len(_PIN_PACKAGES)}/{len(_PIN_PACKAGES)} within pins",
        evidence={"packages": per_pkg},
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_base_dir() -> tuple[str | None, str | None]:
    """Walk the same priority order as SpyglassConfig: dj.config →
    environment. Returns ``(path, source_label)`` or ``(None, None)``.
    """
    try:
        import datajoint as dj

        custom = dj.config.get("custom") or {}
        spyglass_dirs = custom.get("spyglass_dirs") or {}
        from_config = spyglass_dirs.get("base")
        if from_config:
            return from_config, "dj.config"
    except ImportError:
        pass
    from_env = os.environ.get("SPYGLASS_BASE_DIR")
    if from_env:
        return from_env, "env var SPYGLASS_BASE_DIR"
    return None, None


def _test_writable(path: Path) -> tuple[bool, str]:
    """Touch-then-unlink write test. More reliable than ``os.access``,
    which lies on some filesystems (NFS ACLs, container bind-mounts).
    """
    probe = path / ".spyglass_verify_write_test"
    try:
        probe.touch()
        probe.unlink()
    except Exception as exc:  # noqa: BLE001 — class-only reporting
        return False, type(exc).__name__
    return True, ""


def _expected_subdirs() -> tuple[str, ...]:
    """Try to get subdir names from SpyglassConfig so we track upstream
    if they rename anything; fall back to the hardcoded list.
    """
    try:
        from spyglass.settings import SpyglassConfig

        config = SpyglassConfig()
        names: list[str] = []
        for attr in (
            "raw_dir",
            "analysis_dir",
            "recording_dir",
            "sorting_dir",
            "waveforms_dir",
            "temp_dir",
        ):
            value = getattr(config, attr, None)
            if value:
                names.append(Path(str(value)).name)
        if names:
            return tuple(names)
    except Exception:  # noqa: BLE001 — any import / init failure falls back
        pass
    return _FALLBACK_SUBDIRS


# ---------------------------------------------------------------------------
# Registry, runner, rendering
# ---------------------------------------------------------------------------


CHECKS: dict[str, Callable[..., CheckResult]] = {
    "dj_config_loaded": check_dj_config_loaded,
    "spyglass_importable": check_spyglass_importable,
    "base_dir_resolved": check_base_dir_resolved,
    "base_dir_exists_writable": check_base_dir_exists_writable,
    "subdirs_exist_writable": check_subdirs_exist_writable,
    "dj_connection": check_dj_connection,
    "version_pins": check_version_pins,
}


def run(
    selected: list[str] | None = None,
    timeout: int = 10,
) -> list[CheckResult]:
    """Run the selected checks in registry order.

    ``selected`` is an allowlist of check names. ``None`` runs every
    check. Unknown names raise ``KeyError`` — CLI surfaces that as a
    clean error.
    """
    names = selected if selected else list(CHECKS)
    results = []
    for name in names:
        fn = CHECKS[name]
        if name == "dj_connection":
            results.append(fn(timeout=timeout))
        else:
            results.append(fn())
    return results


def _render_human(results: list[CheckResult]) -> str:
    lines = []
    width = max((len(r.name) for r in results), default=0)
    for r in results:
        glyph = _GLYPHS[r.status]
        lines.append(f"{r.name:<{width}}  {glyph} {r.message}")
    summary = _summary(results)
    lines.append("")
    lines.append(
        f"{summary['ok']} ok, {summary['warn']} warn, "
        f"{summary['fail']} fail, {summary['skip']} skip"
    )
    return "\n".join(lines)


def _render_json(results: list[CheckResult], exit_code: int) -> str:
    summary = _summary(results)
    payload = {
        "results": [asdict(r) for r in results],
        "summary": summary,
        "exit_code": exit_code,
    }
    return json.dumps(payload, indent=2)


def _summary(results: list[CheckResult]) -> dict:
    buckets = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for r in results:
        buckets[r.status] += 1
    buckets["total"] = len(results)
    return buckets


def _decide_exit_code(results: list[CheckResult], strict: bool) -> int:
    if any(r.status == "fail" for r in results):
        return 1
    if strict and any(r.status == "warn" for r in results):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a Spyglass environment is ready to populate. "
            "Runs seven checks covering DataJoint config, base dirs, "
            "DB connection, and version pins."
        ),
    )
    parser.add_argument(
        "--check",
        action="append",
        metavar="NAME",
        help=(
            "Run only the named check (repeatable). "
            f"Available: {', '.join(CHECKS)}."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on warnings (e.g. version drift), not just fails.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of human-readable output.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        metavar="SECONDS",
        help="Timeout for the DB-connection check (default: 10).",
    )
    args = parser.parse_args(argv)

    if args.check:
        unknown = [n for n in args.check if n not in CHECKS]
        if unknown:
            print(
                f"verify_spyglass_env: unknown check(s): {', '.join(unknown)}. "
                f"Available: {', '.join(CHECKS)}.",
                file=sys.stderr,
            )
            return 2

    try:
        results = run(selected=args.check, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 — top-level safety net
        print(
            f"verify_spyglass_env: unexpected failure: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    exit_code = _decide_exit_code(results, strict=args.strict)
    if args.json:
        print(_render_json(results, exit_code))
    else:
        print(_render_human(results))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
