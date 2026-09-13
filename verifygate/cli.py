"""Command line.

    verifygate check   order.json          is this order acceptable at all?
    verifygate run     order.json          baseline, delegate, verify, guard
    verifygate list                        runs on record
    verifygate show    <run-id>            what happened, and what the guards saw
    verifygate accept  <run-id>            commit it - refuses anything that failed
    verifygate discard <run-id>            throw the branch and the worktree away
    verifygate guard   --keep X -- files   the comment-stash check on its own
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, comments, gitutil, guards
from .runner import Runner
from .spec import Spec, SpecError


def _store(args) -> str:
    return args.store or os.path.join(os.path.expanduser("~"), ".verifygate", "runs")


def _p(s: str = "") -> None:
    try:
        sys.stdout.write(s + "\n")
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        sys.stdout.write(s.encode(enc, "replace").decode(enc) + "\n")


def _utf8_stdout() -> None:
    """Findings quote source text, which is often not ASCII.

    A Windows console defaults to a legacy code page and turns a Japanese label
    into mojibake, which makes a real finding look like a bug in the tool.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


# ---------------------------------------------------------------- subcommands
def cmd_check(args) -> int:
    try:
        spec = Spec.load(args.spec)
    except SpecError as e:
        _p("rejected.\n\n{}".format(e))
        return 2
    _p("accepted: {}".format(spec.id))
    _p("  scope   {}".format(spec.cwd))
    _p("  verify  {}".format(spec.verify))
    if spec.must_keep:
        _p("  keeps   {} string(s)".format(len(spec.must_keep)))
    if spec.expect:
        _p("  shape   expected to {}".format(spec.expect))
    if args.print_order:
        _p("")
        _p(spec.prompt())
    return 0


def cmd_run(args) -> int:
    try:
        spec = Spec.load(args.spec)
    except SpecError as e:
        _p("rejected.\n\n{}".format(e))
        return 2

    runner = Runner(_store(args),
                    implementer=(args.implementer.split() if args.implementer else None),
                    allow_branch=tuple(args.allow_branch or ()),
                    keep_worktree=args.keep)
    try:
        res = runner.run(spec, dry_run=args.dry_run)
    except RuntimeError as e:
        _p("refusing to start.\n\n  {}".format(e))
        return 2
    except gitutil.GitError as e:
        _p("git: {}".format(e))
        return 2

    _p("run {}".format(res.run_id))
    _p("  branch    {}".format(res.branch))
    _p("  worktree  {}".format(res.worktree))
    if res.baseline:
        _p("  baseline  {} in {:.1f}s".format(
            "passed (this check cannot show the work)" if res.baseline.ok else "failed, as it should",
            res.baseline.seconds))
    if args.dry_run:
        _p("\ndry run: the implementer was not invoked.")
        _p("The order is at {}".format(os.path.join(runner.store, res.run_id, "order.md")))
        return 0
    if res.implementer and not res.implementer.ok:
        _p("  implementer exited {}".format(res.implementer.code))
        if res.implementer.stderr.strip():
            _p("    " + res.implementer.stderr.strip().splitlines()[-1])
    if res.after:
        _p("  verify    {} in {:.1f}s".format("PASS" if res.after.ok else "FAIL",
                                              res.after.seconds))
    _p("  diff      +{} / -{} across {} file(s)".format(
        res.insertions, res.deletions, len(res.changed)))
    _p("")
    _p("guards")
    for f in res.findings:
        _p(f.render())
    _p("")
    if res.passed:
        _p("PASSED. verifygate accept {}".format(res.run_id))
        return 0
    _p("NOT ACCEPTED. Nothing has been committed.")
    _p("  verifygate show {}   to read the diff and the output".format(res.run_id))
    return 1


def cmd_list(args) -> int:
    runner = Runner(_store(args))
    ids = runner.list_runs()
    if not ids:
        _p("no runs in {}".format(runner.store))
        return 0
    for rid in ids:
        try:
            d = runner.load(rid)
        except (OSError, ValueError):
            continue
        _p("{:<34} {:<7} +{}/-{}  {}".format(
            rid, "PASSED" if d["passed"] else "held",
            d["insertions"], d["deletions"], d["spec"]["verify"][:44]))
    return 0


def cmd_show(args) -> int:
    runner = Runner(_store(args))
    try:
        d = runner.load(args.run_id)
    except OSError:
        _p("no such run: {}".format(args.run_id))
        return 2
    _p("{}  {}".format(d["run_id"], "PASSED" if d["passed"] else "held"))
    _p("  objective  {}".format(d["spec"]["objective"].splitlines()[0][:90]))
    _p("  verify     {}".format(d["spec"]["verify"]))
    _p("  branch     {}".format(d["branch"]))
    _p("  diff       +{} / -{} across {} file(s)".format(
        d["insertions"], d["deletions"], len(d["changed"])))
    _p("")
    for f in d["findings"]:
        _p(guards.Finding(f["name"], f["status"], f["summary"], f["detail"]).render())
    for key in ("baseline", "after"):
        c = d.get(key)
        if c and args.output:
            _p("")
            _p("--- {} (exit {}) ---".format(key, c["code"]))
            _p((c["stdout"] or "").strip()[-4000:])
            if (c["stderr"] or "").strip():
                _p((c["stderr"] or "").strip()[-2000:])
    patch = os.path.join(runner.store, args.run_id, "diff.patch")
    if args.diff and os.path.isfile(patch):
        _p("")
        with open(patch, "r", encoding="utf-8", errors="replace") as f:
            _p(f.read())
    return 0


def cmd_accept(args) -> int:
    runner = Runner(_store(args))
    try:
        d = runner.load(args.run_id)
        sha = runner.accept(args.run_id, gitutil.toplevel(d["spec"]["cwd"]), args.message or "")
    except OSError:
        _p("no such run: {}".format(args.run_id))
        return 2
    except RuntimeError as e:
        _p(str(e))
        return 1
    _p("committed {} on {}".format(sha[:12], d["branch"]))
    _p("A person merges it from here.")
    return 0


def cmd_discard(args) -> int:
    runner = Runner(_store(args))
    try:
        d = runner.load(args.run_id)
        runner.discard(args.run_id, gitutil.toplevel(d["spec"]["cwd"]))
    except OSError:
        _p("no such run: {}".format(args.run_id))
        return 2
    _p("discarded {}".format(args.run_id))
    return 0


def cmd_guard(args) -> int:
    """The comment check on its own, for use inside a verify command."""
    bad = 0
    for path in args.files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            _p("{}: {}".format(path, e))
            bad += 1
            continue
        for needle in args.keep:
            in_code = comments.count_in_code(text, needle, path)
            in_comment = comments.count_in_comments(text, needle, path)
            if in_code == 0 and in_comment > 0:
                _p("{}: {!r} only inside a comment".format(path, needle))
                bad += 1
            elif in_code == 0:
                _p("{}: {!r} not found".format(path, needle))
                bad += 1
    if bad:
        _p("{} problem(s)".format(bad))
        return 1
    _p("ok: every string present in code")
    return 0


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="verifygate",
        description="Delegate work only when a machine can tell you it was done.")
    ap.add_argument("--version", action="version", version="verifygate " + __version__)
    ap.add_argument("--store", help="where runs are kept (default ~/.verifygate/runs)")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("check", help="validate an order without running it")
    c.add_argument("spec")
    c.add_argument("--print-order", action="store_true", help="show the text the implementer gets")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="baseline, delegate, verify, guard")
    r.add_argument("spec")
    r.add_argument("--dry-run", action="store_true", help="baseline only; do not delegate")
    r.add_argument("--implementer", help="command to run instead of the Codex CLI")
    r.add_argument("--allow-branch", action="append",
                   help="permit a branch normally treated as deploying")
    r.add_argument("--keep", action="store_true", help="keep the worktree after the run")
    r.set_defaults(func=cmd_run)

    li = sub.add_parser("list", help="runs on record")
    li.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="what happened in a run")
    s.add_argument("run_id")
    s.add_argument("--diff", action="store_true")
    s.add_argument("--output", action="store_true", help="include the verify output")
    s.set_defaults(func=cmd_show)

    a = sub.add_parser("accept", help="commit a run that passed")
    a.add_argument("run_id")
    a.add_argument("-m", "--message")
    a.set_defaults(func=cmd_accept)

    d = sub.add_parser("discard", help="delete a run's branch and worktree")
    d.add_argument("run_id")
    d.set_defaults(func=cmd_discard)

    g = sub.add_parser("guard", help="check strings survive in code, not comments")
    g.add_argument("--keep", action="append", required=True, metavar="STRING")
    g.add_argument("files", nargs="+")
    g.set_defaults(func=cmd_guard)
    return ap


def main(argv=None) -> int:
    _utf8_stdout()
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
