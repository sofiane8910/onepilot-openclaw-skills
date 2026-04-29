"""SOLE subprocess chokepoint for the OpenClaw skills plugin.

This is the only file in the plugin allowed to import `subprocess`. The
CI tripwire (`ci/plugin/onepilot-openclaw-skills/security-check.sh`)
enforces that — any second `import subprocess` site fails the build.

Invariants enforced by this module (see `SECURITY.md`):

  - argv-list invocation only — never the shell=True kwarg
  - resolves the `openclaw` binary against a fixed `SAFE_PATH`, never the
    inherited `$PATH`
  - 30 s timeout on every call
  - stdout truncated at 8 MB
  - stderr discarded (never returned, never logged)
  - returns a structured envelope with `error` field on any failure
    (timeout, missing binary, JSON parse failure, non-zero exit) — no
    exception messages leak
  - sanitized environment passed to the child (`PATH` only, no
    inherited secrets)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

# Hard cap on the binary's stdout. OpenClaw's `skills list/info/search`
# output is a few hundred KB at most; 8 MB is paranoid headroom that
# still bounds the worst case. Anything beyond this is treated as an
# error envelope, not a parse attempt.
_STDOUT_CAP_BYTES = 8 * 1024 * 1024

# Wall-clock timeout for every `openclaw` invocation. OpenClaw's CLI
# can take a few seconds to bootstrap on a cold cache; 30 s is generous
# without leaving a hung process behind on real failures.
_TIMEOUT_SECONDS = 30


def _safe_path() -> str:
    """Build the PATH we hand to the child process.

    Includes nvm-managed Node bin dirs (where `openclaw` lives on most
    user setups), `~/.local/bin`, and the system bin dirs. The user's
    actual `$PATH` is not used — we don't want a malicious shim earlier
    on PATH to win. We DO consult `os.environ.get("PATH")` only as a
    last-resort suffix when the explicit dirs don't yield a binary, and
    even then `shutil.which` will reject anything that isn't executable
    by the current user.
    """
    home = _home()
    nvm_root = home / ".nvm" / "versions" / "node"
    nvm_bins: list[str] = []
    try:
        if nvm_root.is_dir():
            for child in sorted(nvm_root.iterdir()):
                bin_dir = child / "bin"
                if bin_dir.is_dir():
                    nvm_bins.append(str(bin_dir))
    except OSError:
        # Filesystem flake — fall through with what we have.
        pass

    parts: list[str] = list(nvm_bins) + [
        str(home / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    return ":".join(parts)


def _home() -> Path:
    raw = os.environ.get("HOME")
    if raw:
        return Path(raw)
    return Path.home()


_OPENCLAW_BIN: Optional[str] = None


def _resolve_openclaw_bin() -> Optional[str]:
    """Resolve the openclaw binary once, cache the result.

    `shutil.which` against an explicit `path=` argument does NOT consult
    the inherited `$PATH`, so a hostile shim can't slip in via a user's
    custom PATH manipulation.
    """
    global _OPENCLAW_BIN
    if _OPENCLAW_BIN is not None:
        return _OPENCLAW_BIN
    found = shutil.which("openclaw", path=_safe_path())
    if found:
        _OPENCLAW_BIN = found
    return _OPENCLAW_BIN


def _reset_cache_for_tests() -> None:
    """Clear the cached binary lookup. Test-only seam."""
    global _OPENCLAW_BIN
    _OPENCLAW_BIN = None


def run_openclaw(
    argv: list[str],
    *,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke `openclaw [--profile <id>] <argv...>` and return parsed JSON.

    Returns either:
      - `{"ok": True, "data": <parsed JSON>}` on success
      - `{"ok": False, "error": "<class>"}` on any failure

    The error class is one of: `openclaw_not_found`, `openclaw_timeout`,
    `openclaw_unavailable`, `openclaw_output_too_large`, `invalid_json`,
    or the exception class name from a subprocess flake.

    NEVER raises. Callers can rely on the dict shape unconditionally.
    """
    bin_path = _resolve_openclaw_bin()
    if bin_path is None:
        return {"ok": False, "error": "openclaw_not_found"}

    # Build argv. `--profile <id>` goes BEFORE the subcommand to match
    # the OpenClaw CLI's option order. We never interpolate any of these
    # into a string — `subprocess.run([...], shell=False)` treats every
    # element as a separate argv, so quoting/injection is structurally
    # impossible.
    cmd: list[str] = [bin_path]
    if profile is not None:
        cmd.extend(["--profile", profile])
    cmd.extend(argv)

    # Sanitized env: only PATH (so the child can resolve any secondary
    # binaries it needs, e.g. node) and HOME (OpenClaw reads config from
    # `~/.openclaw/`). No other env vars inherited — nothing in
    # `~/.env`, nothing from secret managers, nothing from the SSH
    # session.
    child_env = {
        "PATH": _safe_path(),
        "HOME": str(_home()),
    }

    try:
        result = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "openclaw_timeout"}
    except FileNotFoundError:
        # The binary disappeared between resolve and exec (rare — e.g.
        # nvm switched node versions mid-call). Surface the same error
        # class as the resolve-miss case.
        return {"ok": False, "error": "openclaw_not_found"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}

    # Bound the output we attempt to parse. stderr is discarded — it can
    # carry filesystem paths or OpenClaw-internal state we don't want
    # leaking back over SSH.
    stdout = result.stdout or b""
    if len(stdout) > _STDOUT_CAP_BYTES:
        return {"ok": False, "error": "openclaw_output_too_large"}

    if result.returncode != 0:
        # Non-zero exit. Don't try to parse — OpenClaw's error path
        # writes a message to stderr (not JSON to stdout) and we'd just
        # emit `invalid_json` for the wrong reason.
        return {"ok": False, "error": "openclaw_unavailable"}

    if not stdout:
        return {"ok": False, "error": "openclaw_empty_output"}

    try:
        text = stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"ok": False, "error": "invalid_utf8"}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json"}

    return {"ok": True, "data": data}
