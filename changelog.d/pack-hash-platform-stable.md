- **A pack hashes the same on every platform and every checkout.** `compute_pack_hash` orders files by
  their posix-relative name as a string; sorting `Path` objects compared case-insensitively on Windows,
  so a pack holding `LICENSE` beside `hooks/` (catalog `base/java-security`, `base/review-like-a-red-team`)
  hashed differently there and `chock install` refused it. A local `--from <dir>` source with no `--ref`
  is now read as a clone would read it: a git checkout through `git archive` of its HEAD (uncommitted
  edits are left out and the commit is recorded as `source_commit`), a plain directory with its text
  files normalised to LF. Every git call chock runs for a fetch sets `core.autocrlf=false` and
  `core.eol=lf`, so a clone under Windows' usual `core.autocrlf=true` no longer flips a pack to CRLF.
  The `chock add` unpinned hint names the commit to pin instead of calling it "the default branch".
