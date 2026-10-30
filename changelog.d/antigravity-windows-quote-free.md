- **Antigravity on Windows: plugin hook commands are now quote-free, so cmd.exe hands them to git intact.**
  Antigravity IDE on Windows runs a hook `command` through cmd.exe and passes each `"` on as `\"`, so the
  single-quoted git alias split (`unknown option: -f`) and a double-quoted one did too (a maintainer's witness
  run, 2026-10-18; agentseam 683f95b records the cmd.exe runner). Built on Windows, the Antigravity plugin now
  runs `git -c alias.chock-sh=!<refusal> chock-sh <launcher> <args>` with no quote or space in any argument:
  words split by `${IFS}` in git's sh, every cmd.exe operator caret-escaped, and the missing-launcher refusal
  (exit 2) kept. A plugin folder whose path holds a space, quote or cmd.exe metacharacter is refused at install
  with an error naming the path. The fact is store data (`windows_hook_command: quote_free`); every other
  client, and every non-Windows build, is byte-identical. Not witnessed yet: the built command has not been run
  in Antigravity.
