- **goose's plugin is witnessed: `chock install --selection --client goose` no longer warns "Untested" or asks for
  evidence.** In goose 1.55.0 on Windows 11, chock's plugin refused `block-no-verify` on a `git commit --no-verify`
  shell command before it ran and `pin-github-actions` on a workflow write at the write, while `git status` ran
  (org-plan `witness/results/witness-goose-2026-10-18.md`). That held only with Git for Windows' `sh` on PATH: goose
  runs every hook with `sh -c`, and without `sh` it denied every tool call (`on_failure: block`). The goose install
  output now warns about this on Windows.
