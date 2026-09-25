# VS Code adapter

The VS Code adapter exposes Chock as a workspace-scoped custom agent.

Verified against: https://code.visualstudio.com/docs/agent-customization/custom-agents (VS Code custom agents).

## Files

- No wrapper file: VS Code reads `AGENTS.md` natively, so `chock init` writes nothing
  agent-specific for it.

VS Code custom agents are defined in `.agent.md` files. Workspace-scoped agents live in `.github/agents/` (or `.claude/agents/` in Claude format).

## Pointers

- Core rules: `AGENTS.md`
- Skills: `.agents/skills/`
- Policies: `.agents/policies/`
- Validator: the `chock check` CLI (`src/chock/validation/`)
