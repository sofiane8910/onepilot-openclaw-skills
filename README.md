# onepilot-openclaw-skills (OpenClaw plugin)

Read-only skill discovery surface for the [Onepilot](https://onepilotapp.com)
iOS app on OpenClaw hosts. Wraps `openclaw skills list/info/search --json`
behind a stable, version-stamped JSON envelope so the iOS app can move at
its own pace independent of OpenClaw's CLI shape.

Sibling of `onepilot-skills` (the Hermes-side plugin). Same envelope shape,
same install/upgrade UX in the app, same security invariants — the only
delta is that this plugin shells out to `openclaw` (it has to, since
OpenClaw's skill state isn't in plain files), guarded by a single
chokepoint in `skill_lib/openclaw.py`. See `SECURITY.md` for the full
threat model.

## Why a separate plugin?

- **Independent versioning** — a skill-fetch shape change ships without
  redeploying any other onepilot plugin.
- **Smaller blast radius** — a bug here can leave the marketplace empty;
  it cannot touch the chat channel or any OpenClaw runtime path.
- **Faster iteration** — OpenClaw upstream API drift in `openclaw skills
  …` affects only this plugin; a one-line patch + `git pull` on the host
  is enough, no iOS App Store cycle.

## Install

```sh
git clone https://github.com/sofiane8910/onepilot-openclaw-skills ~/.onepilot/openclaw-skills
```

The Onepilot iOS app probes for the script and offers a one-tap install
when it isn't present. Updates: `cd ~/.onepilot/openclaw-skills && git
pull --ff-only`.

## Usage

```
python3 ~/.onepilot/openclaw-skills/skills_dump.py --mode <mode> [args]
```

Modes:

| Mode | Args | Returns |
|---|---|---|
| `installed` | `--profile <id>` | `{plugin_version, skills:[…], count}` |
| `hub` | `[--page N] [--page-size N] [--query Q]` | `{plugin_version, items, page, total_pages, total}` |
| `inspect` | `--name <slug> --profile <id>` | `{plugin_version, skill: {…} \| null}` |

Every envelope carries `plugin_version` so the consumer can detect drift.
Errors are returned as `{plugin_version, error: "<exception-class>"}` —
never as tracebacks. See `SECURITY.md` for the full threat model.

## Security

This plugin runs entirely offline from Python's perspective. The one
subprocess it spawns is the `openclaw` binary, resolved via a fixed
`SAFE_PATH` (no `$PATH` inheritance), invoked with `shell=False`, an
argv list, and a 30 s timeout. It writes zero files. It reads only
`HOME` (and `PATH` as a hint into `SAFE_PATH`).

`ci/plugin/onepilot-openclaw-skills/security-check.sh` (in the Onepilot
repo) greps the source tree on every CI run and fails on any of:
`import requests/httpx/urllib/socket`, second-site `import subprocess`,
`os.system`, `shell=True`, `Popen`, `subprocess.call`,
`subprocess.check_output`, or any non-`HOME`/`PATH` `os.environ[...]`
access. See `SECURITY.md` for the full invariant list.

## Development

```
cd onepilotapp/plugins/openclaw/onepilot-openclaw-skills
pytest tests/
```

## License

MIT.
