- **`chock sync` wires Factory Droid, goose, OpenHands and Mistral Vibe.** The agent list comes from
  agentseam's adapter registry: every adapter is a valid `supported_agents` name (`factory-droid`, `goose`,
  `openhands`, `mistral-vibe`, `cline`), and every one whose hook config sits in the repository as JSON or TOML
  gets its hook entries and a `.chock/bin/<agent>.py` runtime. Vibe's rules go in one owned block in
  `.vibe/hooks.toml`; goose's go in `.agents/plugins/chock/hooks/hooks.json`. Each answers in its own
  grammar; none can prompt, so an ask is a refusal there and `CHOCK_CAN_ASK` is 0. Cline (one executable per
  event) and Junie and Kimi Code (home-directory config) are selectable but not yet wired.
- **Sync prints each wired agent's pre-tool row from agentseam's tier table**, with its basis and date, and
  says "Untested" for an agent chock has no live witness of.
- **agentseam is pinned to main commit bebbfa6** as a direct reference until its next release.
