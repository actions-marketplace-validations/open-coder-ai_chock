- **`chock new` and `chock check` agree with what they print.** `chock new` now prints two
  next steps, `python -m chock sync --repo <root>` then `python -m chock check --repo <root>`
  (no `&&`, which Windows PowerShell 5.1 lacks); the old `chock check <root>` exited 2
  (`check` takes `--repo`). `chock check` ends with one line,
  `== result: PASS` or `== result: FAIL (exit <n>; see the FAIL above)`, so a failing section is no longer
  followed by a later section's `[PASS]` as the last word; the exit code is unchanged.
- **The `content_regex` template no longer flags itself.** Its gate message said the marker
  it refuses, and INDEX.md quotes the message, so committing a fresh scaffold was blocked by
  its own policy. The message now spells the marker `DO-NOT-COMMIT`, which the pattern does not
  match.
