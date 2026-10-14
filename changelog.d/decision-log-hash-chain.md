- **The decision log is hash-chained.** Every line on every route carries `seq` and `prev`, the
  sha256 of the line before it; the first line after a rotation names the rotated file's last.
  Writers take the log's lock, so hooks running at once never fork the chain; a line that cannot be
  chained is still written, marked `unchained`, and no verdict changes. `chock status --verify-log`
  reports the first break (file, line, expected and found) and exits 1; `--head <seq>:<sha256>`
  confirms a head kept earlier. `chock witness export` carries each log's head, and a person's
  git-hook overrides without the approver. It shows tampering to someone who kept a head; it does not
  stop a local admin from rewriting the whole file.
