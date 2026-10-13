- **`chock doctor` and a session-start heartbeat.** `chock doctor [--client X] [--repo .]` checks
  each client's hooks on the sync and plugin routes: the hooks file runs chock's runtime, the
  launcher and a Python 3.11+ are there, the runtime is the one the installed chock builds (and a
  plugin's recorded engine version and commit match), Codex-style trust, the client version
  against agentseam's witnessed ones, and when each hook surface last fired. Each line is PASS,
  WARN, FAIL or INFO with a one-line fix; it reads only, never runs a client and never uses the
  network. Where a client documents a session-start event, `chock sync` and `chock install` now
  wire a heartbeat hook that writes one `session_start` line per session at `info`; it never
  blocks. Clients without one are listed as "no heartbeat available".
