from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import skills_dump
from skill_lib import inspect as inspect_mod


def _run(argv, monkeypatch) -> dict:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    skills_dump.main(argv)
    return json.loads(buf.getvalue().strip())


# --- Argparse-layer validation (entry script) -------------------------------


def test_inspect_rejects_invalid_name(monkeypatch):
    out = _run(["--mode", "inspect", "--name", "../etc/passwd"], monkeypatch)
    assert out["error"] == "invalid_name"
    assert out["skill"] is None


def test_inspect_rejects_command_chars(monkeypatch):
    out = _run(["--mode", "inspect", "--name", "writer; rm -rf /"], monkeypatch)
    assert out["error"] == "invalid_name"


def test_inspect_rejects_too_long(monkeypatch):
    out = _run(["--mode", "inspect", "--name", "a" * 201], monkeypatch)
    assert out["error"] == "invalid_name"


def test_inspect_accepts_valid_short_name(monkeypatch):
    # Stub run_openclaw so the openclaw binary isn't required for this
    # validation-layer test.
    monkeypatch.setattr(
        "skill_lib.inspect.run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": "openclaw_not_found"},
    )
    out = _run(["--mode", "inspect", "--name", "writer"], monkeypatch)
    assert out["skill"] is None
    assert out["error"] == "openclaw_not_found"


def test_inspect_accepts_valid_slash_path(monkeypatch):
    monkeypatch.setattr(
        "skill_lib.inspect.run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": "openclaw_not_found"},
    )
    out = _run(["--mode", "inspect", "--name", "anthropics/skills/skill-creator"], monkeypatch)
    assert out["skill"] is None
    assert out["error"] == "openclaw_not_found"


def test_inspect_accepts_name_with_spaces(monkeypatch):
    """Plugin >=0.1.2 accepts skill names with spaces (e.g. display
    names like 'MD5 Tool'). Earlier regex rejected them as invalid."""
    monkeypatch.setattr(
        "skill_lib.inspect.run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": "openclaw_not_found"},
    )
    out = _run(["--mode", "inspect", "--name", "MD5 Tool"], monkeypatch)
    # Name passes validation; subprocess wrapper then reports
    # openclaw_not_found because no binary in test env.
    assert out["error"] == "openclaw_not_found"


def test_inspect_still_rejects_shell_metacharacters(monkeypatch):
    """Relaxed regex must still keep dangerous chars out — even though
    subprocess invocation is argv-list (so spaces are safe), we don't
    want to widen the contract beyond what real names need."""
    for bad in [
        "name|cat /etc/passwd",
        "name>/tmp/x",
        "name`whoami`",
        "name$(whoami)",
        "name\\nwith newline",
    ]:
        out = _run(["--mode", "inspect", "--name", bad], monkeypatch)
        assert out["error"] == "invalid_name", f"accepted dangerous: {bad!r}"


def test_unknown_mode_rejected_by_argparse(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        _run(["--mode", "wat"], monkeypatch)
    assert excinfo.value.code == 2


def test_envelope_always_includes_plugin_version(monkeypatch):
    out = _run(["--mode", "inspect", "--name", ""], monkeypatch)
    assert out["plugin_version"] == "0.1.2"

    monkeypatch.setattr(
        "skill_lib.hub.run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": {"results": []}},
    )
    out = _run(["--mode", "hub"], monkeypatch)
    assert out["plugin_version"] == "0.1.2"


def test_invalid_profile_treated_as_none(monkeypatch):
    """A malformed profile id never reaches run_openclaw."""
    seen = {}

    def fake_run(argv, profile=None):
        seen["profile"] = profile
        return {"ok": True, "data": {"skills": []}}

    monkeypatch.setattr("skill_lib.installed.run_openclaw", fake_run)
    _run(["--mode", "installed", "--profile", "../etc"], monkeypatch)
    # Validator rejected the profile → run_openclaw called with None.
    assert seen["profile"] is None


def test_valid_profile_passes_through(monkeypatch):
    seen = {}

    def fake_run(argv, profile=None):
        seen["profile"] = profile
        return {"ok": True, "data": {"skills": []}}

    monkeypatch.setattr("skill_lib.installed.run_openclaw", fake_run)
    _run(["--mode", "installed", "--profile", "coder"], monkeypatch)
    assert seen["profile"] == "coder"


# --- inspect.py module-level tests ------------------------------------------


def test_inspect_returns_translated_detail(monkeypatch):
    monkeypatch.setattr(
        inspect_mod,
        "run_openclaw",
        lambda argv, profile=None: {
            "ok": True,
            "data": {"name": "calendar", "description": "CalDAV", "tags": ["agent"]},
        },
    )
    out = inspect_mod.inspect(plugin_version="0.1.0", name="calendar")
    skill = out["skill"]
    assert skill["name"] == "calendar"
    assert skill["description"] == "CalDAV"
    assert skill["source"] == "clawhub"
    assert skill["trustLevel"] == "community"
    assert skill["identifier"] == "calendar"
    assert skill["tags"] == ["agent"]
    assert "skillMdPreview" not in skill  # no locationPath in the input


def test_inspect_reads_skill_md_preview_when_location_present(tmp_path, monkeypatch):
    skill_dir = tmp_path / "calendar"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Calendar\n\nUse this skill to manage CalDAV.")

    monkeypatch.setattr(
        inspect_mod,
        "run_openclaw",
        lambda argv, profile=None: {
            "ok": True,
            "data": {"name": "calendar", "description": "CalDAV", "locationPath": str(skill_dir)},
        },
    )
    out = inspect_mod.inspect(plugin_version="0.1.0", name="calendar")
    assert "skillMdPreview" in out["skill"]
    assert "Calendar" in out["skill"]["skillMdPreview"]


def test_inspect_rejects_symlinked_skill_md_escape(tmp_path, monkeypatch):
    """A symlinked SKILL.md pointing outside the skill dir must be refused."""
    target = tmp_path / "secret.txt"
    target.write_text("secret data")

    skill_dir = tmp_path / "evil"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").symlink_to(target)

    monkeypatch.setattr(
        inspect_mod,
        "run_openclaw",
        lambda argv, profile=None: {
            "ok": True,
            "data": {"name": "evil", "locationPath": str(skill_dir)},
        },
    )
    out = inspect_mod.inspect(plugin_version="0.1.0", name="evil")
    # The symlink resolves outside skill_dir → preview is omitted.
    assert "skillMdPreview" not in out["skill"]


def test_inspect_handles_run_failure(monkeypatch):
    monkeypatch.setattr(
        inspect_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": "openclaw_timeout"},
    )
    out = inspect_mod.inspect(plugin_version="0.1.0", name="anything")
    assert out["skill"] is None
    assert out["error"] == "openclaw_timeout"


def test_inspect_handles_null_data(monkeypatch):
    """OpenClaw returns `null` for an unknown skill."""
    monkeypatch.setattr(
        inspect_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": None},
    )
    out = inspect_mod.inspect(plugin_version="0.1.0", name="ghost")
    assert out["skill"] is None
    assert "error" not in out
