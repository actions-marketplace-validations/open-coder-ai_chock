# Codex adapter

The Codex adapter is a thin pointer to the agent-agnostic Chock core.

## Files

- No wrapper file: this agent reads `AGENTS.md` natively, so `chock init` writes nothing
  agent-specific for it.
- `docs/README.md` — human documentation

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Wiring: `src/chock/scaffold/adapters.py`
- Validator: the `chock check` CLI (`src/chock/validation/`)
