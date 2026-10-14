- **A logged string can no longer drive the terminal or fake a record.** `chock status --only log` (text, `--by`,
  `--format md`), `chock status --summary`, `chock doctor`, `chock witness export`'s printed lines, `chock check
  --history` paths and SARIF message text now pass every logged or repo-derived string through one sanitiser,
  `chock.display.inert`: ANSI/OSC escapes (OSC 8 links, OSC 52 clipboard), BEL, backspace, CR, C1 controls, bidi
  overrides and invisible format characters are shown as visible escapes (`\x1b`, `‮`), and a newline inside
  a value shows as `\n` instead of starting a forged line. Other languages pass unchanged. The log itself is not
  changed; `--follow` and `--json` stay JSON.
