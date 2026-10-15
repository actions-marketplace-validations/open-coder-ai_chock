- **`chock incident`** prints an ordered, redacted timeline of the local decision log for a window
  (`--since`, `--until`, both routes, rotated files included): sessions, actors, policies fired,
  verdicts, target fingerprints, stops, resumes and overrides, with each hash-chain break and
  unreadable line shown in place and a per-log chain line. Plain allowed calls are counted per
  session. `--format text|md|json`; text and Markdown are terminal-inert. The approver's email is
  shown locally; `--share` leaves out `approver` and `who`. It is evidence for a report, never a report,
  and sends nothing.
