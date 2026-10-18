- **Antigravity's plugin is witnessed: `chock install --selection --client antigravity` no longer warns "Untested" or
  asks for evidence.** In Antigravity IDE on Windows 11 (version not recorded), chock's shipped plugin, built on Windows
  (quote-free hook command), refused `block-no-verify` on a shell command before it ran and `pin-github-actions` on a
  workflow write at turn end, not at the write, while `git status` ran (org-plan
  `witness/results/witness-antigravity-2026-10-18.md`). The claim is for a Windows build only. The turn-end and
  fail-mode warning stays.
