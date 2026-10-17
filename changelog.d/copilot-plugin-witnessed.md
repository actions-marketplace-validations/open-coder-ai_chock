- **Copilot's plugin is witnessed.** In GitHub Copilot CLI 1.0.94 on Windows, the chock plugin refused
  `pin-github-actions` on a workflow `create` and `chock-guardrails-protect` on a shell write to
  `.chock/guardrails.json`, both at `preToolUse`, before either landed (org-plan
  `witness/results/witness-copilot-2026-10-11.md`). The ledger row is keyed `copilot`, agentseam's id for the plugin
  bundle format, and covers the plugin-hook surface in Copilot CLI only: VS Code agent mode, a toggle-file write through
  the edit tool and a delete-only `apply_patch` were not covered. `chock install --client copilot` prints the same
  warnings as before.
