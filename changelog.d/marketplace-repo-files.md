- **`chock marketplace build` writes `llms.txt` and `.github/ISSUE_TEMPLATE/config.yml`.** A plugin
  repo is rebuilt from chock-catalog, so an issue filed there cannot be fixed there and it had no
  machine-readable summary. The build now emits an `llms.txt` (one line per published plugin, its
  posture in this client and its catalog page) and an issue config that disables blank issues and
  routes policy issues to chock-catalog, build bugs to chock and vulnerabilities to chock's private
  advisory route. `--check` reports either file missing or hand-edited. The devin tree's file says
  best-effort, never enforces.
