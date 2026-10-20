- **A fresh clone arms itself again, from what is committed: `chock sync --committed`.** Since `chock sync` became
  person-only, the SessionStart hook could not arm a clone from inside an agent's session. `--committed` takes only
  `--repo`, runs under an agent marker, and refuses (the same person-only message, naming the file) when
  `.chock/config.yaml`, `chock.lock` or anything under `.agents/policies` differs from HEAD or HEAD cannot be read;
  otherwise it is the normal recompile. Every other `sync` form stays person-only. The SessionStart arm calls it;
  the AGENTS.md pointer block, README and docs now say a person runs `chock sync` to change what is enforced.
