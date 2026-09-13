# Chock setup

This repo uses Chock for agent policy engineering. This folder is human documentation: agents take their rules from `AGENTS.md`, and read the files here on demand — when the task is to change one of them — rather than as part of general work.

## Structure

- `.agents/skills/` — your business skills
- `.agents/policies/` — your rules, hooks, and policies
- `docs/` — human documentation
- `AGENTS.md` — agent-readable rules

## Next steps

1. Create your first policy using the `/policy-init` skill installed in your agent's skill directory.
2. Validate with `chock check`.
