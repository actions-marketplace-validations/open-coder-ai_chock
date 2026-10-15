- **`chock gateway` honours `chock stop`.** While a stop reaches the MCP client, every `tools/call`
  is refused with `stopped: <reason>` and logged (`block`, reason `stopped`, policy `chock-stop`);
  `initialize` and `tools/list` still pass. A stop file that cannot be read refuses.
