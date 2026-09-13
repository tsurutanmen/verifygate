import os
import subprocess

import pytest

from verifygate import guards, gitutil


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    git(["init", "-q"], str(d))
    git(["config", "user.email", "t@example.com"], str(d))
    git(["config", "user.name", "t"], str(d))
    git(["checkout", "-q", "-b", "work"], str(d))
    (d / "app.js").write_text(
        'function greet() {\n  return label("使い方を見る");\n}\n', encoding="utf-8")
    git(["add", "app.js"], str(d))
    git(["commit", "-qm", "start"], str(d))
    return str(d)


# ------------------------------------------------------------------- vacuous
def test_a_check_that_was_already_green_is_called_out():
    f = guards.vacuous(baseline_passed=True, after_passed=True)
    assert f.failed
    assert "already passed" in f.summary


def test_red_then_green_is_what_we_want():
    assert guards.vacuous(False, True).status == "ok"


def test_no_baseline_is_skipped_not_silently_ok():
    assert guards.vacuous(None, True).status == "skipped"


# ------------------------------------------------------------- comment_stash
def test_text_moved_into_a_comment_is_caught(repo):
    ref = gitutil.head(repo)
    with open(os.path.join(repo, "app.js"), "w", encoding="utf-8") as f:
        f.write('function greet() {\n  return label(t("btn"));\n}\n'
                '/* former fragments: return label("使い方を見る"); */\n')
    f = guards.comment_stash(repo, ref, ["app.js"])
    assert f.failed
    assert "app.js" in "\n".join(f.detail)


def test_an_honest_rename_is_not_flagged(repo):
    ref = gitutil.head(repo)
    with open(os.path.join(repo, "app.js"), "w", encoding="utf-8") as f:
        f.write('function greet() {\n  return label("使い方を見る");\n}\n'
                '// unrelated note\n')
    assert guards.comment_stash(repo, ref, ["app.js"]).status == "ok"


def test_deleting_outright_is_not_a_stash(repo):
    """Removing the line is a different problem; this guard is about hiding."""
    ref = gitutil.head(repo)
    with open(os.path.join(repo, "app.js"), "w", encoding="utf-8") as f:
        f.write('function greet() {\n  return null;\n}\n')
    assert guards.comment_stash(repo, ref, ["app.js"]).status == "ok"


# ----------------------------------------------------------------- must_keep
def test_required_string_only_in_a_comment_fails(repo):
    with open(os.path.join(repo, "app.js"), "w", encoding="utf-8") as f:
        f.write('function greet() {}\n// 使い方を見る\n')
    f = guards.must_keep(repo, ["使い方を見る"], ["app.js"])
    assert f.failed
    assert "only inside a comment" in "\n".join(f.detail)


def test_required_string_present_in_code_passes(repo):
    f = guards.must_keep(repo, ["使い方を見る"], ["app.js"])
    assert f.status == "ok"


def test_nothing_declared_is_skipped(repo):
    assert guards.must_keep(repo, [], ["app.js"]).status == "skipped"


# ---------------------------------------------------------------- head_moved
def test_a_commit_during_the_run_is_caught(repo):
    before = gitutil.head(repo)
    (open(os.path.join(repo, "b.txt"), "w")).write("x")
    git(["add", "b.txt"], repo)
    git(["commit", "-qm", "sneaky"], repo)
    assert guards.head_moved(repo, before).failed


def test_no_commit_is_fine(repo):
    assert guards.head_moved(repo, gitutil.head(repo)).status == "ok"


# ---------------------------------------------------------------- diff_shape
def test_an_adding_job_that_deletes_more_is_flagged():
    assert guards.diff_shape("add", 3, 90).failed


def test_a_removing_job_that_adds_more_is_flagged():
    assert guards.diff_shape("remove", 90, 3).failed


def test_no_declared_direction_is_skipped():
    assert guards.diff_shape("", 1, 99).status == "skipped"


# --------------------------------------------------------------- outside_cwd
def test_writing_outside_the_scope_is_caught(tmp_path):
    root = tmp_path / "root"
    (root / "in").mkdir(parents=True)
    (root / "out").mkdir()
    f = guards.outside_cwd(str(root), str(root / "in"),
                           [str(root / "in" / "a.txt"), str(root / "out" / "b.txt")])
    assert f.failed
    assert any("out/b.txt" in d for d in f.detail)


def test_staying_inside_the_scope_passes(tmp_path):
    root = tmp_path / "root"
    (root / "in").mkdir(parents=True)
    assert guards.outside_cwd(str(root), str(root / "in"),
                              [str(root / "in" / "a.txt")]).status == "ok"


# ------------------------------------------------------------------- refusal
def test_a_deploying_branch_is_refused(repo):
    git(["checkout", "-q", "-b", "main"], repo)
    why = gitutil.refuses_to_run_here(repo)
    assert why and "deploys" in why


def test_a_working_branch_is_allowed(repo):
    assert gitutil.refuses_to_run_here(repo) is None


def test_main_can_be_allowed_explicitly(repo):
    git(["checkout", "-q", "-b", "main"], repo)
    assert gitutil.refuses_to_run_here(repo, allow=("main",)) is None
