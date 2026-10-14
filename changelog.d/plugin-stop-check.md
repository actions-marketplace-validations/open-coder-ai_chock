- **`chock install` bundles carry the repo stop's own check.** Every plugin bundle, in every client it
  packages (Claude Code, Codex, Copilot, Cursor, Devin, goose, Grok, Antigravity, Gemini CLI, OpenHands,
  Kimi Code, Factory Droid), now runs the runtime with `--stop-check` on every tool call, with no
  matcher and outside the member toggles, as `chock sync` already wires. While `chock stop` reaches the
  agent, a Read that no installed policy matches is refused on the plugin route too. Unstopped, the check
  allows. The plugin repos pick it up at their next release.
