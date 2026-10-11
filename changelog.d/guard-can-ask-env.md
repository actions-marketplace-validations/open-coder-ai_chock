- **Guards learn whether the client can prompt (`CHOCK_CAN_ASK`).** A guard run by a vendored hook
  runtime now sees `CHOCK_CAN_ASK=1` when that client's native pre-tool gate turns an ask (exit 3) into a
  prompt, and `0` when it turns it into a block: 1 for Claude Code, Copilot and Gemini CLI; 0 for Cursor,
  Codex, Devin, Grok, Tabnine, Windsurf and Antigravity. It is unset everywhere else (eval replay, direct
  calls) and never inherited from the caller's environment. Opt-in: no guard reads it yet, so no verdict
  changes.
