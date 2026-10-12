- **`chock install --client kimi-code|factory-droid` (untested in each client).** Kimi Code gets
  `kimi.plugin.json` (`name`, `version`, `description`, `skills: ./skills/`) whose `hooks` array carries
  the hook rules, staged in `~/.chock/marketplace/kimi-code/`; Kimi installs plugins from its TUI only, so
  chock prints the `/plugins install <path>` and `/reload` steps and runs nothing. Its hooks reach the
  scripts by `${KIMI_PLUGIN_ROOT}`, the variable the vendor documents, and carry chock's 45 s `timeout`
  (Kimi's default is 30 s, below the engine's own budget). Factory Droid gets `.factory-plugin/plugin.json`
  plus `hooks/hooks.json` (`${DROID_PLUGIN_ROOT}`), wrapped in a local marketplace
  `~/.chock/marketplace/factory-droid/chock-local/` with `.factory-plugin/marketplace.json`, for
  `droid plugin marketplace add <path>` then `droid plugin install <plugin>@chock-local --scope project`
  (run with `--apply` where `droid` is on PATH). Nothing is published. Labels come from agentseam's tier
  table: an ask is not enforced in either client. Each client's warnings link its agentseam evidence
  issue (#135, #184). `chock plugin build --format kimi|droid` builds the same packages per policy.
