- **Claude Code's plugin is witnessed.** In Claude Code 2.1.283 on Windows, the chock plugin refused
  `block-no-verify` at `PreToolUse:Bash` and `pin-github-actions` at the `PreToolUse:Write`, before either ran
  (org-plan `witness/results/witness-claude-code-2026-10-12.md`). The ledger row is for the plugin-hook surface
  only: the repo-hook route and the Stop (turn-end) refusal were not witnessed.
- **`chock sync`'s "Untested" now means no live run of chock's repo hooks in this client.** A plugin witness covers
  `chock install`, not the hooks sync wires, so sync no longer counts one. Sync now calls claude_code, codex_cli
  and cursor Untested; vscode_copilot, witnessed on agent-hooks, is not.
