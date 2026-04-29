# Security model — `onepilot-openclaw-skills`

## Why this plugin's threat model differs from `onepilot-skills` (Hermes)

The Hermes plugin (`onepilotapp/plugins/hermes/onepilot-skills`) is **subprocess-free** —
all of Hermes' skill state lives in files under `~/.hermes/`, so the plugin
just walks the filesystem and merges YAML/JSON.

OpenClaw's skill state lives behind a CLI (`openclaw skills list/info/search
--json`). Reimplementing OpenClaw's resolver in Python would drift from the
upstream behavior, so this plugin **must** shell out to the `openclaw`
binary. That delta is the entire reason this document exists separately
from the Hermes plugin's `SECURITY.md`.

The rule is: **`skill_lib/openclaw.py` is the only file allowed to call
`subprocess`, and inside that file only one shape — `subprocess.run` with
an argv list, `shell=False`, an explicit timeout, and a sanitized
environment — is permitted.** Everything else mirrors the Hermes plugin.

## What this plugin defends against

| Concern | Mitigation |
|---|---|
| Backend / Supabase access from the plugin | Zero networking imports (`requests`, `httpx`, `urllib`, `socket`) — even if compromised the plugin cannot reach `*.supabase.co` or any Onepilot-controlled endpoint. The CI tripwire blocks reintroduction. |
| Secret / credential exfiltration | `os.environ` is read **only** for `HOME` (resolved once via `Path.home()` or `os.environ.get("HOME")`). No reading of `~/.env`, `.netrc`, `~/.aws/credentials`. No file writes — an attacker cannot stage a payload to exfiltrate later. |
| Command injection from the iOS caller | Entry point uses `argparse` with `choices=[...]` for `--mode` and a strict regex (`^[A-Za-z0-9_./\-]{1,200}$`) for `--name`. `--profile` is matched by `^[A-Za-z0-9_\-]{1,64}$` (tighter — profile ids never contain `/` or `.`). `--page`, `--page-size`, `--limit` get integer clamps. No `shell=True`. No string concatenation into shell commands — argv lists only. |
| Path traversal via `--name` / `--profile` | Regex above forbids leading `/` and `..` segments. Validated **before** subprocess invocation, so a malformed input never reaches the `openclaw` binary at all. |
| Runaway subprocess (`openclaw` hangs, network freeze inside it) | 30 s timeout on every `subprocess.run`. stdout truncated at 8 MB. stderr discarded. On `TimeoutExpired` we emit `{"error": "openclaw_timeout"}` and exit 0 — no process leaks (Python's `subprocess` SIGKILLs on timeout). |
| Untrusted `openclaw` binary on `$PATH` | We resolve the binary via `shutil.which("openclaw", path=SAFE_PATH)` with a **fixed** PATH (`~/.nvm/versions/node/*/bin:~/.local/bin:/usr/local/bin:/usr/bin`). The user's `$PATH` is not inherited. If `openclaw` isn't found in any of those locations we emit `{"error": "openclaw_not_found"}`. |
| Output injection back into iOS | Output is `json.dump`-emitted (RFC-compliant escaping). SwiftUI `Text` renders plain text. |
| Logging leaks | No `logging`. Exception envelopes contain only the exception **class name**, never the message — exception messages can carry filesystem paths or OpenClaw-internal state we don't want trickling out over SSH transcripts. The same rule applies to subprocess stderr: it is discarded, never echoed. |

## What this plugin does NOT defend against

| Out of scope | Why |
|---|---|
| User pushing malicious code to the Onepilot GitHub org | Repo access control is the boundary. We use signed tags and branch protection. |
| A compromised OpenClaw install on the user's host | If `openclaw` itself is compromised, the attacker has all the access the plugin would. We're not the trust boundary. |
| The user explicitly running our scripts with elevated privileges | Plugin runs as the user. `sudo python3 …` would obviously elevate; not our problem. |
| MITM on the user's SSH session | SSH session encryption is the boundary, not us. |

## Hard invariants

These are **enforced by code review and CI** (`ci/plugin/onepilot-openclaw-skills/security-check.sh`).
A single hit fails the build:

- 🚫 `import requests`
- 🚫 `import httpx`
- 🚫 `import urllib`
- 🚫 `import socket`
- 🚫 `import subprocess` **except** in `skill_lib/openclaw.py`
- 🚫 `os.system`
- 🚫 `shell=True` (anywhere, including `openclaw.py`)
- 🚫 `Popen` (use `subprocess.run` only)
- 🚫 `subprocess.call`, `subprocess.check_output` — not flexible enough to enforce timeout/argv-list constraints by inspection
- 🚫 `eval(`, `exec(`, `compile(` (word-boundary; `re.compile` is fine)
- 🚫 `open(..., "w"|"a"|"x")` — file writes
- 🚫 `os.environ[` — bracket access (we only allow `os.environ.get("HOME")` and `os.environ.get("PATH")` reads, the latter only as a fallback alongside `SAFE_PATH`)
- 🚫 `str(e)` inside `json.dump` — exception messages must never reach stdout
- ✅ Every script entry calls `argparse` with `choices=[...]` for `--mode`
- ✅ At least one `subprocess.run([` (argv-list shape) in `skill_lib/openclaw.py`
- ✅ Every catch block emits a sanitized envelope (`type(e).__name__`),
       never `str(e)` or the traceback

## Scope of changes that require security re-review

If you intend to add any of these, the change needs an explicit security
re-review (and probably a redesign):

- Any networking import or HTTP call from inside the plugin.
- Any filesystem write outside the plugin install dir.
- Any second `subprocess.run` site outside `skill_lib/openclaw.py`, or any
  use of `shell=True`, `Popen`, `subprocess.call`, `subprocess.check_output`.
- Any `os.environ` access beyond `HOME` / `PATH`.
- Any change that makes input validation weaker (loosening the `--name` /
  `--profile` regex, expanding `--mode` choices to dynamic values).
- Any change that emits `str(e)` or tracebacks to stdout, or echoes
  subprocess stderr to stdout.

## Reporting

Found a security issue? Email security@onepilotapp.com. Please don't open
public GitHub issues for vulnerabilities.
