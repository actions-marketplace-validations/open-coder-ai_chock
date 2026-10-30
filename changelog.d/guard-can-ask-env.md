- **Guards learn whether the client can prompt (`CHOCK_CAN_ASK`).** A guard run by a vendored hook
  runtime now sees `CHOCK_CAN_ASK=1` when the event that fired turns an ask (exit 3) into a prompt, and
  `0` when it turns it into a block or the runtime cannot name the event: 1 at Claude Code, Copilot and
  Gemini CLI pre-tool and Cursor `beforeShellExecution`; 0 at Cursor `preToolUse`, Codex, Devin, Grok,
  Tabnine and Windsurf. It is unset everywhere else (eval replay, direct calls) and never inherited from
  the caller's environment; a guard treats unset as "can ask". Opt-in: no guard reads it yet, so no
  verdict changes.
