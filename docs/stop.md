# Stop: a person's stop on agents in one repository

```bash
chock stop   [--repo .] [--agent <client>] [--reason "<why>"]
chock resume [--repo .]
```

`stop` writes .chock/stop.json (scope, reason, who as git `user.email`, when). While it exists:

- every tool call an agent in scope makes is refused at Chock's pre-tool hook, reads included, with
  `stopped: <reason>`; the Devin hook too;
- an agent's commit or push is refused at the git hooks; a person's passes (the agent rule in
  [Decision log](decision-log.md#who-did-what));
- neither `CHOCK_ALLOW` nor the rollout level (`observe`, `ask`) loosens it;
- a file that exists but cannot be read or parsed refuses every agent (fail closed).

`--agent` names one client (`codex_cli`, `claude_code`, ...); without it every agent is stopped.
`resume` removes the file. `chock status` shows a stop on its first line. Every refusal, the stop and
the resume are logged ([Decision log](decision-log.md#stop-and-override)). The file is local state:
`chock init` lists it in `.gitignore`, and CI never reads it.

**Limits.**

- It reaches only agents whose hooks Chock wires and that the client runs, and only tool calls a
  wired hook sees: a client runs a hook for the tools its matcher names. An agent with no hook is
  stopped at commit and push only.
- Devin's hook is best-effort: the vendor runs it fail-open, so a hook that errors or times out lets
  the call through.
- It refuses the *next* action. It does not end a process already running (a background shell, a
  spawned server), and it revokes no credential.
- A person, or an agent working outside this repository's hooks, is not affected.
