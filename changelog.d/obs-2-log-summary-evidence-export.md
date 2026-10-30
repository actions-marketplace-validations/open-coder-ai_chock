- **Decision-log summary and evidence export.** `chock status --summary` reports fires per policy and
  per client, block/ask/warn/fault rates, p50/p95 hook latency with a WARN when p95 is within 25% of
  the client's hook timeout (a timeout fails open), the top guard faults, and heartbeat gaps (hook
  records with no `session_start`, and `session_start` records with no hook record). `chock witness
  export --client <c>` writes that client's records, redacted, to a local file in the shape agentseam
  evidence reports ask for, and prints the client's "evidence wanted" issue; it never uploads. See
  [Decision log](docs/decision-log.md#summary).
