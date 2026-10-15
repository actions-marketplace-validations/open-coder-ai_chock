- **`chock stop --everywhere`: one stop for every agent on the machine.** It writes
  `~/.chock/stops/_everywhere.json`, and while it exists every Chock hook refuses every tool call, in every
  repository and session: the sync hooks, every plugin's `--stop-check`, the MCP gateway, and an agent's commit
  or push at the git hooks. An unreadable, corrupt or non-regular file refuses too. `chock resume --everywhere`
  is person-only (no agent shell, a TTY, the typed word `everywhere`) and lifts no per-repository stop.
  `chock status` and `chock doctor` show it; inside a repository both commands log with `"everywhere": true`.
