- **Cursor is witnessed: `chock install --selection --client cursor` no longer warns "Untested".** On Windows,
  Cursor refused `block-no-verify` at `beforeShellExecution` and `pin-github-actions` at the `preToolUse` write
  (org-plan `witness/results/witness-cursor-2026-10-11.md`). The `client` warning that chock has not witnessed
  an install now names no client. Cursor's admin-setting warning stays.
