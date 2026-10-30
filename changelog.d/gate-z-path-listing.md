- **A changed file is judged under its own name, however git would quote it.** The vendored gate runtime lists
  changed paths with `git diff -z` and keeps each name verbatim. A staged file whose name held ESC, a newline
  or a leading space was C-quoted or stripped, could not be read back, and was allowed unjudged. A listing git
  cannot produce, or one that is not NUL-terminated UTF-8, now refuses (exit 2) instead of judging an empty
  change. Paths reach git as literal pathspecs, never globs.
