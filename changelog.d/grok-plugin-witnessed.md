- **Grok's plugin is witnessed: `chock install --selection --client grok` no longer warns "Untested".** In Grok Build
  1.0.62 on Windows 11, a chock plugin installed with `grok plugin install --trust` (no hook trust prompt) and enabled
  under Grok's generated name refused `block-no-verify` on a `git commit --no-verify` shell command before it ran
  (org-plan `witness/results/witness-grok-2026-10-17.md`). The ledger row is keyed `grok` and covers the guard only:
  `pin-github-actions` is advisory on Grok and the workflow write landed, as labelled, so no gate refusal is claimed.
  Grok still warns that its hooks fail open, and the agentseam evidence issue stays linked.
