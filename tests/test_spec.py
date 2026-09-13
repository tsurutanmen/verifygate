import json
import os

import pytest

from verifygate import Spec, SpecError, HOUSE_RULES


def _base(tmp_path, **over):
    d = {
        "id": "demo",
        "objective": "Do the thing.",
        "cwd": str(tmp_path),
        "verify": "pytest -q",
    }
    d.update(over)
    return d


def test_a_spec_without_verify_is_rejected(tmp_path):
    d = _base(tmp_path)
    del d["verify"]
    with pytest.raises(SpecError) as e:
        Spec.from_dict(d)
    msg = str(e.value)
    assert "no verify command" in msg
    # the message has to explain why, not just what
    assert "not ready to delegate" in msg


def test_an_empty_verify_is_also_rejected(tmp_path):
    with pytest.raises(SpecError):
        Spec.from_dict(_base(tmp_path, verify="   "))


def test_a_complete_spec_loads(tmp_path):
    s = Spec.from_dict(_base(tmp_path))
    assert s.id == "demo"
    assert s.effort == "medium"
    assert s.timeout_sec > 0


def test_unknown_fields_are_refused_rather_than_ignored(tmp_path):
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_base(tmp_path, verfy="typo"))
    assert "verfy" in str(e.value)


def test_missing_directory_is_caught_before_the_run(tmp_path):
    with pytest.raises(SpecError):
        Spec.from_dict(_base(tmp_path, cwd=str(tmp_path / "nope")))


def test_bad_effort_and_expect(tmp_path):
    with pytest.raises(SpecError):
        Spec.from_dict(_base(tmp_path, effort="ludicrous"))
    with pytest.raises(SpecError):
        Spec.from_dict(_base(tmp_path, expect="sideways"))


def test_backslashes_in_cwd_are_normalised(tmp_path):
    d = _base(tmp_path, cwd=str(tmp_path).replace("/", "\\"))
    s = Spec.from_dict(d)
    assert "\\" not in s.cwd


def test_prompt_carries_the_house_rules_and_the_check(tmp_path):
    s = Spec.from_dict(_base(tmp_path, must_keep=["保存する"], forbid=["no npm"]))
    p = s.prompt()
    for rule in HOUSE_RULES:
        assert rule in p
    assert "no npm" in p
    assert "保存する" in p
    assert "pytest -q" in p
    # the anti-gaming rule must be stated to the implementer, not just checked after
    assert "into comments" in p


def test_load_from_file(tmp_path):
    p = tmp_path / "order.json"
    p.write_text(json.dumps(_base(tmp_path)), encoding="utf-8")
    s = Spec.load(str(p))
    assert s.id == "demo"


def test_bad_json_says_so(tmp_path):
    p = tmp_path / "order.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SpecError) as e:
        Spec.load(str(p))
    assert "not valid JSON" in str(e.value)
