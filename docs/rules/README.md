# Rules

Rules are ambient guidance that applies to all work in a repo.

## Where rules live

- `.agents/policies/INDEX.md` — the compiled always-on rules
- `AGENTS.md` — a managed pointer block that sends the agent to `INDEX.md`
- `.agents/policies/<rule-id>/` — source rule folder

## Rule folder contents

- `manifest.yaml` — manifest with `artifact: rule`
- `evals/suite.yaml` — eval cases

## How to write a rule

1. Keep the rule text to two lines or less.
2. Put examples and rationale in the policy's own folder if needed.
3. Validate with the Chock validator.

## Compiling into INDEX.md

The framework compiles selected rules into `.agents/policies/INDEX.md`, and keeps a short
pointer block in `AGENTS.md` between the `chock:pointer` markers. Do not hand-edit either;
edit the source rule folder and run `chock sync`. `chock check --only index` verifies both
are fresh.
