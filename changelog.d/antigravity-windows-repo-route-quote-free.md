- **Antigravity on Windows: `chock sync` writes quote-free hook commands too, following the plugin's rule.**
  The repo route's double-quoted git alias reaches cmd.exe the same way the plugin's did, so on Windows, for a
  client whose store data says `windows_hook_command: quote_free`, sync now writes each command in
  `.agents/hooks.json` as `git -c alias.chock-hook=!<refusal> chock-hook <runtime> <args>` with no quote or
  space in any argument; the missing-launcher refusal (exit 2) is kept, and an argument that cannot be carried
  bare is refused. `.chock/compiled` is unchanged; every other client and every non-Windows sync is
  byte-identical. A committed `.agents/hooks.json` synced on Windows is the Windows form. Not witnessed yet.
- **goose's guard note and Antigravity's posture render their witness clause from the ledger.** goose's note
  now cites its witness row and says goose runs every hook with `sh -c`, so sh (Git for Windows' sh on Windows)
  must be on PATH, else every tool call is denied (org-plan `witness/results/witness-goose-2026-10-18.md`).
  Antigravity's posture says "not witnessed by chock" until its ledger row lands.
