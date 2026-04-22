#!/usr/bin/env python3
"""Print a DataJoint / Spyglass config file with secrets masked.

Reads `dj_local_conf.json` or `~/.datajoint_config.json` and emits the
same JSON with sensitive fields (password, access_key, secret_key, token,
credential, api_key, auth) replaced by the literal string
``"***MASKED***"``. Host, user, port, and directory paths are preserved so
an agent or reviewer can still inspect the environment without leaking
credentials into the conversation history.

The scrubbing header is written to stderr; the scrubbed body is written
to stdout so you can pipe (``python scrub_dj_config.py | jq .database.host``)
without header contamination.

Exit codes:
    0 - success
    2 - no config file found at default or explicit path
    3 - config file exists but contains invalid JSON
    4 - unexpected failure (raw file is NEVER printed as a fallback)

Lifecycle: this is a prototype. Upstream candidate is
``spyglass.settings.scrub_config()`` + a ``python -m spyglass.settings``
entry point. The pure functions (``is_sensitive_key``, ``scrub``,
``load_config``) are structured to lift verbatim; CLI glue stays here
until upstream decides where the entry point belongs. Retire this file
from the skill when the upstream merges land.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

MASKED = "***MASKED***"

_SENSITIVE_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "credential",
    "access_key",
    "api_key",
    "auth",
)

def _default_config_paths() -> tuple[Path, ...]:
    """Resolve default config lookup paths lazily.

    Called every lookup rather than computed at import time so that
    long-running processes or tests that rebind ``$HOME`` still see
    the current user's home directory.
    """
    return (
        Path("./dj_local_conf.json"),
        Path("~/.datajoint_config.json").expanduser(),
    )


def is_sensitive_key(dotted_path: str) -> bool:
    """Return True if the final segment of a dotted key path looks sensitive.

    Matching is case-insensitive on the final segment only. This keeps
    nested sections named like ``credentials: {...}`` from being masked
    wholesale — each leaf inside is evaluated on its own terminal segment.
    """
    if not dotted_path:
        return False
    final_segment = dotted_path.rsplit(".", 1)[-1].lower()
    return any(token in final_segment for token in _SENSITIVE_SUBSTRINGS)


def scrub(config: dict, unmask: Iterable[str] = ()) -> dict:
    """Recursively replace sensitive values with ``MASKED``.

    ``unmask`` is a collection of dotted key paths to leave intact even
    if they match a sensitive pattern — an explicit escape hatch for
    debugging. A sensitive key that points to a dict or list has the
    ENTIRE subtree replaced with ``MASKED``, because leaves inside (e.g.
    ``credentials.signing_key`` where the per-leaf name isn't itself
    recognized as sensitive) would otherwise leak.
    """
    unmask_set = set(unmask)
    return _scrub_recursive(config, prefix="", unmask=unmask_set)


def _scrub_recursive(value, prefix: str, unmask: set[str]):
    if prefix in unmask:
        return value
    if is_sensitive_key(prefix) and value not in (None, ""):
        # Sensitive key → mask the whole subtree regardless of shape.
        # A dict / list under a sensitive key can hold nested secrets
        # whose per-leaf names don't match the predicate (see review
        # finding "dict-as-sensitive-leaf leaks").
        return MASKED
    if isinstance(value, dict):
        return {
            key: _scrub_recursive(
                item, _extend_path(prefix, key), unmask
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _scrub_recursive(item, f"{prefix}[{i}]", unmask)
            for i, item in enumerate(value)
        ]
    return value


def _extend_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def find_config_file(explicit: Path | None = None) -> Path:
    """Resolve the config path to scrub.

    Returns the explicit path when given (without checking existence — the
    caller decides how to handle missing explicit paths). Otherwise walks
    the default locations in order and returns the first existing file.

    Raises
    ------
    FileNotFoundError
        If no explicit path was provided and none of the defaults exist.
    """
    if explicit is not None:
        return explicit
    for candidate in _default_config_paths():
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "No DataJoint config found. Looked at: "
        + ", ".join(str(p) for p in _default_config_paths())
    )


def load_config(path: Path) -> dict:
    """Load and parse a JSON config file, raising on invalid JSON."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print a DataJoint config file with secrets masked. "
            "Safe to run in conversation history — password and other "
            "sensitive leaves are replaced with '***MASKED***'."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "Path to a DataJoint config JSON. Defaults: "
            "./dj_local_conf.json, then ~/.datajoint_config.json."
        ),
    )
    parser.add_argument(
        "--unmask",
        default="",
        help=(
            "Comma-separated dotted key paths to leave unmasked in "
            "stdout. DO NOT use inside a Claude / agent conversation — "
            "unmasked values enter the model's context and tool-result "
            "history. Local-shell debugging only."
        ),
    )
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument(
        "--json",
        dest="compact",
        action="store_true",
        help="Emit compact JSON (default is pretty-printed).",
    )
    output_format.add_argument(
        "--pretty",
        dest="compact",
        action="store_false",
        help="Pretty-print output (default).",
    )
    parser.set_defaults(compact=False)

    args = parser.parse_args(argv)

    try:
        resolved = find_config_file(
            Path(args.path).expanduser() if args.path else None
        )
    except FileNotFoundError as exc:
        print(f"scrub_dj_config: {exc}", file=sys.stderr)
        return 2

    if args.path and not resolved.exists():
        print(
            f"scrub_dj_config: no such file: {resolved}",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_config(resolved)
    except json.JSONDecodeError as exc:
        print(
            f"scrub_dj_config: invalid JSON in {resolved}: "
            f"{exc.msg} at line {exc.lineno} col {exc.colno}",
            file=sys.stderr,
        )
        return 3
    except (
        UnicodeDecodeError, PermissionError, IsADirectoryError, OSError,
    ) as exc:
        # Any other read-side failure (non-UTF-8 bytes, perms, symlink
        # loop, passed a dir by mistake). Report the exception class
        # only — the default traceback could include bytes from the
        # offending file.
        print(
            f"scrub_dj_config: could not read {resolved}: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return 4

    try:
        unmask = tuple(
            key.strip() for key in args.unmask.split(",") if key.strip()
        )
        if unmask:
            # Loud stderr banner — --unmask is the designed escape hatch
            # but leaves raw values in stdout, which lands in tool-result
            # / conversation history for any agent running the script.
            print(
                "scrub_dj_config: WARNING --unmask leaves "
                f"{len(unmask)} key(s) raw in stdout: "
                f"{', '.join(unmask)}. Do NOT run inside an active Claude "
                "conversation — unmasked values enter context history.",
                file=sys.stderr,
            )
        scrubbed = scrub(config, unmask=unmask)
    except Exception as exc:  # noqa: BLE001 — deliberate: never leak raw
        print(
            f"scrub_dj_config: SCRUB FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 4

    print(f"Scrubbed config from: {resolved}", file=sys.stderr)
    if args.compact:
        print(json.dumps(scrubbed, separators=(",", ":")))
    else:
        print(json.dumps(scrubbed, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
