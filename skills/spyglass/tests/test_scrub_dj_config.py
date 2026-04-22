"""Tests for scripts/scrub_dj_config.py.

The whole point of this script is leak-prevention, so the tests lean on
two invariants: (1) every sensitive leaf must be masked across the
fixture corpus, and (2) stdout must be empty on any mid-scrub failure —
we never fall back to printing the raw file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "skills/spyglass/scripts/scrub_dj_config.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures/dj_config"


@pytest.fixture(scope="session")
def scrub_module():
    """Import scrub_dj_config as a module so we can exercise its API."""
    spec = importlib.util.spec_from_file_location(
        "scrub_dj_config", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# is_sensitive_key predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        # Positive matches — the substrings we explicitly target.
        ("database.password", True),
        ("password", True),
        ("stores.raw.access_key", True),
        ("stores.raw.secret_key", True),
        ("custom.kachery_cloud.api_token", True),
        ("custom.credentials", True),
        ("custom.auth_list[0].api_key", True),
        ("session_token", True),
        # Case insensitivity.
        ("Database.Password", True),
        ("STORES.RAW.ACCESS_KEY", True),
        # Negative matches — terminal segments that contain no sensitive
        # substring anywhere.
        ("database.host", False),
        ("database.user", False),
        ("database.port", False),
        ("stores.raw.location", False),
        ("stores.raw.stage", False),
        ("stores.raw.bucket", False),
        ("custom.spyglass_dirs.base", False),
        # Edge: value "authority" contains "auth" as a substring —
        # this is a KNOWN over-mask the predicate accepts because the
        # safer default is to mask anything resembling an auth field.
        # The escape hatch is --unmask authority.
        ("authority", True),
        # Edge: my_keyword contains "key" but not "access_key" / "api_key";
        # since we don't match bare "key", this is NOT masked.
        ("my_keyword", False),
        # Empty path is never sensitive.
        ("", False),
        # "credentials" anywhere triggers the predicate; when the value
        # is a dict/list the scrubber masks the whole subtree to avoid
        # leaking nested secrets whose per-leaf names aren't themselves
        # recognized (e.g. {"credentials": {"signing_key": "..."}}).
        ("credentials", True),
    ],
)
def test_is_sensitive_key(scrub_module, path, expected):
    assert scrub_module.is_sensitive_key(path) is expected


# ---------------------------------------------------------------------------
# scrub() on fixtures — preservation and masking invariants
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_scrub_preserves_non_sensitive_fields(scrub_module):
    """Host, user, port, and dir paths must be untouched."""
    config = _load_fixture("spyglass_custom.json")
    scrubbed = scrub_module.scrub(config)
    assert scrubbed["database.host"] == config["database.host"]
    assert scrubbed["database.port"] == config["database.port"]
    assert scrubbed["database.user"] == config["database.user"]
    assert (
        scrubbed["custom"]["spyglass_dirs"]["base"]
        == config["custom"]["spyglass_dirs"]["base"]
    )
    assert scrubbed["stores"]["raw"]["location"] == config["stores"]["raw"]["location"]


def test_scrub_masks_database_password_on_every_fixture(scrub_module):
    """Every fixture with a non-empty password must have it masked."""
    for fixture_name in (
        "basic.json",
        "with_stores.json",
        "spyglass_custom.json",
    ):
        config = _load_fixture(fixture_name)
        scrubbed = scrub_module.scrub(config)
        assert (
            scrubbed["database.password"] == scrub_module.MASKED
        ), f"password not masked in {fixture_name}"


def test_scrub_masks_store_access_and_secret_keys(scrub_module):
    config = _load_fixture("with_stores.json")
    scrubbed = scrub_module.scrub(config)
    assert scrubbed["stores"]["raw"]["access_key"] == scrub_module.MASKED
    assert scrubbed["stores"]["raw"]["secret_key"] == scrub_module.MASKED
    assert scrubbed["stores"]["raw"]["bucket"] == "example-raw-bucket"
    assert scrubbed["stores"]["raw"]["endpoint"] == "s3.amazonaws.com"


def test_scrub_masks_kachery_credentials_and_api_token(scrub_module):
    config = _load_fixture("spyglass_custom.json")
    scrubbed = scrub_module.scrub(config)
    zone = scrubbed["custom"]["kachery_cloud"]["zone"]
    assert zone["credentials"] == scrub_module.MASKED
    assert zone["client_id"] == "not-a-secret-per-se-but-identifier"
    assert zone["name"] == "example-lab.default"
    assert scrubbed["custom"]["kachery_cloud"]["api_token"] == scrub_module.MASKED


def test_scrub_masks_whole_list_under_sensitive_key(scrub_module):
    """``auth_list`` matches the sensitive-key predicate → whole list
    gets replaced with MASKED, not just the per-leaf api_key entries.
    This is the stronger contract that prevents leaks when a
    credential-bearing dict has leaves whose own names aren't
    themselves sensitive."""
    config = _load_fixture("edge_cases.json")
    scrubbed = scrub_module.scrub(config)
    assert scrubbed["custom"]["auth_list"] == scrub_module.MASKED


def test_scrub_leaves_empty_and_none_secrets_untouched(scrub_module):
    """Empty strings and nulls preserve — nothing to hide, and we want
    the reader to see the field was unset, not that we masked it."""
    config = _load_fixture("edge_cases.json")
    scrubbed = scrub_module.scrub(config)
    assert scrubbed["database.password"] == ""
    assert scrubbed["custom"]["credentials"] is None
    assert scrubbed["custom"]["empty_secret"] == ""


def test_scrub_unmask_escape_hatch(scrub_module):
    """--unmask on a specific path leaves that one untouched."""
    config = _load_fixture("with_stores.json")
    scrubbed = scrub_module.scrub(
        config, unmask=("stores.raw.access_key",)
    )
    assert scrubbed["stores"]["raw"]["access_key"] == "AKIAEXAMPLE1234"
    # Others still masked.
    assert scrubbed["stores"]["raw"]["secret_key"] == scrub_module.MASKED
    assert scrubbed["database.password"] == scrub_module.MASKED


def test_scrub_masks_dict_under_sensitive_key(scrub_module):
    """A sensitive key holding a dict: the WHOLE subtree must be masked.

    Regression for a leak where nested secrets whose per-leaf names
    weren't themselves recognized (e.g. ``credentials.signing_key``)
    escaped masking because the recursion descended before the
    sensitive-key check fired.
    """
    config = {
        "custom": {
            "kachery_cloud": {
                "credentials": {
                    "username": "someone",
                    "signing_material": "secret-signing-material",
                }
            }
        }
    }
    scrubbed = scrub_module.scrub(config)
    assert (
        scrubbed["custom"]["kachery_cloud"]["credentials"]
        == scrub_module.MASKED
    )


def test_scrub_masks_list_under_sensitive_key(scrub_module):
    """A sensitive key holding a list of dicts: whole list masked.

    Same regression as the dict case; lists of credential entries
    (e.g. a rotating auth-tokens list) must not leak.
    """
    config = {
        "custom": {
            "credentials_list": [
                {"user": "me", "pw": "p1"},
                {"user": "you", "pw": "p2"},
            ]
        }
    }
    scrubbed = scrub_module.scrub(config)
    assert scrubbed["custom"]["credentials_list"] == scrub_module.MASKED


# ---------------------------------------------------------------------------
# CLI — exit codes and the leak-prevention invariant
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_2_when_config_missing(tmp_path):
    missing = tmp_path / "nope.json"
    result = _run_cli([str(missing)])
    assert result.returncode == 2
    assert result.stdout == ""
    assert "no such file" in result.stderr.lower() or "not found" in result.stderr.lower()


def test_cli_exits_3_on_invalid_json(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text('{"database.host": "db.example.test"', encoding="utf-8")
    result = _run_cli([str(broken)])
    assert result.returncode == 3
    assert result.stdout == ""
    assert "invalid json" in result.stderr.lower()


def test_cli_success_masks_password_on_real_fixture():
    result = _run_cli([str(FIXTURES_DIR / "basic.json")])
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["database.password"] == "***MASKED***"
    assert parsed["database.host"] == "db.example.test"
    # Header went to stderr, not stdout.
    assert "Scrubbed config from" in result.stderr
    assert "Scrubbed config from" not in result.stdout


def test_cli_compact_json_flag():
    result = _run_cli(["--json", str(FIXTURES_DIR / "basic.json")])
    assert result.returncode == 0
    # Compact JSON has no indentation.
    assert "\n  " not in result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["database.password"] == "***MASKED***"


def test_cli_unmask_prints_warning_banner():
    """--unmask must fire a loud stderr banner naming the keys.

    The banner exists to deter running with --unmask inside an active
    Claude / agent conversation — the unmasked values land in stdout,
    which becomes part of tool-result / context history.
    """
    result = _run_cli(
        [
            "--unmask",
            "database.password",
            str(FIXTURES_DIR / "basic.json"),
        ]
    )
    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert "--unmask" in result.stderr
    assert "database.password" in result.stderr
    # And the unmasked value IS in stdout (that's the escape-hatch contract).
    parsed = json.loads(result.stdout)
    assert parsed["database.password"] == "s3cr3t-password"


def test_cli_read_failure_returns_4_and_empty_stdout(tmp_path):
    """Any file-read error (non-UTF-8 bytes, permissions, symlink loop,
    user passed a directory) must hit the broad ``never leak`` handler:
    exit 4, empty stdout, exception class on stderr.

    Regression for a bypass where these exceptions escaped past the
    JSONDecodeError handler and crashed with a default traceback.
    """
    # Binary garbage — UnicodeDecodeError at read time.
    broken = tmp_path / "non_utf8.json"
    broken.write_bytes(b"\xff\xfe\x00\x00")
    result = _run_cli([str(broken)])
    assert result.returncode == 4
    assert result.stdout == ""
    assert "could not read" in result.stderr.lower()


def test_cli_directory_as_path_returns_4(tmp_path):
    """Passing a directory as the config path trips IsADirectoryError."""
    result = _run_cli([str(tmp_path)])
    assert result.returncode == 4
    assert result.stdout == ""
    assert "could not read" in result.stderr.lower()


def test_cli_never_prints_raw_file_on_error(monkeypatch, scrub_module):
    """If scrub() raises mid-flight, stdout stays empty — no partial leak.

    We simulate this by monkey-patching scrub() to raise after import,
    then invoking main() in-process to verify the exit code path.
    """

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated mid-scrub failure")

    monkeypatch.setattr(scrub_module, "scrub", boom)

    from io import StringIO

    captured_stdout = StringIO()
    captured_stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", captured_stdout)
    monkeypatch.setattr(sys, "stderr", captured_stderr)

    exit_code = scrub_module.main([str(FIXTURES_DIR / "basic.json")])
    assert exit_code == 4
    assert captured_stdout.getvalue() == ""
    assert "SCRUB FAILED" in captured_stderr.getvalue()
    # The raw password literal must not appear anywhere in output.
    assert "s3cr3t-password" not in captured_stdout.getvalue()
    assert "s3cr3t-password" not in captured_stderr.getvalue()
