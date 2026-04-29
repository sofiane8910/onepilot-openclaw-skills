"""ClawHub browse — wraps `openclaw skills search --json`.

OpenClaw's search CLI accepts `--limit` but no `--offset`/`--page`, so
we fetch one large window (capped) and paginate in-plugin. That keeps
the iOS adapter's pagination contract identical to the Hermes plugin's
`hub` mode (`page`, `total_pages`, `total`, `items`).

Translation layer (Hermes-plugin parallel):
  ClawHub field   →  iOS canonical field
  slug            →  name (slug is the install identifier; iOS uses
                     it as the display key as well — display label
                     is filled by `displayName`)
  displayName     →  (folded into `description` prefix when summary
                     is empty; otherwise we keep `summary`)
  summary         →  description
  (none)          →  source = "clawhub"
  (none)          →  trustLevel = "community"  (every ClawHub skill
                     is community by definition; OpenClaw's bundled
                     skills do not appear in `skills search`)
  (none)          →  tags = []   (search response doesn't include tags;
                     `inspect` mode resolves them lazily on row tap)

See SECURITY.md for invariants.
"""

from __future__ import annotations

from typing import Any

from skill_lib.openclaw import run_openclaw

# Cap the search window we fetch from OpenClaw in one call. We don't
# want to ask for 100 000 results just because the user typoed page
# 9999 — `_clamp_page` upstream already bounds the page index, but
# this is the secondary belt-and-braces.
_MAX_FETCH = 2000


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _translate_search_item(raw: Any) -> dict[str, Any]:
    """ClawHub search-result row → iOS InstallableSkill shape."""
    if not isinstance(raw, dict):
        return {
            "name": "",
            "description": "",
            "source": "clawhub",
            "trustLevel": "community",
            "tags": [],
        }
    slug = raw.get("slug", "")
    if not isinstance(slug, str):
        slug = ""
    summary = raw.get("summary")
    display = raw.get("displayName")
    if isinstance(summary, str) and summary:
        description = summary
    elif isinstance(display, str) and display:
        description = display
    else:
        description = ""
    return {
        "name": slug,
        "description": description,
        "source": "clawhub",
        "trustLevel": "community",
        "tags": [],
    }


def browse(
    plugin_version: str,
    page: int = 1,
    page_size: int = 100,
    query: str = "",
) -> dict[str, Any]:
    """Return one page of the ClawHub catalog, in iOS-canonical shape."""
    page = _clamp_int(page, 1, 1000, 1)
    page_size = _clamp_int(page_size, 1, 100, 100)

    if not isinstance(query, str):
        query = ""

    # Always fetch the full window — `--limit` is the only knob OpenClaw
    # exposes, and varying it per-page (e.g. limit = page * page_size)
    # makes `total_pages` shift as the user paginates, which renders as
    # "Page 1 of 2" → "Page 2 of 3" jank. Asking for `_MAX_FETCH` every
    # time pins `total_pages` to a stable number for the entire browse
    # session. ClawHub's search payload is small (a few hundred KB at
    # 2000 results) and OpenClaw caches it, so the cost is one slow
    # first call and free thereafter.
    fetch_limit = _MAX_FETCH

    argv = ["skills", "search", "--json", "--limit", str(fetch_limit)]
    if query:
        argv.append(query)

    result = run_openclaw(argv)
    if not result.get("ok"):
        return {
            "plugin_version": plugin_version,
            "items": [],
            "page": page,
            "total_pages": 1,
            "total": 0,
            "error": result.get("error", "unknown"),
        }

    data = result["data"]
    if not isinstance(data, dict):
        return {
            "plugin_version": plugin_version,
            "items": [],
            "page": page,
            "total_pages": 1,
            "total": 0,
            "error": "unexpected_shape",
        }

    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        raw_results = []

    translated = [_translate_search_item(it) for it in raw_results]
    # Drop empty-name rows so the iOS list never renders blank cards.
    translated = [it for it in translated if it["name"]]

    total = len(translated)
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    window = translated[start : start + page_size]

    return {
        "plugin_version": plugin_version,
        "items": window,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }
