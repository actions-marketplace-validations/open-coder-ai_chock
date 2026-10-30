- **The decision log now says who did what on every line.** Each line carries `actor` (`agent:<client>`
  or `person`, by the agent rule a commit is judged by), the client's `session_id`, and on a tool call a
  `target` fingerprint, never content: a repository-relative path, `outside:sha256:<hex>` for a path
  outside the repository, `<program> sha256:<hex of the whole command>` for a shell command (no argument
  is ever written), or `<server>/<tool>` for an MCP call. Every allowed tool call is now logged at the
  default `info` level as one such fingerprint line, so the log can answer "what did the agent touch"; it
  was debug-only before. Redaction still runs first, files stay owner-only, and nothing leaves the machine.
