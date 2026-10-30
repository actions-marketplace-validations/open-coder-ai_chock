- **Copilot's label says the write is judged before it lands.** Copilot CLI 1.0.94 on Windows refused an
  unpinned workflow `create` at `preToolUse`, and nothing landed (org-plan
  `witness/results/witness-copilot-2026-10-11.md`). `chock install --client copilot` now reads "blocks on an
  agent's file writes and at turn end", and a client note says VS Code agent mode's write path is unmeasured.
