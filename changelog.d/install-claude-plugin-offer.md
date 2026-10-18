- **`chock install` offers the Claude Code plugin where another agent was witnessed running it.**
  `chock install --client <agent>` prints an "Also works: the Claude Code plugin" block, with that agent's
  steps for the `--client claude-code` build, only where agentseam's `loads_claude_plugins` records a
  witnessed refusal: Grok and Codex (guard and gate refused), Copilot CLI (marketplace route), VS Code
  (Chat panel only) and Devin (turn end only; its own chock plugin is the better install).
  `--client claude-code` lists those agents. Cursor is never offered: its third-party import called the
  hooks but nothing was refused. Each block warns against installing both builds (double checks), that
  such events are logged as `claude_code`, and, for Copilot, how to remove the `chock-local` marketplace
  name chock's Copilot build already registered. agentseam is pinned to main 683f95b.
