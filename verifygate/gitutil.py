"""The small amount of git this needs, with the sharp edges filed off.

Two habits are enforced here rather than left to the caller:

* ``git add -A`` is never used.  Working copies get shared - with another
  agent, another session, a person - and a blanket add sweeps someone else's
  unfinished work into your commit.  Paths are always named.
* A run never starts on a branch that deploys.  Somewhere there is a repository
  where pushing to ``main`` publishes a website within seconds, and the cost of
  finding that out during an automated run is a broken site.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Sequence, Tuple


class GitError(RuntimeError):
    pass


def run(args: Sequence[str], cwd: str, check: bool = True, timeout: int = 120) -> str:
    p = subprocess.run(
        ["git"] + list(args), cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if check and p.returncode != 0:
        raise GitError("git {}: {}".format(" ".join(args), (p.stderr or p.stdout).strip()))
    return p.stdout


def is_repo(cwd: str) -> bool:
    try:
        return run(["rev-parse", "--is-inside-work-tree"], cwd).strip() == "true"
    except (GitError, OSError):
        return False


def current_branch(cwd: str) -> str:
    return run(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def head(cwd: str) -> str:
    return run(["rev-parse", "HEAD"], cwd).strip()


def toplevel(cwd: str) -> str:
    return run(["rev-parse", "--show-toplevel"], cwd).strip()


def is_clean(cwd: str) -> bool:
    return run(["status", "--porcelain"], cwd).strip() == ""


def status_paths(cwd: str) -> List[Tuple[str, str]]:
    """[(status, path)] for every changed or untracked path."""
    out = []
    for line in run(["status", "--porcelain"], cwd).splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2].strip() or "??", line[3:].strip()
        if " -> " in path:                     # renames
            path = path.split(" -> ", 1)[1]
        out.append((code, path.strip('"')))
    return out


def diff(cwd: str, ref: Optional[str] = None, paths: Optional[Sequence[str]] = None) -> str:
    args = ["diff"]
    if ref:
        args.append(ref)
    args += ["--no-color"]
    if paths:
        args += ["--"] + list(paths)
    return run(args, cwd, check=False)


def diff_numstat(cwd: str, ref: Optional[str] = None) -> List[Tuple[int, int, str]]:
    """[(insertions, deletions, path)]. Binary files report -1, -1."""
    args = ["diff", "--numstat"]
    if ref:
        args.append(ref)
    out = []
    for line in run(args, cwd, check=False).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        a, d, path = parts
        out.append((-1 if a == "-" else int(a), -1 if d == "-" else int(d), path.strip()))
    return out


def file_at(cwd: str, ref: str, path: str) -> Optional[str]:
    """Contents of ``path`` at ``ref``, or None if it did not exist there."""
    p = subprocess.run(
        ["git", "show", "{}:{}".format(ref, path)], cwd=cwd,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return None if p.returncode != 0 else p.stdout


def add_paths(cwd: str, paths: Sequence[str]) -> None:
    """Stage exactly these paths. There is deliberately no 'add everything'."""
    if not paths:
        return
    run(["add", "--"] + list(paths), cwd)


def stash_push(cwd: str, message: str) -> bool:
    """Set the working tree aside. True if something was actually stashed."""
    before = run(["stash", "list"], cwd).count("\n")
    run(["stash", "push", "--include-untracked", "-m", message], cwd, check=False)
    return run(["stash", "list"], cwd).count("\n") > before


def stash_pop(cwd: str) -> None:
    run(["stash", "pop"], cwd, check=False)


DEPLOYING_BRANCHES = ("main", "master", "production", "prod", "release")


def refuses_to_run_here(cwd: str, allow: Sequence[str] = ()) -> Optional[str]:
    """Why this working copy must not be worked in directly, or None."""
    if not is_repo(cwd):
        return "not a git repository: {}".format(cwd)
    branch = current_branch(cwd)
    if branch in DEPLOYING_BRANCHES and branch not in allow:
        return (
            "on branch '{}'. Work is not done on a branch that deploys.\n"
            "  Check out a working branch first, or pass --allow-branch {} if this\n"
            "  repository really does not publish from it.".format(branch, branch)
        )
    return None


def worktree_add(repo: str, path: str, branch: str, base: str) -> None:
    run(["worktree", "add", "-b", branch, path, base], repo)


def worktree_remove(repo: str, path: str, force: bool = True) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(path)
    run(args, repo, check=False)


def worktree_list(repo: str) -> List[str]:
    out = []
    for line in run(["worktree", "list", "--porcelain"], repo, check=False).splitlines():
        if line.startswith("worktree "):
            out.append(line[len("worktree "):].strip())
    return out


def rel_to_top(cwd: str, path: str) -> str:
    top = os.path.abspath(toplevel(cwd))
    ap = os.path.abspath(path)
    return os.path.relpath(ap, top).replace("\\", "/")
