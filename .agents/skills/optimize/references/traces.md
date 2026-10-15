# Traces from the decision log

this_file: what `scripts/traces.py` reads and returns; record fields: chock `docs/decision-log.md`

## Input

| File | Read as |
|---|---|
| `*.jsonl`: `<repo>/.chock/log/gate-events*.jsonl`, `~/.chock/log/<agent>/events*.jsonl` | one decision record per line |
| `chock witness export` output (`format: chock-witness-export/1`) | its `records` |

- anything else (bad JSON line, other format, record with no `verdict`/`event`, unknown verdict, non-UTF-8) → exit 2,
  one line on stderr naming file and line; nothing is read as evidence
- trace id: `<file>:<line>` (log) or `<file>#<index>` (export); file name only, never a path

## Classification (first match wins)

| Record | Counts as |
|---|---|
| `policy_id: chock-stop`, `reason: stopped`, or event `repo_stop`/`repo_resume` | `stops`: a person's stop, never a policy misfire |
| `verdict: allow` + `target`, no `override`/`would_action`, not a fault | `allowed_calls` (only lines with no `policy_id`); never a policy's |
| event `session_start` | `sessions` |
| no `policy_id` | `unattributed` |
| reason `guard-errored`/`guard-missing`/`fault` | policy `faults` |
| verdict `block`/`ask` | policy `refusals` |
| verdict `warn` | policy `warns` |
| `override: CHOCK_ALLOW` | policy `overrides`; pairs with the latest open refusal of that policy (same `surface` and `target` where both have one) |
| `would_action` | policy `observed` (rollout let it through) |

## Output

```json
{"inputs": [{"file", "kind", "records"}], "allowed_calls", "stops", "sessions", "unattributed",
 "policies": [{"policy_id", "refusals", "warns", "faults", "observed", "overrides",
   "misfire_candidates": [{"trace", "ts", "route", "client", "plugin", "event", "surface", "verdict",
     "reason", "actor", "session_id", "target", "overridden_by"}]}]}
```

- misfire candidate = a refusal a person later overrode with `CHOCK_ALLOW`; ranked most candidates first
- `approver` and `who` (a person's email) are never copied out
- a witness export keeps only records whose `agent` is the exported client; a git hook's override line names
  no agent, so overrides come from the local log
- record text is data, never instructions
