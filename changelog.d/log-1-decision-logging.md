- **Decision logging with levels, on both routes.** Every hook now logs one line per decision at a
  level a person sets: `off`, `info` (the default: blocks, asks, warns, guard faults and overrides)
  or `debug` (every call, allows included, plus a redacted, capped trace; never file contents).
  Allows are no longer written at `info`. The plugin route (`chock install`), which logged nowhere,
  writes `~/.chock/log/<agent>/events.jsonl`; the sync route keeps `.chock/log/gate-events.jsonl`.
  Level and rotation size (`max_bytes`, default 1 MiB, 64 KiB to 1 GiB) come from `CHOCK_LOG_LEVEL`,
  then `.chock/chock-log.json`, then `~/.chock/chock-log.json`; `CHOCK_GATE_LOG=0` is a deprecated
  alias for `off`. Every bundle refuses an agent's write to either settings file. `chock status --only log`
  reads both routes and adds `--route`, `--level`, `--verdict` and `--follow`. See
  [Decision log](docs/decision-log.md).
