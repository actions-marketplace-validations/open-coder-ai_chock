- **The write gate reads an `apply_patch` text the way Codex does, so nothing the patch writes escapes it.**
  The patch reader cut the text at the first `*** End Patch` anywhere, even inside an added line, so the rest
  went unjudged. It matched headers without Codex's whitespace trimming: an indented `*** Add File:` after a
  delete or an add was not seen, so its file was judged under the wrong path or not at all. It placed hunks
  only by exact or trailing-space match, so a hunk Codex places by trimmed or ASCII-punctuation match left
  the file unjudged. It also read paths from the repository root rather than the agent's working directory,
  and read each file from disk even when an earlier file in the same patch had already written it. Blocked
  content on any of these paths was allowed (measured with Codex CLI 0.162.1's `apply_patch`: 12 payloads
  that Codex writes were allowed; all are now refused). The reader now ports Codex's own parser and hunk
  placement. A patch Codex would not parse is refused rather than guessed at.
