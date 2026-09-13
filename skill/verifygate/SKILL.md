---
name: verifygate
description: Gate delegated coding work behind a check that can actually fail. Use whenever you are about to hand a task to another coding agent (Codex, a subagent, a teammate), or are writing the verification command for one - it refuses orders with no check, runs the check on the starting state first, and catches the ways a green check hides undone work.
---

# verifygate

Delegate only what a machine can confirm. `pip install git+https://github.com/tsurutanmen/verifygate`

## When to reach for this

- You are about to hand a coding task to another agent and are writing the instructions.
- You are writing a verification command, a "check the change landed" script, or a CI gate.
- Someone reports that a check passed but the work is not actually there.
- You are about to run an agent directly in a working copy someone else is using.

## The rule that does the work

**No verification command, no delegation.** `verifygate check order.json` exits 2
on an order with no `verify` field.

Before writing the order, answer: *what command, run afterwards, would tell me
this was done?* If you cannot answer it, the task is not delegable yet. Either
find the check first, or do the work yourself. Do not delegate and plan to read
the result — reading someone else's code is slower than writing your own.

## Writing the check

Three failure modes, in the order they bite:

1. **The check was already green.** Then passing means nothing. Always run it
   on the starting state first (`verifygate run order.json --dry-run` does
   this). If it passes there, it does not measure the job.
2. **The check counts, so the agent makes the count right.** "Fewer than N
   direct colour values" is satisfied by changing what the colours mean.
   Measure the property you care about, not a proxy for it.
3. **The check asks "is this string present?"** A comment contains the string.
   Strip comments before comparing, or use `verifygate guard --keep STR -- files`.

For removal jobs, always declare what must survive. A check that says "the
emoji are gone" is satisfied by deleting the close button, because `✕` is in
the emoji range.

## The order

```json
{
  "id": "short-name",
  "objective": "What to do. No ambiguity.",
  "cwd": "C:/path/to/repo",
  "verify": "pytest -q tests/test_thing.py",
  "must_keep": ["text that must still be in real code"],
  "expect": "add",
  "notes": "Where the interpreter lives, what cannot be run locally.",
  "forbid": ["job-specific prohibitions"]
}
```

Forward slashes in paths. Unknown fields are rejected, not ignored.

## Running it

```
verifygate check order.json --print-order    # see exactly what the agent gets
verifygate run   order.json --dry-run        # baseline only: can the check fail?
verifygate run   order.json                  # baseline, delegate, verify, guard
verifygate show  <run-id> --diff
verifygate accept <run-id>                   # refuses anything that failed
```

Default implementer is the Codex CLI. `--implementer "claude -p"` or any
command that reads an order on stdin and edits files in its working directory.

Each run gets its own git worktree and branch, so the working copy stays clean
and parallel runs cannot collide. Runs refuse to start on `main`/`master`/
`production` — some repositories deploy from a push.

## Reading the result

`accept` refuses anything that failed, so the question is only ever *why* it is
held:

| guard | what it means |
|---|---|
| `vacuous` | the check was green before the work; it proves nothing |
| `comment_stash` | text left the code and reappeared in a comment |
| `must_keep` | something declared to preserve is gone, or is only in a comment |
| `head_moved` | the agent committed; the diff is not the change |
| `diff_shape` | an adding job mostly deleted |
| `outside_cwd` | files written outside the scope |

`skipped` is not `ok`. It means the guard could not look, and it says why.

## Two habits worth keeping even without the tool

- **Run the verification script yourself before delegating.** A broken check
  looks exactly like a failed agent.
- **Never `git add -A`** in a shared working copy. Name the paths.
