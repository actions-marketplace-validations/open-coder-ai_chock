- **A gate pattern cannot hang a commit or fail a hook open.** A `content_regex` or `test_integrity`
  pattern a backtracking engine can run in exponential time (`^(a+)+$` on a 60-character line) used to
  hang `git commit` on every platform, burn the client's hook timeout in the agent (which fails open) and
  wedge `chock check --history` on Windows. Now every gate pattern runs in a child interpreter the engine
  kills at a deadline (`PATTERN_SECONDS`, 10 s per judgement), on every platform: the git hook exits 2
  naming the gate, the write and tool_call paths refuse naming it, and the history scan errors naming it.
  `chock validate` and the compile step also refuse, naming the param and the pattern, a pattern whose
  nested repeats can run into each other (a linear-time check; overlapping alternation is left to the
  deadline). The vendored runtimes under `.chock/bin` are regenerated; `chock sync` rewrites them.
