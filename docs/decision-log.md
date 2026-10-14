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
once never interleave. One rotated file is kept beside each (`gate-events.1.jsonl`, `events.1.jsonl`).
Each write takes a lock beside the file (fcntl, or msvcrt on Windows) to rotate and chain the line (see
[Hash chain](#hash-chain)). The sync file is the same file earlier versions wrote, so older readers keep working.

## Hash chain

Each line carries `seq`, its place in its file's chain, and `prev`, the sha256 of the line before it
(that line's exact bytes, without the newline). A log's first line names 64 zeros. After a rotation the
new file's first line names the rotated file's last, so the chain runs across both files. Every route
writes through the same journal: runtime hooks, git hooks, the MCP gateway, `chock stop` and
`chock resume`, and overrides.

A writer waits up to one second for the lock. A line it cannot chain (the lock stayed held, or the last
line could not be read) is still written, with `unchained` naming why. A chaining failure never
changes a verdict.

```bash
chock status --verify-log [--route sync|plugin] [--json]   # exit 0 intact, 1 at a break
chock status --verify-log --head <seq>:<sha256>            # confirm a head you kept is still there
```

It walks each log (rotated file first) and reports the first break: the file, the line, and the
expected and found `prev` or `seq`. An edited, deleted, inserted or reordered line breaks the link of
the line after it. History that is missing or rotated away is not a break: the walk reports
`chain starts at <hash> (seq N)`. Lines written before chaining existed are counted, then the chain
starts. A line written after that by a runtime that does not chain yet (until `chock sync` regenerates
it, or the plugin is reinstalled) is a break of kind `unchained`.

What it shows, and what it does not:

- It shows a change made after the fact to someone who kept an earlier head (`seq` and `sha256`, as
  `--verify-log` prints it and `chock witness export` carries it): `--head` fails once that record
  changes, even when every later hash was recomputed.
- It does not stop anyone who can write the file. A local admin, or any process running as you, can
  rewrite the whole file and every hash, and the walk then passes. Without a kept head, the chain
  shows only edits that left the later links alone.
- Deleting the newest lines, or the oldest lines of the oldest file, leaves no break; only a kept head
  shows the first.
- It makes no claim about any regulation or standard.

## Levels

| Level | Writes |
| :--- | :--- |
| `off` | nothing |
| `info` (default) | one line each time a policy fires: block, ask, warn, a guard fault, or an override or rollout level that let a finding through; and one line per allowed agent tool call, carrying only its `target` fingerprint. However many policy hooks judge that call, its allow is one line, written at once by the first hook to run and naming no policy (no `policy_id`, `plugin` or match fields): an allowed call is the call's, not any one policy's. A call is known by the client's `tool_use_id`, else by session, second and `target`, so with no id two identical calls in one second are one line. Every block, ask, warn, fault and override keeps its own line per policy |
| `debug` | every hook call (one allow line per policy hook), the turn's end included, plus a `trace`: wire event, tool, matched rule (or "no rule matched"), the guard's exit code, per-stage timings, and the command or path cut to 200 characters with every value the scan-secrets policy would block replaced by `[redacted]` |

`chock status` counts allowed tool calls once each, in total (`allowed_calls`), and never toward a
policy: its per-policy columns show what a policy decided, its blocks, asks, warns and overrides.

Each line carries `ts`, `route`, `level`, `agent`, `client` (when the payload names one), `event`,
`policy_id`, `surface`, `verdict`, `reason`, `duration_ms`, `can_ask`, `actor`, `session_id` (the
client's session id, when the payload carries one) and, on a tool call, `target`. The sync route adds
`chock_version` (left out when the hook's Python has no chock installed). The plugin route adds
`plugin` and `plugin_version` instead, never `chock_version`: a plugin runs its own bundled Python, not chock. On the sync route a compiled gate's line is written by `gate.py`
and keeps its own fields (`kind`, `match_count`, `matches`, `rules`), plus `actor`, and `session_id`
and `target` from the hook that ran it. A git hook's line carries `actor` only: a commit is no tool call.

## Who did what

| Field | Value |
| :--- | :--- |
| `actor` | `agent:<client>` for an agent hook (the payload's client, else the bundle's agent). On a git hook, the agent rule a commit is judged by: `CLAUDECODE=1` or `AI_AGENT` names the client, any other marker is `agent:unknown`, none (or `CHOCK_AGENT_COMMIT=0`) is `person` |
| `session_id` | the client's session id, when the payload carries one |
| `target` | a fingerprint of what one tool call touched, never its content (below) |

| A tool call on | `target` |
| :--- | :--- |
| a file in the repository | its repository-relative path, e.g. `src/app.py` |
| a file outside it (or with no repository) | `outside:sha256:<hex of the absolute path>`: a home path names the user. On macOS and Linux a Windows drive or UNC path (`C:\...`, `\\server\...`) is outside, hashed as given |
| a shell command | `<program> sha256:<hex of the whole command line, UTF-8>`, e.g. `git sha256:9f2c...`. Leading `NAME=value` words are skipped; no argument is ever written. The program is named only when it is a common command (`git`, `python3`, `/usr/bin/git` as `git`) or a plain word with no folder, digit, quote or redirect; anything else is `-`. To confirm a suspected command: `printf %s '<command>' \| sha256sum` |
| an MCP tool | `<server>/<tool>`, redacted, cut to 128 characters |
| any other tool | the tool's name |

Redaction runs on every `target` first, the same scan-secrets pattern as a trace. A stop, a session
start and an unreadable payload have no `target`. `client`, and the client in `actor`, keep only
`a-z`, `0-9`, `_` and `-` of the payload's `client_type`, at most 32. A character that is not UTF-8
(a lone surrogate in a path) is written as the text `\uXXXX`, never dropping the line.

**Known limit.** The hashes are unsalted sha256. Anyone holding the log can confirm a guessed path or
a guessed command (a short or common one is easy to guess); they cannot read one they did not guess.
Treat the log as private to the machine's owner.

## Stop and override

While a stop is in force (`chock stop`, [Stop](stop.md)),
each call it refuses is a `block` line with `"reason": "stopped"` and the fields above (`actor`,
`session_id`, `target`). A pre-tool refusal names the hook's policy; a commit or push refused at
the git dispatcher names `chock-stop`. `chock stop` and `chock resume` each write one `chock-stop`
line, event `repo_stop` or `repo_resume`, with `scope`, `who` (git `user.email`) and `when`.

A person's `CHOCK_ALLOW` override is an `allow` line with `"override": "CHOCK_ALLOW"`, the
`policy_id` it answered, and `approver`: the git `user.email` of the shell that ran it.

`approver` and `who` name a person. They stay in this local log (created `0o600`): Chock sends
nothing over the network, and `chock witness export` leaves both out.

## MCP gateway

`chock gateway run` writes to the sync route's file (`<repo>/.chock/log/gate-events.jsonl`, the
`--repo` it serves) with the fields above: `agent` and `surface` are `mcp-gateway`, `actor` and
`client` come from the MCP client's `initialize` (`clientInfo.name`, same character rule), and
`target` is `<server>/<tool>`: the server's `serverInfo.name` (`-` before it answers), redacted, cut
to 128 characters. A tool call's arguments are never written. stdio MCP carries no session id, so
there is no `session_id`.

| Call | Lines |
| :--- | :--- |
| forwarded | one `allow` line, reason `no-rule`, no `policy_id`; plus one `warn` line per warning policy |
| refused by a policy | one `block` line per refusing policy, reason `gate-block` (`gate-ask` for an ask: the gateway cannot prompt) |
| a gate that cannot run, or malformed `params` | `block`, reason `fault`: the gate's policy, or `mcp-gateway` |
| refused because a stop reaches it ([Stop](stop.md)) | `block`, reason `stopped`, policy `chock-stop` |
| refused because another element of its batch was | `block`, reason `batch`, policy `mcp-gateway` |

The line is written after the verdict is carried out; a log that cannot be written changes no
verdict.

## Heartbeat

Where the client documents a session-start event, chock wires one more hook there (the runtime,
with no flags) on both routes, and it writes one line per session at `info`:

```json
{"ts": "...", "event": "session_start", "route": "sync", "agent": "codex_cli", "session_id": "...", "chock_version": "0.15.2", "level": "info"}
```

The plugin route's line carries `plugin` and `plugin_version` instead of `chock_version`. The
hook never refuses and never blocks the session; a heartbeat that cannot be written is dropped.
Most clients fail open when a hook crashes or never loads, so a session with no heartbeat is the
sign of a hook that did not run: `chock doctor` reports it. Antigravity, Mistral Vibe and
Windsurf document no session-start event, so they have no heartbeat.

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

## Summary

```bash
chock status --summary [--since DAYS] [--route sync|plugin] [--json]
```

- Fires per policy and per client, with block, ask, warn and fault counts and rates. A fault is a hook
  that could not judge the call: reason `guard-errored`, `guard-missing` or `fault`.
- p50 and p95 `duration_ms` per hook (client and surface), nearest rank. At `info` every tool call is
  logged, but a turn's end only when a policy fired on it; set `debug` to time every call.
- **WARN when a hook's p95 is within 25% of its client's hook timeout.** A client timeout fails
  open, so a call slower than that goes through unchecked. The timeout is the one chock writes on
  every hook entry; where a vendor's hook schema has no timeout field (`src/chock/data/hook_timeouts.json`),
  the client's own default applies, and an undocumented one is shown as `unknown`, never warned on.
- The top 5 guard faults, by policy and reason code.
- Heartbeats (`session_start` records): hook records with no `session_start` before them, and
  `session_start` records with no hook record after them, per route and client. The summary groups by
  heartbeat, not by `session_id`: a session runs from one heartbeat to the next. A client agentseam records no
  session-start event for is listed as "no heartbeat available", never as missing one.

## Evidence export

```bash
chock witness export --client <client> [--since DAYS] [--out FILE] [--repo .]
```

Writes one client's records from both routes to a local JSON file, redacted: the home folder is
written `~`, and every string goes through the same scan-secrets redaction and 200-character cap as a
debug trace. Beside the records it names what an agentseam evidence report asks for: the agent, its
version (fill it in), the platform, chock's version and commit, each plugin's version string, the
catalog ref (the plugin's install marker, or `chock.lock`), and the events seen. It prints the
agentseam issue to attach the file to: the client's "evidence wanted" issue, read from agentseam's
matrix row or chock's install warnings, otherwise a new evidence report. `--client` takes an
agentseam id (`gemini_cli`), a `chock install` client (`gemini-cli`) or a `chock sync` agent name
(`gemini`). `--out` must name a new `.json` file: an existing file is refused, never overwritten, and the
export is created readable by you only. Nothing is uploaded: you attach the file yourself, after reading it.

The export also carries `chain`: each log's head (`seq`, `sha256` of its last line) and whether its
walk was intact, so an attestation over the export binds the log as it stood. A person's override at a
git hook (`CHOCK_ALLOW`, no agent on the line) is exported as evidence beside the client's records;
`approver` and `who` stay in the local log only.
