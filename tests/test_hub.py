from __future__ import annotations

import pytest

from skill_lib import hub as hub_mod


def _stub_run(monkeypatch, results):
    monkeypatch.setattr(
        hub_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": {"results": results}},
    )


def _stub_run_failure(monkeypatch, error: str):
    monkeypatch.setattr(
        hub_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": False, "error": error},
    )


def test_translates_clawhub_search_to_ios_canonical(monkeypatch):
    _stub_run(
        monkeypatch,
        [
            {"slug": "calendar", "displayName": "Calendar", "summary": "CalDAV", "version": "1.0.0"},
            {"slug": "writer", "displayName": "Writer"},  # no summary
        ],
    )

    out = hub_mod.browse(plugin_version="0.1.0", page=1, page_size=10)
    assert out["plugin_version"] == "0.1.0"
    assert out["total"] == 2
    assert out["page"] == 1
    assert len(out["items"]) == 2

    item0 = out["items"][0]
    assert item0["name"] == "calendar"
    assert item0["description"] == "CalDAV"
    assert item0["source"] == "clawhub"
    assert item0["trustLevel"] == "community"
    assert item0["tags"] == []

    # When summary is missing, fall back to displayName.
    assert out["items"][1]["description"] == "Writer"


def test_pagination_in_plugin(monkeypatch):
    results = [{"slug": f"skill-{i}", "displayName": f"S{i}", "summary": f"sum {i}"} for i in range(25)]
    _stub_run(monkeypatch, results)

    page1 = hub_mod.browse(plugin_version="0.1.0", page=1, page_size=10)
    page3 = hub_mod.browse(plugin_version="0.1.0", page=3, page_size=10)

    assert page1["total"] == 25
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 10
    assert page1["items"][0]["name"] == "skill-0"

    assert page3["page"] == 3
    assert len(page3["items"]) == 5  # tail
    assert page3["items"][0]["name"] == "skill-20"


def test_clamps_pagination_inputs(monkeypatch):
    _stub_run(monkeypatch, [])
    out = hub_mod.browse(plugin_version="0.1.0", page=99999, page_size=99999)
    assert out["page"] == 1  # clamped down to total_pages=1 when empty
    assert out["total_pages"] == 1


def test_drops_rows_with_empty_slug(monkeypatch):
    _stub_run(
        monkeypatch,
        [
            {"slug": "", "displayName": "Bad"},
            {"displayName": "Also bad"},  # no slug
            {"slug": "ok"},
        ],
    )
    out = hub_mod.browse(plugin_version="0.1.0")
    assert out["total"] == 1
    assert out["items"][0]["name"] == "ok"


def test_handles_malformed_items(monkeypatch):
    _stub_run(monkeypatch, [None, "not a dict", {"slug": "ok"}])
    out = hub_mod.browse(plugin_version="0.1.0")
    # Two empty-slug rows are dropped; only "ok" survives.
    assert out["total"] == 1
    assert out["items"][0]["name"] == "ok"


def test_run_failure_returns_error_envelope(monkeypatch):
    _stub_run_failure(monkeypatch, "openclaw_not_found")
    out = hub_mod.browse(plugin_version="0.1.0")
    assert out["plugin_version"] == "0.1.0"
    assert out["items"] == []
    assert out["error"] == "openclaw_not_found"


def test_query_arg_is_appended_when_nonempty(monkeypatch):
    seen: dict = {}

    def fake_run(argv, profile=None):
        seen["argv"] = argv
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(hub_mod, "run_openclaw", fake_run)
    hub_mod.browse(plugin_version="0.1.0", query="calendar")
    assert seen["argv"][:4] == ["skills", "search", "--json", "--limit"]
    # Query is the trailing positional.
    assert seen["argv"][-1] == "calendar"


def test_query_omitted_when_empty(monkeypatch):
    seen: dict = {}

    def fake_run(argv, profile=None):
        seen["argv"] = argv
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(hub_mod, "run_openclaw", fake_run)
    hub_mod.browse(plugin_version="0.1.0", query="")
    # No positional after `--limit <n>`.
    assert seen["argv"][-2] == "--limit"


def test_unexpected_shape_returns_error_envelope(monkeypatch):
    monkeypatch.setattr(
        hub_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": "not a dict"},
    )
    out = hub_mod.browse(plugin_version="0.1.0")
    assert out["error"] == "unexpected_shape"
