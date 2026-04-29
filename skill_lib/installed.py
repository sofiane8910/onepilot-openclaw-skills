"""Installed-skill enumeration.

Wraps `openclaw skills list --json`. The CLI already returns the
canonical iOS shape (every field on `Skill` in `Skill.swift` maps
1:1), so this module is mostly a passthrough — we just stamp the
envelope with the plugin version, normalize a few optional fields
that OpenClaw may omit, and surface a stable `error` envelope on
failure paths.

See SECURITY.md for invariants.
"""

from __future__ import annotations

from typing import Any, Optional

from skill_lib.openclaw import run_openclaw


def _normalize_skill(raw: Any) -> Optional[dict[str, Any]]:
    """Best-effort cleanup of one skill record.

    Drops obviously-malformed entries (no `name`) instead of letting them
    poison the envelope. iOS's `Skill` decoder is strict on `name`,
    `description`, `source`, `bundled`, `eligible`, `disabled`,
    `blockedByAllowlist`, and `missing` — we make sure those exist with
    safe defaults so an OpenClaw upstream omission doesn't take out the
    entire list.
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None

    out: dict[str, Any] = dict(raw)
    out["name"] = name
    out.setdefault("description", "")
    out.setdefault("source", "")
    out.setdefault("bundled", False)
    out.setdefault("eligible", False)
    out.setdefault("disabled", False)
    out.setdefault("blockedByAllowlist", False)
    if not isinstance(out.get("missing"), dict):
        out["missing"] = {
            "bins": [],
            "anyBins": [],
            "env": [],
            "config": [],
            "os": [],
        }

    # `registrySource` keeps Hermes/OpenClaw envelopes symmetric for the
    # iOS decoder. OpenClaw doesn't natively use the field name, but we
    # can derive it from the existing `source` / `slug` data so the iOS
    # "Registry" filter dropdown works the same way for both frameworks.
    if "registrySource" not in out:
        if isinstance(out.get("slug"), str) and out.get("slug"):
            # Skill came from ClawHub → the registry is "clawhub".
            out["registrySource"] = "clawhub"
        elif out.get("bundled"):
            out["registrySource"] = "bundled"
        else:
            out["registrySource"] = None

    return out


def collect_installed(
    plugin_version: str,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Return the full `installed` envelope for the iOS app.

    Emits the same shape the Hermes plugin's `installed` mode does:
        {plugin_version, skills: [...], count}
    plus passes through OpenClaw's `workspaceDir` and `managedSkillsDir`
    so the iOS detail view can show users where their skills live.

    Errors collapse to `{plugin_version, skills: [], count: 0,
    error: "<class>"}` — never raises.
    """
    result = run_openclaw(["skills", "list", "--json"], profile=profile)
    if not result.get("ok"):
        return {
            "plugin_version": plugin_version,
            "skills": [],
            "count": 0,
            "error": result.get("error", "unknown"),
        }

    data = result["data"]
    if not isinstance(data, dict):
        return {
            "plugin_version": plugin_version,
            "skills": [],
            "count": 0,
            "error": "unexpected_shape",
        }

    raw_skills = data.get("skills", [])
    if not isinstance(raw_skills, list):
        raw_skills = []

    cleaned: list[dict[str, Any]] = []
    for raw in raw_skills:
        norm = _normalize_skill(raw)
        if norm is not None:
            cleaned.append(norm)

    envelope: dict[str, Any] = {
        "plugin_version": plugin_version,
        "skills": cleaned,
        "count": len(cleaned),
    }
    if isinstance(data.get("workspaceDir"), str):
        envelope["workspaceDir"] = data["workspaceDir"]
    if isinstance(data.get("managedSkillsDir"), str):
        envelope["managedSkillsDir"] = data["managedSkillsDir"]
    return envelope
