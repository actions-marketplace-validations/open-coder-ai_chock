- **`chock gateway` writes the decision log.** Every judged `tools/call` gets a line in
  `<repo>/.chock/log/gate-events.jsonl` with the fields every hook writes: one `allow` line per
  forwarded call (no policy), one `block` line per refusing policy (`gate-block`, `gate-ask`, or
  `fault` for a gate that cannot run), `target` `<server>/<tool>` redacted and capped at 128
  characters, and never the call's arguments. A gate that raises now refuses the call (`fault`)
  instead of stopping the gateway. A log that cannot be written changes no verdict.
