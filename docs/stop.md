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
git hook the client comes from the agent's marker: one that names a shorter client (`AI_AGENT=codex_...`
is `codex`) is reached by a stop on a client it begins (`codex_cli`), and an agent naming no client is
reached by every stop. Both err toward refusing.

Only a person changes a stop: `stop` and `resume` refuse, and log the refusal, when the shell carries an
agent marker (the same rule as a commit). `resume` removes the file.

`chock sync` wires one hook of its own per client, `--stop-check`, with no matcher and whatever
policies are installed, so the stop sees every tool call, reads included. The plugin route carries
the same entry, in every client format (Devin's included):

| Route | Stop check |
| --- | --- |
| `chock sync` | one per client, beside chock's other entries |
| `chock install` bundle | one per bundle; member toggles never reach it |
| `chock plugin build` package (the marketplace route) | one per package that ships hooks |
| an advisory-only package (skill text, no hooks) | none, as `chock sync` wires none where it wires nothing |
| `chock gateway run` (MCP) | in the gateway, before its gates: every `tools/call` |

The gateway refuses each `tools/call` while a stop reaches it (an MCP error, `stopped: <reason>`); it
forwards `initialize`, `tools/list` and every other method, so the client can still connect and list
tools. It judges a stop in its `--repo`, its working directory, and every folder `initialize` names
(`roots`, `workspaceFolders`), each resolved to its repository (the nearest folder holding `.git`) as the pre-tool hook does. The client is
the MCP `clientInfo.name` read as a client id (`claude-code` is `claude_code`; `codex-mcp-client` is
`codex`, reached by a stop on `codex_cli`); a name that is no client's is reached by every stop.
`clientInfo.name` is the client's own claim. A stop file it cannot read, or a check that fails, refuses.

With several packages installed, each runs its own check on every tool call. Unstopped it allows and
logs nothing of its own beyond the call's one allow line. `chock status` shows a stop on its first line. Every refusal, the stop and
the resume are logged ([Decision log](decision-log.md#stop-and-override)). The file is local state:
`chock init` lists it in `.gitignore`, and CI never reads it.

**Limits.**

- It reaches only agents whose hooks Chock wires and that the client runs. An agent with no hook is
  stopped at commit and push only.
- Devin's hook is best-effort: the vendor runs it fail-open, so a hook that errors or times out lets
  the call through.
- It refuses the *next* action. It does not end a process already running (a background shell, a
  spawned server), and it revokes no credential.
- A person, or an agent working outside this repository's hooks, is not affected.
