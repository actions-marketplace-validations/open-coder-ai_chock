- **Added and removed lines are read from the diff's structure, not by prefix.** The vendored gate runtime
  dropped every added line whose text began with `++` (and every removed line beginning with `--`) as if it
  were a file header, and `str.splitlines` cut a line at a form feed or Unicode separator so its tail lost
  its `+`; blocked content on such a line was allowed. File headers are now read only before a file's first
  hunk, hunk lines are classified by their first character and bounded by the hunk's counts, and a diff that
  git cannot produce or that does not parse refuses (exit 2). The diff is read without colour, external diff
  drivers or textconv. `chock review require` and the gate-log check list paths with `-z`, so a name with a
  space, a newline or non-ASCII is matched verbatim.
