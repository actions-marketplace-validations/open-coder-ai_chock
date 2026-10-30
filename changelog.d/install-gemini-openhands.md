- **`chock install --client openhands` (untested in OpenHands).** OpenHands gets `.plugin/plugin.json`
  plus `hooks/hooks.json`, staged in `~/.chock/marketplace/openhands/` for `openhands --plugin <path>`;
  OpenHands documents no plugin-root variable, so its hook commands name the folder by absolute path.
  chock's Claude package is not reused for OpenHands: its matchers never match OpenHands' `terminal` or
  `file_editor` and its runtime lets an OpenHands `rm -rf /` through (measured in
  `tests/test_plugin_install_targets_openhands.py`). Its warnings link its agentseam evidence issue.
  `chock plugin build --format openhands` builds the same package per policy.
- **An installed Antigravity `plugin.json` no longer carries `keywords`.** The per-member manifest
  `chock install` writes added an empty `keywords` list to every client's manifest, which Antigravity's
  closed manifest schema refuses; it is now kept only where the client's manifest has one.
