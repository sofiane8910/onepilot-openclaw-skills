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
    # Zero-padded slugs so alphabetical sort matches numeric sort.
    results = [
        {"slug": f"skill-{i:02d}", "displayName": f"S{i}", "summary": f"sum {i}"}
        for i in range(25)
    ]
    _stub_run(monkeypatch, results)

    # Pass a query so the plugin makes a single call (no vowel fan-out).
    page1 = hub_mod.browse(plugin_version="0.1.0", page=1, page_size=10, query="skill")
    page3 = hub_mod.browse(plugin_version="0.1.0", page=3, page_size=10, query="skill")

    assert page1["total"] == 25
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 10
    assert page1["items"][0]["name"] == "skill-00"

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


def test_empty_query_fans_out_vowel_probes(monkeypatch):
    """Empty query must run multiple search calls with single-vowel
    probes, since OpenClaw's `skills search` (which calls ClawHub's
    /api/v1/search with q=`*`) returns 0 hits when no query is given."""
    calls: list[list[str]] = []

    def fake_run(argv, profile=None):
        calls.append(list(argv))
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(hub_mod, "run_openclaw", fake_run)
    hub_mod.browse(plugin_version="0.1.0", query="")

    assert len(calls) == len(hub_mod._BROWSE_PROBES)
    probes = {call[-1] for call in calls}
    assert probes == set(hub_mod._BROWSE_PROBES)
    # Each call still has the --limit argv shape.
    for call in calls:
        assert call[:5] == ["skills", "search", "--json", "--limit", str(hub_mod._MAX_FETCH)]


def test_empty_query_dedupes_across_probes(monkeypatch):
    """Same skill appearing in multiple probe results must surface once."""
    by_probe = {
        "a": [{"slug": "calendar", "displayName": "Calendar"}],
        "e": [{"slug": "calendar", "displayName": "Calendar"}],  # duplicate
        "i": [{"slug": "writer", "displayName": "Writer"}],
        "o": [{"slug": "calendar", "displayName": "Calendar"}],  # duplicate
        "u": [{"slug": "researcher", "displayName": "Researcher"}],
    }

    def fake_run(argv, profile=None):
        probe = argv[-1]
        return {"ok": True, "data": {"results": by_probe.get(probe, [])}}

    monkeypatch.setattr(hub_mod, "run_openclaw", fake_run)
    out = hub_mod.browse(plugin_version="0.1.0", query="")

    names = {item["name"] for item in out["items"]}
    assert names == {"calendar", "writer", "researcher"}
    assert out["total"] == 3
    # Alphabetical ordering by slug.
    assert [it["name"] for it in out["items"]] == ["calendar", "researcher", "writer"]


def test_query_uses_single_call(monkeypatch):
    """Non-empty query path must make exactly one openclaw call —
    no vowel fan-out when the user already typed something."""
    calls: list[list[str]] = []

    def fake_run(argv, profile=None):
        calls.append(list(argv))
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(hub_mod, "run_openclaw", fake_run)
    hub_mod.browse(plugin_version="0.1.0", query="calendar")
    assert len(calls) == 1
    assert calls[0][-1] == "calendar"


def test_unexpected_shape_returns_error_envelope(monkeypatch):
    monkeypatch.setattr(
        hub_mod,
        "run_openclaw",
        lambda argv, profile=None: {"ok": True, "data": "not a dict"},
    )
    out = hub_mod.browse(plugin_version="0.1.0")
    assert out["error"] == "unexpected_shape"
