- **Installed content is what `verify` says it is.** `chock add` and `chock verify` refuse a pack that
  ships `__pycache__` or `.pyc`/`.pyo` (build artifacts, never catalog content), and policy scripts now
  run with `PYTHONDONTWRITEBYTECODE=1`, so running a gate no longer leaves bytecode in the pack. Each
  vendored runtime entry now hashes the shared runtime's bytes before executing them and compares that to
  its pin, instead of trusting a digest the file declares about itself. The agent-event runner exits 2 on
  stdin that is not UTF-8 instead of judging text with replacement characters. Run `chock sync` to
  refresh `.chock/bin`.
