- **Devin is witnessed through its plugin: the Devin plugin's posture now says "witnessed blocking on Devin CLI
  3000.11.3 (local session), Windows, 2026-10-08" instead of "not witnessed by chock".** A chock plugin installed with
  `devin plugins install --local` refused `git commit --no-verify` and an agent's `chock bundle off` before either ran;
  `pin-github-actions` let the write through and refused only at turn end; self-protection held (org-plan
  `witness/results/witness-devin-2026-10-08.md`). The ledger row is for the plugin-hook surface only: the repo-hook
  route was not witnessed, so `chock sync` still prints "Untested" for devin.
