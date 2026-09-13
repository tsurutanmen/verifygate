"""What the verification command cannot see.

A command that exits zero tells you one thing: that command exited zero.  These
guards ask the questions it does not.  Each one exists because the thing it
looks for actually happened and the check stayed green.

  vacuous       The check passed before any work was done, so passing after it
                proves nothing.  A control that cannot come out differently is
                not a control.
  comment_stash Text vanished from code and reappeared in a comment, which is
                how a "the wording is still there" check is satisfied without
                the wording being there.
  must_keep     Something the job was told to preserve is gone from real code -
                or is only in a comment, which is the same thing.
  head_moved    The implementer committed, so the diff you are about to review
                is not the change.
  diff_shape    A job described as adding produced more deletions than
                insertions.
  outside_cwd   Files were written outside the directory the job was scoped to.

A guard reports one of: ok (looked, found nothing), fail (found it), or
skipped (could not look, and says why).  Nothing silently passes for want of
information.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import comments, gitutil


@dataclass
class Finding:
    name: str
    status: str                 # "ok" | "fail" | "skipped"
    summary: str
    detail: List[str]

    @property
    def failed(self) -> bool:
        return self.status == "fail"

    def render(self) -> str:
        mark = {"ok": "ok  ", "fail": "FAIL", "skipped": "skip"}[self.status]
        lines = ["  [{}] {:<14} {}".format(mark, self.name, self.summary)]
        lines += ["         " + d for d in self.detail[:12]]
        if len(self.detail) > 12:
            lines.append("         ... {} more".format(len(self.detail) - 12))
        return "\n".join(lines)


# --------------------------------------------------------------------- guards
def vacuous(baseline_passed: Optional[bool], after_passed: bool) -> Finding:
    """The check has to be able to fail, and has to have failed before."""
    if baseline_passed is None:
        return Finding("vacuous", "skipped",
                       "baseline not run, so it is unknown whether this check can fail", [])
    if baseline_passed and after_passed:
        return Finding(
            "vacuous", "fail",
            "the check already passed before the work started", [
                "Passing afterwards therefore shows nothing about the work.",
                "Either the job was already done, or the check does not measure it.",
                "Write a check that is red on the starting state.",
            ])
    if baseline_passed and not after_passed:
        return Finding("vacuous", "ok", "check was green before and is red now", [])
    return Finding("vacuous", "ok", "check was red before the work, as it should be", [])


def comment_stash(cwd: str, ref: str, changed: Sequence[str],
                  min_len: int = 8) -> Finding:
    """Text removed from code that turns up in a comment in the same file."""
    hits: List[str] = []
    looked = 0
    for path in changed:
        before = gitutil.file_at(cwd, ref, path)
        if before is None:
            continue
        full = os.path.join(cwd, path)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                after = f.read()
        except OSError:
            continue
        looked += 1

        before_code = comments.strip(before, path)
        after_code = comments.strip(after, path)

        # whole lines that vanished from code and turn up in a comment
        candidates = [(f, "line") for f in _fragments(before_code, min_len)]
        # and the quoted text inside them, which is what usually gets parked
        before_lits = comments.literals(before, path)
        after_lits = set(comments.literals(after, path))
        candidates += [(s, "string") for s in before_lits if s not in after_lits]

        for frag, kind in candidates:
            if frag in after_code:
                continue                        # still in real code, fine
            if comments.count_in_comments(after, frag, path) > 0:
                hits.append("{}: {} {!r}".format(path, kind, _clip(frag)))
                if len(hits) >= 40:
                    break
        if len(hits) >= 40:
            break

    if not looked:
        return Finding("comment_stash", "skipped", "no text files to compare", [])
    if hits:
        return Finding("comment_stash", "fail",
                       "{} fragment(s) left code and appeared in comments".format(len(hits)),
                       hits + ["This is how a presence check is satisfied without the work."])
    return Finding("comment_stash", "ok",
                   "nothing moved from code into comments ({} file(s) compared)".format(looked), [])


def must_keep(cwd: str, needles: Sequence[str], changed: Sequence[str]) -> Finding:
    """Strings the order said to preserve must survive in code, not in comments."""
    if not needles:
        return Finding("must_keep", "skipped", "nothing declared to preserve", [])

    files = [p for p in changed if os.path.isfile(os.path.join(cwd, p))]
    if not files:
        return Finding("must_keep", "skipped", "no changed files to search", [])

    texts: Dict[str, str] = {}
    for p in files:
        try:
            with open(os.path.join(cwd, p), "r", encoding="utf-8", errors="replace") as f:
                texts[p] = f.read()
        except OSError:
            continue

    lost, hidden = [], []
    for s in needles:
        in_code = sum(comments.count_in_code(t, s, p) for p, t in texts.items())
        in_comment = sum(comments.count_in_comments(t, s, p) for p, t in texts.items())
        if in_code == 0 and in_comment > 0:
            hidden.append("{!r} survives only inside a comment".format(_clip(s)))
        elif in_code == 0:
            lost.append("{!r} is gone from the changed files".format(_clip(s)))

    if lost or hidden:
        return Finding("must_keep", "fail",
                       "{} of {} required string(s) not in real code".format(
                           len(lost) + len(hidden), len(needles)),
                       hidden + lost)
    return Finding("must_keep", "ok",
                   "all {} required string(s) present in code".format(len(needles)), [])


def head_moved(cwd: str, before_head: str) -> Finding:
    try:
        now = gitutil.head(cwd)
    except gitutil.GitError as e:
        return Finding("head_moved", "skipped", "could not read HEAD: {}".format(e), [])
    if now != before_head:
        return Finding("head_moved", "fail", "HEAD moved during the run", [
            "was {}".format(before_head[:12]),
            "now {}".format(now[:12]),
            "The implementer committed. The diff under review is not the change.",
        ])
    return Finding("head_moved", "ok", "HEAD unchanged", [])


def diff_shape(expect: str, insertions: int, deletions: int) -> Finding:
    if not expect:
        return Finding("diff_shape", "skipped", "no expected direction declared", [])
    if expect == "add" and deletions > insertions:
        return Finding("diff_shape", "fail",
                       "an adding job deleted more than it added (+{} / -{})".format(
                           insertions, deletions),
                       ["Check for a regression before reading anything else."])
    if expect == "remove" and insertions > deletions:
        return Finding("diff_shape", "fail",
                       "a removing job added more than it removed (+{} / -{})".format(
                           insertions, deletions), [])
    return Finding("diff_shape", "ok",
                   "diff shape matches a '{}' job (+{} / -{})".format(expect, insertions, deletions), [])


def outside_cwd(repo_root: str, scope: str, changed_abs: Sequence[str]) -> Finding:
    scope_abs = os.path.abspath(scope)
    stray = [p for p in changed_abs
             if os.path.commonpath([scope_abs, os.path.abspath(p)]) != scope_abs]
    if stray:
        return Finding("outside_cwd", "fail",
                       "{} file(s) changed outside the scope".format(len(stray)),
                       [os.path.relpath(p, repo_root).replace("\\", "/") for p in stray])
    return Finding("outside_cwd", "ok", "all changes inside the scope", [])


# --------------------------------------------------------------------- helper
def _fragments(code: str, min_len: int) -> List[str]:
    """Meaty single lines of code, used as the unit that can go missing."""
    seen, out = set(), []
    for raw in code.splitlines():
        s = raw.strip()
        if len(s) < min_len or s in seen:
            continue
        if not any(c.isalnum() for c in s):
            continue
        seen.add(s)
        out.append(s)
        if len(out) > 4000:
            break
    return out


def _clip(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "..."
