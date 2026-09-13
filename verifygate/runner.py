"""Run the order, judge the result, and let nothing through that failed.

The shape of a run:

  1. refuse to start on a branch that deploys
  2. take a disposable worktree on a new branch, so two runs cannot collide
     and the working copy you were using is untouched
  3. run the verification command on the untouched starting state - the
     baseline.  A check that is already green is not a check
  4. hand the order to the implementer
  5. run the verification command again
  6. run the guards, which ask what the command cannot
  7. record everything; merge only on request, and only if it passed

Step 3 is the one people skip.  Without it you cannot tell "the work was done"
from "this check was never able to fail".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import gitutil, guards
from .guards import Finding
from .spec import Spec


@dataclass
class CommandResult:
    ok: bool
    code: int
    seconds: float
    stdout: str
    stderr: str


@dataclass
class RunResult:
    run_id: str
    spec: Spec
    branch: str
    worktree: str
    base_ref: str
    baseline: Optional[CommandResult]
    after: Optional[CommandResult]
    findings: List[Finding] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    changed: List[str] = field(default_factory=list)
    implementer: Optional[CommandResult] = None
    error: str = ""

    @property
    def verified(self) -> bool:
        return bool(self.after and self.after.ok)

    @property
    def guards_passed(self) -> bool:
        return not any(f.failed for f in self.findings)

    @property
    def passed(self) -> bool:
        return self.verified and self.guards_passed and not self.error

    def to_dict(self) -> Dict:
        def cr(c):
            if c is None:
                return None
            return {"ok": c.ok, "code": c.code, "seconds": round(c.seconds, 2),
                    "stdout": c.stdout[-20000:], "stderr": c.stderr[-20000:]}
        return {
            "run_id": self.run_id, "spec": self.spec.to_dict(), "branch": self.branch,
            "worktree": self.worktree, "base_ref": self.base_ref,
            "baseline": cr(self.baseline), "after": cr(self.after),
            "implementer": cr(self.implementer),
            "insertions": self.insertions, "deletions": self.deletions,
            "changed": self.changed, "error": self.error,
            "verified": self.verified, "guards_passed": self.guards_passed,
            "passed": self.passed,
            "findings": [{"name": f.name, "status": f.status, "summary": f.summary,
                          "detail": f.detail} for f in self.findings],
        }


def shell(cmd: str, cwd: str, timeout: int = 1800,
          env: Optional[Dict[str, str]] = None) -> CommandResult:
    """Run a command line as the user's shell would.

    ``shell=True`` is used deliberately and only here: the verification command
    is written by the person delegating the work, in the same breath as the
    order, and is expected to contain pipes and redirection.  It is never built
    from the implementer's output.
    """
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, **(env or {})})
        return CommandResult(p.returncode == 0, p.returncode, time.time() - t0,
                             p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return CommandResult(False, -1, time.time() - t0, "",
                             "timed out after {}s".format(timeout))


def codex_command(spec: Spec, prompt_file: str) -> List[str]:
    """The default implementer: the Codex CLI, in exec mode."""
    cmd = ["codex", "exec", "--skip-git-repo-check"]
    if spec.model:
        cmd += ["-m", spec.model]
    # write access and web search sit behind feature flags on some platforms;
    # asking for them explicitly is harmless where they are already on
    cmd += ["--enable", "experimental_windows_sandbox"]
    if spec.web:
        cmd += ["--enable", "web_search_request"]
    cmd += ["-"]
    return cmd


class Runner:
    def __init__(self, store: str, implementer: Optional[Sequence[str]] = None,
                 allow_branch: Sequence[str] = (), keep_worktree: bool = False):
        self.store = store
        self.implementer = list(implementer) if implementer else None
        self.allow_branch = tuple(allow_branch)
        self.keep_worktree = keep_worktree
        os.makedirs(self.store, exist_ok=True)

    # ------------------------------------------------------------------ run
    def run(self, spec: Spec, dry_run: bool = False) -> RunResult:
        repo = gitutil.toplevel(spec.cwd)
        why = gitutil.refuses_to_run_here(spec.cwd, allow=self.allow_branch)
        if why:
            raise RuntimeError(why)

        base = spec.base or gitutil.current_branch(spec.cwd)
        base_ref = gitutil.head(spec.cwd)
        run_id = "{}-{}".format(spec.id, time.strftime("%Y%m%d-%H%M%S"))
        branch = "vg/{}".format(run_id)
        wt = os.path.join(self.store, run_id, "tree")
        os.makedirs(os.path.dirname(wt), exist_ok=True)

        gitutil.worktree_add(repo, wt, branch, base)
        # the job's directory, relative to the repo, inside the fresh worktree
        rel_scope = gitutil.rel_to_top(spec.cwd, spec.cwd)
        scope = wt if rel_scope in (".", "") else os.path.join(wt, rel_scope)

        res = RunResult(run_id=run_id, spec=spec, branch=branch, worktree=wt,
                        base_ref=base_ref, baseline=None, after=None)
        try:
            # 3. the baseline. A check that is already green measures nothing.
            res.baseline = shell(spec.verify, scope, timeout=spec.timeout_sec)

            if dry_run:
                res.error = "dry run: implementer not invoked"
                return self._finish(res, repo, scope, base_ref, skip_guards=True)

            # 4. hand it over
            prompt = spec.prompt()
            pf = os.path.join(self.store, run_id, "order.md")
            with open(pf, "w", encoding="utf-8") as f:
                f.write(prompt)

            head_before = gitutil.head(scope)
            res.implementer = self._invoke(spec, prompt, scope, pf)

            # 5. judge
            res.after = shell(spec.verify, scope, timeout=spec.timeout_sec)

            return self._finish(res, repo, scope, head_before)
        finally:
            self._save(res)

    def _invoke(self, spec: Spec, prompt: str, scope: str, prompt_file: str) -> CommandResult:
        cmd = self.implementer or codex_command(spec, prompt_file)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=scope, input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=spec.timeout_sec)
            return CommandResult(p.returncode == 0, p.returncode, time.time() - t0,
                                 p.stdout, p.stderr)
        except FileNotFoundError:
            return CommandResult(False, 127, time.time() - t0, "",
                                 "implementer not found: {}\n"
                                 "Install it, or pass --implementer.".format(cmd[0]))
        except subprocess.TimeoutExpired:
            return CommandResult(False, -1, time.time() - t0, "",
                                 "implementer timed out after {}s".format(spec.timeout_sec))

    def _finish(self, res: RunResult, repo: str, scope: str, head_before: str,
                skip_guards: bool = False) -> RunResult:
        wt = res.worktree
        changed = [p for _, p in gitutil.status_paths(wt)]
        res.changed = changed
        ins = dels = 0
        for a, d, _ in gitutil.diff_numstat(wt):
            if a > 0:
                ins += a
            if d > 0:
                dels += d
        res.insertions, res.deletions = ins, dels

        if skip_guards:
            return res

        base_head = gitutil.head(wt) if head_before is None else head_before
        f: List[Finding] = [
            guards.vacuous(res.baseline.ok if res.baseline else None,
                           bool(res.after and res.after.ok)),
            guards.head_moved(wt, base_head),
            guards.comment_stash(wt, base_head, changed),
            guards.must_keep(wt, res.spec.must_keep, changed),
            guards.diff_shape(res.spec.expect, ins, dels),
            guards.outside_cwd(wt, scope, [os.path.join(wt, p) for p in changed]),
        ]
        res.findings = f
        return res

    # ---------------------------------------------------------------- store
    def _save(self, res: RunResult) -> None:
        d = os.path.join(self.store, res.run_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
            json.dump(res.to_dict(), f, indent=2, ensure_ascii=False)
        try:
            with open(os.path.join(d, "diff.patch"), "w", encoding="utf-8") as f:
                f.write(gitutil.diff(res.worktree))
        except (gitutil.GitError, OSError):
            pass

    def load(self, run_id: str) -> Dict:
        with open(os.path.join(self.store, run_id, "result.json"), "r", encoding="utf-8") as f:
            return json.load(f)

    def list_runs(self) -> List[str]:
        if not os.path.isdir(self.store):
            return []
        return sorted(d for d in os.listdir(self.store)
                      if os.path.isfile(os.path.join(self.store, d, "result.json")))

    # ---------------------------------------------------------------- gate
    def accept(self, run_id: str, repo: str, message: str = "") -> str:
        """Commit the run's changes on its branch. Refuses anything that failed.

        The branch is left for a person to merge. The gate's job is to make
        sure nothing that failed ever becomes a candidate.
        """
        d = self.load(run_id)
        if not d["passed"]:
            reasons = []
            if not d["verified"]:
                reasons.append("the verification command did not pass")
            for f in d["findings"]:
                if f["status"] == "fail":
                    reasons.append("{}: {}".format(f["name"], f["summary"]))
            raise RuntimeError("refusing to accept {}:\n  - {}".format(
                run_id, "\n  - ".join(reasons)))

        wt = d["worktree"]
        paths = d["changed"]
        if not paths:
            raise RuntimeError("{}: nothing changed".format(run_id))
        gitutil.add_paths(wt, paths)           # never 'add -A'
        msg = message or "{}\n\nverified: {}".format(d["spec"]["objective"].splitlines()[0],
                                                     d["spec"]["verify"])
        gitutil.run(["commit", "-m", msg], wt)
        return gitutil.head(wt)

    def discard(self, run_id: str, repo: str) -> None:
        d = self.load(run_id)
        gitutil.worktree_remove(repo, d["worktree"])
        gitutil.run(["branch", "-D", d["branch"]], repo, check=False)
        shutil.rmtree(os.path.join(self.store, run_id), ignore_errors=True)
