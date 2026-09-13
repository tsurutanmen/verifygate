"""The machine-readable contract.

A gate is only useful to someone else's pipeline if the pipeline can read the
result without scraping a human-readable table.  These tests define what
``--json`` has to emit; they are written before the feature exists, so they are
red on the starting state and can therefore show that the work happened.
"""

import json
import os
import subprocess
import sys

import pytest

from verifygate import Spec
from verifygate.cli import main
from verifygate.runner import Runner


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def finished_run(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(["init", "-q"], str(repo))
    git(["config", "user.email", "t@example.com"], str(repo))
    git(["config", "user.name", "t"], str(repo))
    git(["checkout", "-q", "-b", "work"], str(repo))
    (repo / "app.js").write_text('var a = 1;\n', encoding="utf-8")
    (repo / "check.py").write_text(
        "import sys\n"
        "sys.exit(0 if 't(' in open('app.js', encoding='utf-8').read() else 1)\n",
        encoding="utf-8")
    git(["add", "."], str(repo))
    git(["commit", "-qm", "start"], str(repo))

    impl = tmp_path / "impl.py"
    impl.write_text(
        "import sys, io\n"
        "sys.stdin.read()\n"
        "io.open('app.js','w',encoding='utf-8').write('var a = t(\"x\");\\n')\n",
        encoding="utf-8")

    store = str(tmp_path / "store")
    r = Runner(store, implementer=[sys.executable, str(impl)])
    res = r.run(Spec.from_dict({
        "id": "demo",
        "objective": "Wrap it.",
        "cwd": str(repo),
        "verify": "{} check.py".format(sys.executable),
    }))
    return store, res.run_id


REQUIRED_KEYS = {"run_id", "passed", "verified", "guards_passed",
                 "insertions", "deletions", "changed", "findings"}


def _run_cli(args, capsys):
    code = main(args)
    return code, capsys.readouterr().out


def test_show_json_is_valid_json_with_the_documented_keys(finished_run, capsys):
    store, run_id = finished_run
    code, out = _run_cli(["--store", store, "show", run_id, "--json"], capsys)
    assert code == 0
    d = json.loads(out)
    assert REQUIRED_KEYS <= set(d), sorted(REQUIRED_KEYS - set(d))
    assert d["run_id"] == run_id
    assert isinstance(d["passed"], bool)


def test_show_json_emits_nothing_but_json(finished_run, capsys):
    """A caller pipes this into a parser. Stray human text breaks it."""
    store, run_id = finished_run
    _, out = _run_cli(["--store", store, "show", run_id, "--json"], capsys)
    assert out.lstrip().startswith("{")
    json.loads(out)                      # would raise on any trailing chatter


def test_each_finding_carries_name_and_status(finished_run, capsys):
    store, run_id = finished_run
    _, out = _run_cli(["--store", store, "show", run_id, "--json"], capsys)
    findings = json.loads(out)["findings"]
    assert findings
    for f in findings:
        assert {"name", "status", "summary"} <= set(f)
        assert f["status"] in ("ok", "fail", "skipped")


def test_list_json_is_an_array_of_runs(finished_run, capsys):
    store, _ = finished_run
    code, out = _run_cli(["--store", store, "list", "--json"], capsys)
    assert code == 0
    rows = json.loads(out)
    assert isinstance(rows, list) and rows
    for row in rows:
        assert {"run_id", "passed"} <= set(row)


def test_json_does_not_change_the_exit_code(finished_run, capsys):
    """The exit code is the gate's answer; --json must not alter it."""
    store, run_id = finished_run
    plain, _ = _run_cli(["--store", store, "show", run_id], capsys)
    as_json, _ = _run_cli(["--store", store, "show", run_id, "--json"], capsys)
    assert plain == as_json


def test_missing_run_still_fails_cleanly_in_json_mode(finished_run, capsys):
    store, _ = finished_run
    code, out = _run_cli(["--store", store, "show", "no-such-run", "--json"], capsys)
    assert code == 2
