# Doctor

Most clients fail open when a hook crashes, times out or never loads, so a silent hook looks
exactly like a protected session. `chock doctor` checks that each client's chock hooks are in
place, current, and seen running.

```bash
chock doctor [--repo .] [--client <id>] [--client-version <v>] [--sessions 3] [--json]
```

Read-only; no network, and it never runs a client. For each client with chock hooks, on the
sync route (the vendored runtimes `chock sync` put in `--repo`) and the plugin route (bundles
`chock install` built into a client's default folder), it prints one line per check, `PASS`,
`WARN`, `FAIL` or `INFO`, with a one-line fix:

- **hooks**: the file the client reads runs chock's runtime, and the runtime is there;
- **launcher**: the launcher is there, and a `python3`, `python` or `py` on PATH is 3.11+;
- **engine**: the runtime is byte-identical to what the installed chock builds; a plugin's
  recorded engine (version and commit, in `chock.selection.json`) is compared too;
- **trust**: for clients that run a hook only once a person trusts it (Codex, Grok), how to;
  chock cannot read that record;
- **client**: the versions agentseam witnessed; `--client-version` compares yours;
- **last fired** and **heartbeat**: from the [decision log](decision-log.md), the last record per
  hook surface, and the `session_start` heartbeats. Tool-use records with no heartbeat warn; at
  level `debug`, no hook record in the last `--sessions` sessions warns. A client with no
  documented session-start event reads "no heartbeat available", never a failure.

`--client` takes an install client id (`claude-code`) or an agent id (`claude_code`). Exit 1
when any check fails or no chock hooks are found, else 0.
