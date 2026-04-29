"""Safety asserts for the SOLE subprocess chokepoint.

These tests are the runtime counterpart to the CI tripwire:
they prove the wrapper enforces argv-list invocation, fixed PATH,
timeout, and sanitized environment — properties grep can't fully
verify on its own.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from skill_lib import openclaw as oc


@pytest.fixture(autouse=True)
def reset_openclaw_cache():
    oc._reset_cache_for_tests()
    yield
    oc._reset_cache_for_tests()


def _capture_run(monkeypatch):
    """Patch subprocess.run; capture every call's kwargs."""
    captured: list[dict] = []

    def fake_run(cmd, **kwargs):
        captured.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b'{"ok":true}', stderr=b""
        )

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    return captured


def test_run_uses_argv_list_never_shell_true(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")
    captured = _capture_run(monkeypatch)

    oc.run_openclaw(["skills", "list", "--json"])

    assert len(captured) == 1
    call = captured[0]
    # `cmd` MUST be a list, not a string.
    assert isinstance(call["cmd"], list)
    assert call["cmd"][0] == "/fake/openclaw"
    # `shell=True` MUST never appear.
    assert call.get("shell") is False
    # Timeout MUST be set.
    assert call.get("timeout") == 30
    # `check` MUST be False (we handle exit codes ourselves).
    assert call.get("check") is False
    # Environment MUST be a sanitized dict, not None (which would
    # inherit os.environ).
    assert isinstance(call.get("env"), dict)
    # The sanitized env exposes ONLY PATH and HOME.
    assert set(call["env"].keys()) == {"PATH", "HOME"}


def test_profile_argv_position(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")
    captured = _capture_run(monkeypatch)

    oc.run_openclaw(["skills", "list", "--json"], profile="coder")

    cmd = captured[0]["cmd"]
    assert cmd == ["/fake/openclaw", "--profile", "coder", "skills", "list", "--json"]


def test_missing_binary_returns_error_envelope_without_invoking_subprocess(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: None)
    captured = _capture_run(monkeypatch)

    out = oc.run_openclaw(["skills", "list", "--json"])

    assert out == {"ok": False, "error": "openclaw_not_found"}
    # subprocess.run MUST not be reached when the binary is unresolved.
    assert captured == []


def test_timeout_is_caught_and_classified(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    out = oc.run_openclaw(["skills", "list", "--json"])
    assert out == {"ok": False, "error": "openclaw_timeout"}


def test_oversized_output_rejected(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")
    huge = b"a" * (oc._STDOUT_CAP_BYTES + 1)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=huge, stderr=b"")

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    out = oc.run_openclaw(["skills", "list", "--json"])
    assert out["ok"] is False
    assert out["error"] == "openclaw_output_too_large"


def test_nonzero_exit_classified_as_unavailable(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")

    def fake_run(cmd, **kwargs):
        # stderr has the error message — and it MUST NOT be returned.
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout=b"",
            stderr=b"openclaw: error: secret/path/leaked\n",
        )

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    out = oc.run_openclaw(["skills", "list", "--json"])

    assert out == {"ok": False, "error": "openclaw_unavailable"}
    assert "secret/path/leaked" not in str(out)


def test_invalid_json_classified(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"not json", stderr=b"")

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    out = oc.run_openclaw(["skills", "list", "--json"])
    assert out == {"ok": False, "error": "invalid_json"}


def test_unexpected_subprocess_exception_does_not_leak_message(monkeypatch):
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")

    def fake_run(cmd, **kwargs):
        raise PermissionError("/etc/shadow leaked")

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    out = oc.run_openclaw(["skills", "list", "--json"])
    assert out["ok"] is False
    assert out["error"] == "PermissionError"
    assert "/etc/shadow" not in str(out)


def test_safe_path_does_not_inherit_user_path(monkeypatch):
    # Even if the user's $PATH has a malicious shim earlier than nvm,
    # the SAFE_PATH we hand to subprocess.run never includes it.
    monkeypatch.setenv("PATH", "/tmp/malicious:/usr/bin")
    safe = oc._safe_path()
    assert "/tmp/malicious" not in safe


def test_run_openclaw_never_raises_on_internal_failure(monkeypatch):
    """No matter what subprocess.run does, run_openclaw returns a dict."""
    monkeypatch.setattr(oc, "_resolve_openclaw_bin", lambda: "/fake/openclaw")

    for boom in [
        OSError("disk full"),
        RuntimeError("???"),
        ValueError("nope"),
    ]:
        def fake_run(cmd, _e=boom, **kwargs):
            raise _e

        monkeypatch.setattr(oc.subprocess, "run", fake_run)
        out = oc.run_openclaw(["skills", "list", "--json"])
        assert isinstance(out, dict)
        assert out["ok"] is False
        assert "error" in out
