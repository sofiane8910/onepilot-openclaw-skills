"""Single-skill detail — wraps `openclaw skills info <name> --json`.

Returns the full `Skill` shape (matching `Skill.swift`'s decoder) plus,
when available, a `skillMdPreview` extracted from the skill's
`SKILL.md` file. The preview is read directly from the workspace's
managed-skills dir (a path OpenClaw returns in the `info` envelope) —
no extra subprocess, no GitHub fetch.

See SECURITY.md for invariants.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from skill_lib.openclaw import run_openclaw

# Cap the SKILL.md preview we send back to iOS. The detail view shows
# a scrollable preview; 16 KB is enough to give a sense of the skill
# without bloating the SSH transcript.
_PREVIEW_CAP_BYTES = 16 * 1024


def _read_skill_md_preview(location: Optional[str]) -> Optional[str]:
    """Read the first ~16 KB of `<location>/SKILL.md`.

    Tolerant: any error (path doesn't exist, isn't a dir, read fails,
    UTF-8 decode fails) returns None and we omit `skillMdPreview` from
    the envelope. We never construct a path that escapes the location
    OpenClaw gave us — `Path(location) / "SKILL.md"` plus a check that
    the resolved path stays under the parent.
    """
    if not isinstance(location, str) or not location:
        return None
    try:
        base = Path(location).resolve()
        if not base.is_dir():
            return None
        skill_md = (base / "SKILL.md").resolve()
        # Defense in depth: ensure SKILL.md actually lives under base.
        # `Path.resolve()` follows symlinks, so a malicious symlink in
        # base/SKILL.md could otherwise point at /etc/shadow.
        try:
            skill_md.relative_to(base)
        except ValueError:
            return None
        if not skill_md.is_file():
            return None
        with skill_md.open("rb") as fp:
            raw = fp.read(_PREVIEW_CAP_BYTES + 1)
    except OSError:
        return None
    truncated = len(raw) > _PREVIEW_CAP_BYTES
    chunk = raw[:_PREVIEW_CAP_BYTES]
    try:
        text = chunk.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if truncated:
        text = text.rstrip() + "\n\n…[truncated]"
    return text


def _build_detail(raw: dict[str, Any], slug: str) -> dict[str, Any]:
    """Translate `openclaw skills info` JSON to iOS InstallableSkillDetail."""
    description = ""
    summary = raw.get("description")
    if isinstance(summary, str) and summary:
        description = summary

    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        tags_raw = []
    tags = [str(t) for t in tags_raw if isinstance(t, (str, int))]

    out: dict[str, Any] = {
        "name": slug,
        "description": description,
        "source": "clawhub",
        "trustLevel": "community",
        "identifier": slug,
        "tags": tags,
    }

    # Try to surface a SKILL.md preview from the on-disk skill, if it's
    # already installed. For not-yet-installed skills (the common
    # marketplace case) `locationPath` won't exist and we just skip.
    location = raw.get("locationPath")
    if not isinstance(location, str):
        location = None
    preview = _read_skill_md_preview(location)
    if preview:
        out["skillMdPreview"] = preview

    return out


def inspect(
    plugin_version: str,
    name: str,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Return the `inspect` envelope for one ClawHub skill slug."""
    if not isinstance(name, str) or not name:
        return {
            "plugin_version": plugin_version,
            "skill": None,
            "error": "invalid_name",
        }

    result = run_openclaw(
        ["skills", "info", name, "--json"],
        profile=profile,
    )
    if not result.get("ok"):
        return {
            "plugin_version": plugin_version,
            "skill": None,
            "error": result.get("error", "unknown"),
        }

    data = result["data"]
    if data is None:
        return {"plugin_version": plugin_version, "skill": None}
    if not isinstance(data, dict):
        return {
            "plugin_version": plugin_version,
            "skill": None,
            "error": "unexpected_shape",
        }

    return {
        "plugin_version": plugin_version,
        "skill": _build_detail(data, slug=name),
    }
