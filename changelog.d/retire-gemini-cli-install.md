- **`chock install --client gemini-cli` is retired: use `--client antigravity`.** Google replaced Gemini CLI
  with Antigravity CLI for unpaid and Google One users (2026-06-18), and Gemini CLI is not optimized for
  Gemini 4 Argon, so chock no longer builds a Gemini CLI extension. `--client gemini-cli`, or a selection
  naming it, exits 1 with one line pointing to `--client antigravity`; `chock plugin build --format gemini` is
  gone. `chock sync` still wires Gemini CLI's repo hooks (`.gemini/settings.json`) for paid users who run it.
