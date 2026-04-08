---
name: tsc-check-on-completion
description: Run a TypeScript type check after completing code edits. Use when files are created or modified in this repo, before sending the final response, to catch compile errors with npx tsc --noEmit in code/ui.
---

# TSC Check On Completion

## Goal

Always run a TypeScript compile check after finishing edits and before giving the final user response.

## When to apply

- Any task that changes code in this repository.
- Especially when editing `.ts` or `.tsx` files.
- Skip only if no files were edited.

## Required command

From `code/ui`, run:

```bash
npx tsc --noEmit
```

## Workflow

1. Complete requested edits.
2. Run `npx tsc --noEmit` in `code/ui`.
3. If errors appear:
   - Fix the relevant issues.
   - Re-run `npx tsc --noEmit`.
4. Repeat until the command succeeds.
5. In the final response, state whether the type check passed.

## Notes

- Do not skip this check for speed.
- If the command fails due to environment/tooling issues unrelated to code changes, report that clearly and include the blocking error.
