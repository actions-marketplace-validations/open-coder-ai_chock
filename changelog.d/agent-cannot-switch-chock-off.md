- **An agent cannot switch chock off.** `chock sync`, `recompile`, `install-hooks`, `enable`, `disable`,
  `add`, `remove`, `init` and `compile`, the commands that change `.chock/config.yaml`, `chock.lock` or the
  compiled tree, refuse under an agent marker (`CLAUDECODE=1`, `AI_AGENT`, a truthy `CHOCK_AGENT_COMMIT`, a
  configured `agent_commit_env` name) with the rule `chock resume` applies: a person runs them from their own
  shell. The refusal is logged (`policy_id: chock-cli`). `sync --check`, `check` and `status` stay open. One
  actor rule now serves every check: `CHOCK_AGENT_COMMIT=0` unsets that one variable and clears no vendor
  marker, so `CHOCK_ALLOW=<id> CHOCK_AGENT_COMMIT=0` in an agent's terminal no longer answers an ask and
  `CHOCK_ROLLOUT` is ignored there; a person's own shell, which has no marker, keeps both. A refused ask tells
  a person the `CHOCK_ALLOW` line and tells an agent to ask the person, naming no override. For the agent
  asking `chock_guidance`, a `policies.disabled` entry counts only once committed (HEAD), the way the
  committed rollout caps the working tree's. docs/assurance-case.md restates "tamper-evident" to what the
  mechanism gives and lists the bytecode and runtime-pin limits.
