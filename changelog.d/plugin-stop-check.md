- **Plugins carry the repo stop's own check.** Every `chock install` bundle and every hook-carrying
  `chock plugin build` package, in every client format (Claude Code, Codex, Copilot, Cursor, Devin, goose,
  Grok, Antigravity, Gemini CLI, OpenHands, Kimi Code, Factory Droid), now runs the runtime with
  `--stop-check` on every tool call, with no matcher and outside a bundle's member toggles, as
  `chock sync` already wires. While `chock stop` reaches the agent, a Read that no installed policy
  matches is refused on the plugin route too. Unstopped, the check allows; each installed package runs
  its own. Advisory-only packages ship no hooks and get none. The plugin repos pick it up at their next
  release.
