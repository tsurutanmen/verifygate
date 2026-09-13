# verifygate

**Delegate work to a coding agent only when a machine can tell you it was done.**

```
pip install git+https://github.com/tsurutanmen/verifygate
```

```
verifygate run order.json
```

```
run i18n-20260913-203914
  baseline  failed, as it should in 0.1s
  verify    PASS in 0.1s
  diff      +2 / -1 across 1 file(s)

guards
  [ok  ] vacuous        check was red before the work, as it should be
  [ok  ] head_moved     HEAD unchanged
  [FAIL] comment_stash  1 fragment(s) left code and appeared in comments
         app.js: string '使い方を見る'
         This is how a presence check is satisfied without the work.
  [FAIL] must_keep      1 of 1 required string(s) not in real code
  [ok  ] diff_shape     diff shape matches a 'add' job (+2 / -1)
  [ok  ] outside_cwd    all changes inside the scope

NOT ACCEPTED. Nothing has been committed.
```

The verification command passed. The work was not done. That gap is what this
tool is about.

## The one rule

**An order without a verification command is rejected.** Not warned about —
rejected, before anything runs.

```
$ verifygate check order.json
rejected.

order.json: no verify command.

  A work order without a verification command is not accepted.
  If you cannot write a command that tells you the job was done,
  the job is not ready to delegate - do it yourself, or find the
  check first.
```

This is not bureaucracy. Whether you can write that command *is* the test of
whether the job can be handed over at all. If a machine cannot tell you the
work was done, you will read every line of the result yourself, and reading
someone else's code takes longer than writing your own. The question "what
command would prove this?" is the same question as "should I delegate this?"

| | how you would check it | verdict |
|---|---|---|
| remove every decorative emoji from 83 files | count them, and count what must survive | delegate |
| generate 240 quiz items | parse the JSON, check the answer index, check for duplicates | delegate |
| wrap UI strings in a translation call | the call appears, and the original text is still in code | delegate |
| decide which paragraph to cut | you have to read it | keep |
| make the page feel less generic | there is no command | keep |
| click through the SDK flow | you cannot run it | keep |

## What the check cannot see

An exit code of zero tells you one thing: that command exited zero. Six guards
ask what it does not. Each one is here because it happened.

### vacuous — the check was already green

If the verification command passes *before* the work starts, passing after it
proves nothing. Either the job was already done, or the check does not measure
it. `verifygate` runs the check on the untouched starting state first, and
fails the run if it was green both times.

This is the most commonly skipped step and the one that invalidates the most
results. A control that cannot come out differently is not a control.

### comment_stash — the text moved into a comment

Asked to restructure some UI while keeping the wording, an agent once parked
the deleted fragments in a block comment headed `source markers for former
fragments`, and the "is the wording still there?" check went green across
twenty-three files. Four of them reached production before anyone noticed.

`verifygate` strips comments before comparing, and separately looks for text
that left the code and reappeared in a comment in the same file — by whole line
and by quoted string, because it is usually a quoted string that gets parked.

The same check is available on its own, to put inside your own verify command:

```
verifygate guard --keep "使い方を見る" --keep "保存する" -- src/*.js
```

### must_keep — what had to survive

Removal jobs need a list of things that must *not* be removed. A check that
says "the emoji are gone" is satisfied by deleting the close button, because
`✕` is in the emoji range. Declare what must remain, and it is checked in real
code — a comment does not count.

```json
"must_keep": ["✕", "❤", "保存する"]
```

### diff_shape — the diff contradicts the job

An adding job that deletes more than it adds is a regression, and you want to
know before you start reading. Declare the direction with `"expect": "add"` or
`"expect": "remove"`.

### head_moved — the agent committed

If HEAD moved during the run, the diff you are about to review is not the
change. The order forbids committing; this notices when it happened anyway.

### outside_cwd — files written out of scope

Anything changed outside the directory the job was scoped to.

## Isolation

Each run gets **its own git worktree on its own branch**. Three consequences:

- the working copy you are using is untouched, so an agent and a person can
  work at the same time
- two runs cannot collide, so write-heavy jobs can go in parallel — without
  this you have to serialise them
- nothing lands anywhere by accident; `accept` commits on the run's branch and
  a person merges

A run **refuses to start on `main`, `master`, `production`, `prod` or
`release`**. Somewhere there is a repository where pushing to `main` publishes
a website within seconds. Use `--allow-branch main` if yours is not one.

`git add -A` is never used; `accept` stages exactly the paths the run changed.
Working copies get shared, and a blanket add sweeps someone else's unfinished
work into your commit.

## The order

```json
{
  "id": "i18n-en-1",
  "objective": "Wrap the UI strings in t(). Do not change any Japanese wording.",
  "cwd": "C:/work/portal-site",
  "verify": "php -l includes/i18n.php && python check_i18n.py",
  "notes": "php is at C:/tools/php/php.exe. There is no database locally.",
  "must_keep": ["使い方を見る", "保存する"],
  "expect": "add",
  "forbid": ["Do not add npm packages"],
  "model": "gpt-5.6-luna",
  "effort": "medium",
  "timeout_sec": 2400,
  "web": false
}
```

Required: `id`, `objective`, `cwd`, `verify`. Everything else is optional.
Write paths with forward slashes — a JSON file full of doubled backslashes
gets mangled by whatever sits between you and the agent.

Unknown fields are rejected rather than ignored, so `"verfy"` is caught at load
time instead of silently disabling the one rule.

Every order carries house rules the agent is told about up front, including
*do not move text into comments to satisfy the check*. Guards are the backstop,
not the first line — say it first, then check.

See `verifygate check order.json --print-order` for the exact text sent.

## Commands

```
verifygate check   order.json     is this order acceptable at all
verifygate run     order.json     baseline, delegate, verify, guard
verifygate run     order.json --dry-run       baseline only, do not delegate
verifygate list                   runs on record
verifygate show    <run-id> --diff --output
verifygate accept  <run-id>       commit it; refuses anything that failed
verifygate discard <run-id>       throw the branch and worktree away
verifygate guard   --keep STR -- files
```

Exit codes: `0` passed, `1` held, `2` the order or the repository was refused.

## The implementer

By default `verifygate` invokes the **Codex CLI** (`codex exec`), passing the
order on stdin. Any command works:

```
verifygate run order.json --implementer "claude -p"
verifygate run order.json --implementer "python my_agent.py"
```

The implementer is a command that reads an order on stdin and edits files in
its working directory. That is the whole contract — which is why the tests can
use a three-line script for the honest agent, the lazy one, and the one that
games the check.

## Before you delegate, run your own check

Run the verification command by hand on the current state first. A check that
is broken looks exactly like an agent that failed, and you will spend the
afternoon debugging the wrong one. `--dry-run` does this for you, and tells you
whether the check is red on the starting state.

One specific trap: on Windows, a PowerShell script with non-ASCII comments and
no BOM is read as the legacy code page. The same script then returns a
different number. That once turned 343 into 5466.

## Install

```
pip install git+https://github.com/tsurutanmen/verifygate
```

Python 3.9+. No dependencies beyond the standard library and `git` on PATH.

## Claude Code skill

`skill/verifygate/SKILL.md` teaches Claude Code when to reach for this. Copy it
to `~/.claude/skills/verifygate/`.

## Limits

- Comment stripping is a scanner, not a parser. It tracks string literals well
  enough that a URL is not mistaken for a comment, and it knows the syntax for
  about forty extensions, but it will not be right about every corner of every
  grammar. `comments.strip(..., keep_strings=False)` gives the stricter
  reading; run both if it matters.
- Guards look at what changed. A job that changes nothing passes every guard
  and fails the verification command, which is the right outcome by a slightly
  indirect route.
- `comment_stash` compares against the run's base commit. It sees the agent's
  work, not what you had uncommitted before it started.
- There is no sandbox here. `verifygate` isolates *the repository*, not the
  machine. Sandboxing is the agent's job — and worth confirming, since at least
  one CLI has silently ignored its own sandbox setting on Windows.

## Related

[strictnull](https://github.com/tsurutanmen/strictnull) — build the control
before you compare. The same idea one floor down: a comparison without a
control that could have come out differently is not a measurement.

## License

MIT
