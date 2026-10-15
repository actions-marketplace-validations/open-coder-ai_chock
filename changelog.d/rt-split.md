- **One shared runtime beside the per-agent entries.** `chock sync` writes `.chock/bin/_chock_runtime.py`, the
  stdlib-only guard logic every `.chock/bin/<agent>.py` loads from its own folder, and each entry shrinks to
  its vendor's adapter and dispatch. Plugin packages (`chock plugin build`, `chock install`) ship it beside
  their entry. The module is bytecode-cached, so the hook no longer recompiles about 3,400 lines on every
  call. An entry refuses every call, in its client's own grammar, when the shared runtime is missing,
  unreadable, fails to import or carries another version's digest; it never allows. Verdicts are unchanged.
