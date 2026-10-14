- **An allowed tool call is one decision-log line, not one per policy hook.** At `info`, however many
  policy hooks judge a call, its plain allow is written once, at once, by its first hook, and names no
  policy (`debug` still writes every hook's line). `chock status` counts allowed calls in total
  (`allowed_calls`), never per policy; per-policy columns show blocks, asks, warns and overrides. With no
  client call id, identical calls in the same second are one line. Every block, ask, warn, fault and
  override keeps its own line per policy. The `target` fingerprint is
  tighter: a Windows drive or UNC path on macOS or Linux is hashed as outside the repository; a shell
  program is named only when it is a common command or a plain word with no folder, digit, quote or
  redirect, else `-`; an MCP `server/tool` is redacted and cut to 128 characters; `client_type` keeps only
  `[a-z0-9_-]`, at most 32; and a path that is not UTF-8 no longer drops its line. `chock doctor` now warns
  at `info` when sessions start but no hook fires. The fingerprints are unsalted, so anyone holding the
  log can confirm a guess; docs/decision-log.md says so.
