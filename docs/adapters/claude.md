# Claude adapter

The Claude adapter is a thin pointer to the agent-agnostic Chock core.

## Files

- `CLAUDE.md` (repo root) — agent-readable wrapper that points to `AGENTS.md`
- `.claude/settings.json` — hook entries chock installs
- `docs/README.md` — human documentation

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Wiring: `src/chock/scaffold/adapters.py`
- Validator: the `chock check` CLI (`src/chock/validation/`)
