- **`chock stop` and `chock resume`: a person's stop on agents in one repository.** `chock stop [--agent
  <client>] [--reason ...]` writes .chock/stop.json (scope, reason, who, when); `chock resume` removes it;
  `chock status` shows it on its first line. While it exists, every tool call by an agent in scope is
  refused at Chock's pre-tool hooks, reads included and the Devin hook too, with `stopped: <reason>`, and an
  agent's commit or push is refused at the git hooks; a person's passes. Neither `CHOCK_ALLOW` nor the
  rollout level loosens it, and a file that exists but cannot be read refuses every agent. Each refusal is a
  decision-log line with reason `stopped`; the stop and the resume are logged with who and when. `chock
  init` lists the file in `.gitignore`. Sync wires one matcher-less `--stop-check` hook per client beside chock's
  others, so a stop sees every tool call whatever the policies match. Only a person changes a stop: `chock
  stop` and `chock resume` refuse in a shell with an agent marker. Limits: it reaches only agents whose hooks
  Chock wires (a `chock install` plugin has no stop check); Devin's hook is best-effort and fail-open per the vendor; it refuses the
  next action, ends no running process and revokes no credential. `chock stop` also writes a `0o600` machine
  registry entry under `~/.chock/stops/`: a hook whose client names no project root refuses while any entry is
  in force. Paths are resolved through symlinks and read from anywhere in a call's input; git hooks find the
  stop through `GIT_DIR`, `GIT_WORK_TREE` and the common dir and run only the main checkout's gate.py; a bare
  repository's stop reaches its worktrees; `CHOCK_AGENT_COMMIT=0` clears no agent marker for a stop.
- **A `CHOCK_ALLOW` override names its approver.** The override's log line carries `approver`, the git
  `user.email` of the person's shell, beside its `policy_id`. It stays in the local `0o600` log: `chock
  witness export` leaves it out, and Chock sends nothing.
