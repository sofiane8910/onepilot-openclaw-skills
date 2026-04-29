from __future__ import annotations

from typing import Any

import pytest

from skill_lib import installed as installed_mod


def _stub_run(monkeypatch, payload: dict[str, Any]):
    monkeypatch.setattr(
        installed_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": payload},
    )


def _stub_run_failure(monkeypatch, error: str):
    monkeypatch.setattr(
        installed_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": error},
    )


def test_passthrough_with_canonical_skill(monkeypatch):
    payload = {
        "workspaceDir": "/Users/u/work",
        "managedSkillsDir": "/Users/u/work/.managed",
        "skills": [
            {
                "name": "calendar",
                "description": "CalDAV helpers",
                "source": "clawhub",
                "bundled": False,
                "eligible": True,
                "disabled": False,
                "blockedByAllowlist": False,
                "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
                "slug": "calendar",
                "version": "1.0.0",
            }
        ],
    }
    _stub_run(monkeypatch, payload)
    out = installed_mod.collect_installed(plugin_version="0.1.0")

    assert out["plugin_version"] == "0.1.0"
    assert out["count"] == 1
    assert out["workspaceDir"] == "/Users/u/work"
    assert out["managedSkillsDir"] == "/Users/u/work/.managed"

    skill = out["skills"][0]
    assert skill["name"] == "calendar"
    assert skill["registrySource"] == "clawhub"  # derived from slug


def test_bundled_skill_gets_bundled_registry_source(monkeypatch):
    payload = {
        "skills": [
            {
                "name": "core-thing",
                "description": "Built-in",
                "source": "bundled",
                "bundled": True,
                "eligible": True,
                "disabled": False,
                "blockedByAllowlist": False,
                "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
            }
        ]
    }
    _stub_run(monkeypatch, payload)
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["skills"][0]["registrySource"] == "bundled"


def test_no_slug_no_bundled_yields_nil_registry(monkeypatch):
    payload = {
        "skills": [
            {
                "name": "manual-drop",
                "description": "Hand-placed",
                "source": "manual",
                "bundled": False,
                "eligible": True,
                "disabled": False,
                "blockedByAllowlist": False,
                "missing": {"bins": [], "anyBins": [], "env": [], "config": [], "os": []},
            }
        ]
    }
    _stub_run(monkeypatch, payload)
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["skills"][0]["registrySource"] is None


def test_normalize_fills_missing_required_fields(monkeypatch):
    payload = {"skills": [{"name": "sparse"}]}
    _stub_run(monkeypatch, payload)
    out = installed_mod.collect_installed(plugin_version="0.1.0")

    skill = out["skills"][0]
    assert skill["description"] == ""
    assert skill["source"] == ""
    assert skill["bundled"] is False
    assert skill["eligible"] is False
    assert skill["disabled"] is False
    assert skill["blockedByAllowlist"] is False
    assert skill["missing"] == {"bins": [], "anyBins": [], "env": [], "config": [], "os": []}


def test_skills_without_name_are_dropped(monkeypatch):
    payload = {"skills": [{"description": "no name"}, {"name": "ok"}, "not-a-dict"]}
    _stub_run(monkeypatch, payload)
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["count"] == 1
    assert out["skills"][0]["name"] == "ok"


def test_run_failure_returns_error_envelope(monkeypatch):
    _stub_run_failure(monkeypatch, "openclaw_not_found")
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["plugin_version"] == "0.1.0"
    assert out["skills"] == []
    assert out["count"] == 0
    assert out["error"] == "openclaw_not_found"


def test_unexpected_shape_returns_error_envelope(monkeypatch):
    monkeypatch.setattr(
        installed_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": "not a dict"},
    )
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["error"] == "unexpected_shape"


def test_envelope_always_carries_plugin_version(monkeypatch):
    _stub_run_failure(monkeypatch, "openclaw_timeout")
    out = installed_mod.collect_installed(plugin_version="0.1.0")
    assert out["plugin_version"] == "0.1.0"


def test_profile_passed_through_to_run_openclaw(monkeypatch):
    seen = {}

    def fake_run(argv, profile=None):
        seen["argv"] = argv
        seen["profile"] = profile
        return {"ok": True, "data": {"skills": []}}

    monkeypatch.setattr(installed_mod, "run_openclaw", fake_run)
    installed_mod.collect_installed(plugin_version="0.1.0", profile="coder")
    assert seen["profile"] == "coder"
    assert seen["argv"] == ["skills", "list", "--json"]
