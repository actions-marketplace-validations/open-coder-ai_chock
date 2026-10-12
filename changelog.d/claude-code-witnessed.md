- **Claude Code is witnessed through its plugin: `chock sync` no longer prints "Untested" for claude_code.** In
  Claude Code 2.1.283 on Windows, the chock plugin refused `block-no-verify` at `PreToolUse:Bash` and
  `pin-github-actions` at the `PreToolUse:Write`, before either ran (org-plan
  `witness/results/witness-claude-code-2026-10-12.md`). The ledger row is for the plugin-hook surface only: the
  repo-hook route and the Stop (turn-end) refusal were not witnessed.
