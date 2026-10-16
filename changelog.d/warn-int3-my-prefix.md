- **`chock validate` no longer warns on the `my-` prefix `chock new` adds.** INT-3 (verb-first
  ids) took `my` as the first word of every policy scaffolded outside a catalog, so
  `my-block-marker` warned "does not start with a verb". It now reads the word after the
  prefix: `my-block-marker` passes, `my-tf-destroy` still warns.
