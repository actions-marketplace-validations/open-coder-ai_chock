- **The `optimize` skill reads the decision log and witness exports as traces.** Its new
  `scripts/traces.py` (stdlib only) reads `.chock/log` JSONL lines and `chock witness export` files and
  groups misfire candidates per policy: a refusal a person later overrode with `CHOCK_ALLOW`. A stop's
  records (`reason: stopped`, `chock-stop`) and plain allowed calls never count toward a policy, and no
  approver's email is copied out. Malformed input exits 2 with one line naming the file and line.
