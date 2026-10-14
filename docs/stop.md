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

`--agent` names one client (`codex_cli`, `claude_code`, ...); without it every agent is stopped. At a
git hook the client comes from the agent's marker, lower-cased with `-` read as `_`: a client whose name
starts with the scope is reached (`cursor-agent` by `cursor`), so is a shorter form of it (`AI_AGENT=codex_...`
is `codex`, reached by `codex_cli`), and so is an agent naming no client or one no Chock client id matches.
All three err toward refusing.

A stop reaches every repository the call works in or touches: the one Chock's hook runs for, every
repository above the call's folder and above each path it names (a nested repository inside a stopped one
included), and, from a linked worktree (`git worktree add`, Claude Code's `.claude/worktrees/`), the main
checkout's stop as well as its own. The file is not committed, so a worktree has no copy of its own.

Only a person changes a stop: `stop` and `resume` refuse, and log the refusal, when the shell carries any
agent marker. Unlike a commit, `CHOCK_AGENT_COMMIT=0` does not clear one here: an agent can set it too. `resume` removes the file.

`chock sync` wires one hook of its own per client, `--stop-check`, with no matcher and whatever
policies are installed, so the stop sees every tool call, reads included. Unstopped it allows and
logs nothing of its own beyond the call's one allow line. `chock status` shows a stop on its first line. Every refusal, the stop and
the resume are logged ([Decision log](decision-log.md#stop-and-override)). The file is local state:
`chock init` lists it in `.gitignore`, and CI never reads it.

**Limits.**

- It reaches only agents whose hooks Chock wires and that the client runs. An agent with no hook is
  stopped at commit and push only. A plugin installed with `chock install` carries no stop check: there
  a stop reaches only the tools that plugin's own hooks match.
- Devin's hook is best-effort: the vendor runs it fail-open, so a hook that errors or times out lets
  the call through.
- It refuses the *next* action. It does not end a process already running (a background shell, a
  spawned server), and it revokes no credential.
- A person, or an agent working outside this repository's hooks, is not affected. Such an agent can also
  delete .chock/stop.json directly: the file is protected only from agents whose calls a hook judges.
