# Decision log

Every chock hook writes one line per decision to a local JSONL file. Nothing leaves the machine:
no network, no telemetry. A file's contents are never logged.

## Where it is written

| Route | Installed by | File |
| :--- | :--- | :--- |
| sync | `chock sync` (hooks run `<repo>/.chock/bin/<agent>.py`) | `<repo>/.chock/log/gate-events.jsonl` |
| plugin | `chock install` (hooks run inside the plugin package) | `~/.chock/log/<agent>/events.jsonl` |

Every chock plugin in a client, the merged bundle and single catalog plugins alike, appends to that
client's one file; each line names its `plugin`. A line is written in one append, so hooks running at
once never interleave. One rotated file is kept beside each (`gate-events.1.jsonl`, `events.1.jsonl`);
rotation takes a lock (fcntl, or msvcrt on Windows), and a writer that finds it busy skips rotating. The sync file is
the same file earlier versions wrote, so older readers keep working.

## Levels

| Level | Writes |
| :--- | :--- |
| `off` | nothing |
| `info` (default) | one line each time a policy fires: block, ask, warn, a guard fault, or an override or rollout level that let a finding through |
| `debug` | every hook call, allows included, plus a `trace`: wire event, tool, matched rule (or "no rule matched"), the guard's exit code, per-stage timings, and the command or path cut to 200 characters with every value the scan-secrets policy would block replaced by `[redacted]` |

Each line carries `ts`, `route`, `level`, `agent`, `client` (when the payload names one), `event`,
`policy_id`, `surface`, `verdict`, `reason`, `duration_ms`, `can_ask`, `chock_version`, and on the
plugin route `plugin` and `plugin_version`. On the sync route a compiled gate's line is written by `gate.py`
and keeps its own fields (`kind`, `match_count`, `matches`, `rules`).

## Settings (a person's, only)

```json
{"level": "debug", "max_bytes": 4194304}
```

One file per scope, both optional, each named `chock-log.json` inside a `.chock` folder:

1. the environment: `CHOCK_LOG_LEVEL=off|info|debug` in the shell the agent client was started from;
2. the repository: `<repo>/.chock/chock-log.json`;
3. the user: `~/.chock/chock-log.json`;
4. the default: `info`, `max_bytes` 1048576 (1 MiB).

The first that sets a value wins. `max_bytes` must be a whole number from 65536 (64 KiB) to
1073741824 (1 GiB); a value outside that range, an unknown level or key, or unreadable JSON is
ignored and named by `chock status --only log`. `CHOCK_GATE_LOG=0` still works: it is a deprecated
alias for `CHOCK_LOG_LEVEL=off`.

An agent cannot change the level. A hook's environment comes from the client, not from the
command an agent writes, so `CHOCK_LOG_LEVEL=off rm -rf build` changes nothing. Every chock bundle
refuses an agent's write to either settings file, raising or lowering, through a shell command (best
effort) or an Edit/Write (`chock-guardrails-protect`). A client with no chock bundle installed has
no such refusal: there the settings files are protected only by whatever policies the repository
itself installs. Edit the file yourself, in your own editor or shell.

Logging never changes a verdict, never raises and never blocks: a line that cannot be written is
dropped silently.

## Reading it

```bash
chock status --only log                       # both routes, per policy
chock status --only log --route plugin --plugin <name> --verdict block --since 7
chock status --only log --level debug --json  # allows included
chock status --only log --follow              # print new lines as they are written
```
