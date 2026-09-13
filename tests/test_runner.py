"""End to end, with a scripted implementer standing in for the real one.

The implementer is just a command, so the honest one, the lazy one and the one
that games the check can all be written as three-line scripts.
"""

import json
import os
import subprocess
import sys

import pytest

from verifygate import Spec, gitutil
from verifygate.runner import Runner


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    git(["init", "-q"], str(d))
    git(["config", "user.email", "t@example.com"], str(d))
    git(["config", "user.name", "t"], str(d))
    git(["checkout", "-q", "-b", "work"], str(d))
    (d / "app.js").write_text('var msg = "使い方を見る";\n', encoding="utf-8")
    # the check: the file must mention t(, and must still mention the label
    (d / "check.py").write_text(
        "import sys\n"
        "s = open('app.js', encoding='utf-8').read()\n"
        "sys.exit(0 if 't(' in s else 1)\n", encoding="utf-8")
    git(["add", "."], str(d))
    git(["commit", "-qm", "start"], str(d))
    return str(d)


def _spec(repo, tmp_path, **over):
    d = {
        "id": "demo",
        "objective": "Wrap the label in t().",
        "cwd": repo,
        "verify": "{} check.py".format(sys.executable),
    }
    d.update(over)
    return Spec.from_dict(d)


def _script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return "{} {}".format(sys.executable, str(p))


def test_dry_run_reports_the_baseline_without_delegating(repo, tmp_path):
    r = Runner(str(tmp_path / "store"))
    res = r.run(_spec(repo, tmp_path), dry_run=True)
    assert res.baseline is not None
    assert res.baseline.ok is False          # t( is not there yet
    assert res.implementer is None
    assert os.path.isdir(res.worktree)


def test_an_honest_implementer_passes_and_can_be_accepted(repo, tmp_path):
    impl = _script(tmp_path, "good.py",
                   "import sys\n"
                   "sys.stdin.read()\n"
                   "open('app.js','w',encoding='utf-8')"
                   ".write('var msg = t(\"使い方を見る\");\\n')\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    res = r.run(_spec(repo, tmp_path, must_keep=["使い方を見る"]))
    assert res.verified, res.after.stderr
    assert res.guards_passed, [f.summary for f in res.findings if f.failed]
    assert res.passed
    sha = r.accept(res.run_id, repo)
    assert len(sha) == 40


def test_an_implementer_that_games_the_check_is_caught(repo, tmp_path):
    """t( appears, the label is preserved only in a comment. The check passes."""
    impl = _script(tmp_path, "cheat.py",
                   "import sys\n"
                   "sys.stdin.read()\n"
                   "open('app.js','w',encoding='utf-8').write(\n"
                   "  'var msg = t(\"btn\");\\n// 使い方を見る\\n')\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    res = r.run(_spec(repo, tmp_path, must_keep=["使い方を見る"]))
    assert res.verified          # the verification command is happy
    assert not res.passed        # the gate is not
    names = {f.name for f in res.findings if f.failed}
    assert "must_keep" in names or "comment_stash" in names


def test_a_run_that_failed_cannot_be_accepted(repo, tmp_path):
    impl = _script(tmp_path, "lazy.py", "import sys\nsys.stdin.read()\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    res = r.run(_spec(repo, tmp_path))
    assert not res.passed
    with pytest.raises(RuntimeError) as e:
        r.accept(res.run_id, repo)
    assert "refusing to accept" in str(e.value)


def test_a_check_that_was_already_green_fails_the_gate(repo, tmp_path):
    """The job is already done. Passing afterwards shows nothing."""
    with open(os.path.join(repo, "app.js"), "w", encoding="utf-8") as f:
        f.write('var msg = t("使い方を見る");\n')
    git(["add", "app.js"], repo)
    git(["commit", "-qm", "already done"], repo)

    impl = _script(tmp_path, "noop.py", "import sys\nsys.stdin.read()\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    res = r.run(_spec(repo, tmp_path))
    assert res.verified
    assert not res.passed
    assert any(f.name == "vacuous" and f.failed for f in res.findings)


def test_the_original_working_copy_is_untouched(repo, tmp_path):
    before = open(os.path.join(repo, "app.js"), encoding="utf-8").read()
    impl = _script(tmp_path, "good2.py",
                   "import sys\nsys.stdin.read()\n"
                   "open('app.js','w',encoding='utf-8').write('var msg = t(\"x\");\\n')\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    r.run(_spec(repo, tmp_path))
    assert open(os.path.join(repo, "app.js"), encoding="utf-8").read() == before
    assert gitutil.is_clean(repo)


def test_it_refuses_to_start_on_a_deploying_branch(repo, tmp_path):
    git(["checkout", "-q", "-b", "main"], repo)
    r = Runner(str(tmp_path / "store"))
    with pytest.raises(RuntimeError) as e:
        r.run(_spec(repo, tmp_path), dry_run=True)
    assert "deploys" in str(e.value)


def test_two_runs_do_not_collide(repo, tmp_path):
    impl = _script(tmp_path, "g3.py",
                   "import sys\nsys.stdin.read()\n"
                   "open('app.js','w',encoding='utf-8').write('var msg = t(\"x\");\\n')\n")
    r = Runner(str(tmp_path / "store"), implementer=impl.split())
    a = r.run(_spec(repo, tmp_path, id="one"))
    b = r.run(_spec(repo, tmp_path, id="two"))
    assert a.worktree != b.worktree
    assert a.branch != b.branch
    assert len(r.list_runs()) == 2


def test_the_run_is_written_down(repo, tmp_path):
    impl = _script(tmp_path, "g4.py",
                   "import sys\nsys.stdin.read()\n"
                   "open('app.js','w',encoding='utf-8').write('var msg = t(\"x\");\\n')\n")
    store = str(tmp_path / "store")
    r = Runner(store, implementer=impl.split())
    res = r.run(_spec(repo, tmp_path))
    with open(os.path.join(store, res.run_id, "result.json"), encoding="utf-8") as f:
        d = json.load(f)
    assert d["run_id"] == res.run_id
    assert d["spec"]["verify"]
    assert os.path.isfile(os.path.join(store, res.run_id, "order.md"))
    assert os.path.isfile(os.path.join(store, res.run_id, "diff.patch"))


def test_a_missing_implementer_is_reported_not_crashed(repo, tmp_path):
    r = Runner(str(tmp_path / "store"), implementer=["definitely-not-a-command-xyz"])
    res = r.run(_spec(repo, tmp_path))
    assert res.implementer is not None
    assert res.implementer.code == 127
    assert "not found" in res.implementer.stderr
    assert not res.passed
