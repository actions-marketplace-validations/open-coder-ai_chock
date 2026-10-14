- **A finding can no longer drive the terminal or the CI log through the gate's own output.** The vendored gate
  runtime's commit-time and ask refusals on stderr, its `::error`/`::warning` workflow commands and its step
  summary now apply the same rule as `chock.display.inert`: ANSI/OSC escapes (OSC 8 links, OSC 52 clipboard),
  BEL, C0/C1 controls, lone surrogates, line and paragraph separators, bidi overrides and isolates and invisible
  format characters are shown as visible escapes (ESC as `\x1b`), and a newline inside a path or finding shows
  as `\n` instead of starting a forged line. A script's own multi-line message keeps its lines; workflow-command
  data still encodes `%`, CR and LF. Verdicts, exit codes and the decision log are unchanged.
