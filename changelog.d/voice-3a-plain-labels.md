- **Policy labels, install warnings and witness notes now use short plain sentences (VOICE-3a).** The grade text
  that `chock install` prints and the catalog's registry reads no longer chains clauses with semicolons, and no
  longer says "judged" or "fails open". A gate that runs only at turn end now reads "blocks at turn end only. It
  does not check a file write when it happens". Devin's label and the labels of clients graded from agentseam's
  tier table say "a hook error lets the action through" where they said "fails open" or "fail mode open". No
  label claims more than before, and every caveat is kept. Code that matches the old wording, such as the
  catalog's `tools/label_honesty.py`, needs the new text.
