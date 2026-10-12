- **`chock install --client goose|grok|antigravity` (untested in each client).** goose gets a manifest-less
  user plugin in `~/.agents/plugins/<name>/` with `hooks/hooks.json` and `on_failure: block` on every entry;
  grok gets a manifest-less plugin staged in `~/.chock/marketplace/grok/` for `grok plugin install <path>
  --trust`, and the install prints the enable step instead of editing grok's config; Antigravity gets
  `plugin.json` (`name`, `description`) plus `hooks.json` for `agy plugin install <path>`. Antigravity
  documents no plugin-root variable, so its hook commands name the installed folder by absolute path. The
  hook documents are agentseam's rendering; the folder layouts are chock's own record, with the vendor
  pages they were read from (`src/chock/plugin/data/stores/`), until agentseam's packaging data covers
  these agents. Labels come from agentseam's tier table, an ask gate is labelled not enforced where the
  client cannot prompt, and each client's warnings link its agentseam "evidence wanted" issue.
  `chock plugin build --format goose|grok|antigravity` builds the same packages per policy.
- **An unreadable Stop payload is refused in Antigravity's Stop grammar.** Antigravity names no event, so
  the refusal was rendered in the pre-tool grammar (`deny`), which an Antigravity Stop reads as allow. The
  runtime now answers an unreadable Stop with `continue`, from the vendor's required Stop field
  (`src/chock/data/shape_events.json`), kept only when agentseam parses it as a Stop. This also covers
  `chock sync`'s Antigravity Stop gate.
- **The guardrails toggle lookup reads goose's `working_dir` and Antigravity's `workspacePaths`.** It read
  only `cwd` and `workspace_roots`, so in those clients it looked from the hook's own working directory.
