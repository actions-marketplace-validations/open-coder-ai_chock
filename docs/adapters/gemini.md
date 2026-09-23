# Gemini CLI adapter

The Gemini CLI adapter is a thin pointer to the agent-agnostic Chock core.

Verified against: https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html (Gemini CLI `GEMINI.md` context files).

## Files

- No wrapper file: Gemini CLI reads `AGENTS.md` natively, so `chock init` writes nothing
  agent-specific for it.

Gemini CLI discovers `GEMINI.md` files hierarchically: global `~/.gemini/GEMINI.md`, project root, `.gemini/`, and subdirectories.

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: the `chock check` CLI (`src/chock/validation/`)
