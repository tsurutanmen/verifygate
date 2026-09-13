"""The work order, and the one rule that makes it one.

A spec without a verification command is rejected at load time.  That is not a
convenience check.  Whether you can write the check *is* the test of whether
the job can be delegated at all: if a machine cannot tell you the work was
done, you will read every line of it yourself, and reading someone else's code
takes longer than writing your own.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


class SpecError(ValueError):
    """A work order that cannot be accepted as written."""


#: Appended to every objective.  Each line is here because it was learned the
#: hard way; see README for the incident behind each one.
HOUSE_RULES: List[str] = [
    "Do not run git commit, push, checkout, reset, or branch. The run is reviewed before history moves.",
    "Do not create or modify files outside the working directory.",
    "Do not read skill files (SKILL.md) or any instructions other than this order.",
    "Do not widen the objective. If something else looks broken, report it, do not fix it.",
    "Do not move text into comments, disabled code, or hidden elements in order to satisfy the"
    " verification command. Doing so fails the run.",
    "Run the verification command yourself and make it pass before reporting.",
]

_REQUIRED = ("id", "objective", "cwd", "verify")
_KNOWN = {
    "id", "objective", "cwd", "verify", "notes", "forbid", "model", "effort",
    "timeout_sec", "web", "expect", "must_keep", "base",
}


def _as_list(v: Any, field_name: str) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            if not isinstance(x, str):
                raise SpecError("{}: every entry must be a string".format(field_name))
            out.append(x)
        return out
    raise SpecError("{}: expected a string or a list of strings".format(field_name))


@dataclass
class Spec:
    """One unit of delegated work."""

    id: str
    objective: str
    cwd: str
    verify: str
    notes: str = ""
    forbid: List[str] = field(default_factory=list)
    model: Optional[str] = None
    effort: str = "medium"
    timeout_sec: int = 2400
    web: bool = False
    #: "add" or "remove" or "" — used to flag a diff whose shape contradicts the job
    expect: str = ""
    #: strings that must still be present, in real code, when the run finishes
    must_keep: List[str] = field(default_factory=list)
    #: branch the work is based on; the run refuses to start on a deploying branch
    base: str = ""

    # ------------------------------------------------------------------ load
    @classmethod
    def from_dict(cls, d: Dict[str, Any], source: str = "<dict>") -> "Spec":
        if not isinstance(d, dict):
            raise SpecError("{}: expected a JSON object at the top level".format(source))

        unknown = sorted(set(d) - _KNOWN)
        if unknown:
            raise SpecError("{}: unknown field(s): {}".format(source, ", ".join(unknown)))

        missing = [k for k in _REQUIRED if not str(d.get(k, "")).strip()]
        if missing:
            if "verify" in missing:
                raise SpecError(
                    "{}: no verify command.\n\n"
                    "  A work order without a verification command is not accepted.\n"
                    "  If you cannot write a command that tells you the job was done,\n"
                    "  the job is not ready to delegate - do it yourself, or find the\n"
                    "  check first.  See README, 'The one rule'.\n"
                    "  Still missing: {}".format(source, ", ".join(missing))
                )
            raise SpecError("{}: missing required field(s): {}".format(source, ", ".join(missing)))

        if not str(d["id"]).strip().replace("-", "").replace("_", "").isalnum():
            raise SpecError("id: use letters, digits, '-' and '_' only (it becomes a branch name)")

        cwd = str(d["cwd"]).replace("\\", "/")
        if not os.path.isdir(cwd):
            raise SpecError("cwd: not a directory: {}".format(cwd))

        effort = str(d.get("effort", "medium"))
        if effort not in ("low", "medium", "high", "max"):
            raise SpecError("effort: expected one of low, medium, high, max")

        expect = str(d.get("expect", ""))
        if expect not in ("", "add", "remove"):
            raise SpecError("expect: expected 'add', 'remove', or omitted")

        try:
            timeout = int(d.get("timeout_sec", 2400))
        except (TypeError, ValueError):
            raise SpecError("timeout_sec: expected an integer number of seconds")
        if timeout <= 0:
            raise SpecError("timeout_sec: must be positive")

        return cls(
            id=str(d["id"]).strip(),
            objective=str(d["objective"]).strip(),
            cwd=cwd,
            verify=str(d["verify"]).strip(),
            notes=str(d.get("notes", "")),
            forbid=_as_list(d.get("forbid"), "forbid"),
            model=(str(d["model"]) if d.get("model") else None),
            effort=effort,
            timeout_sec=timeout,
            web=bool(d.get("web", False)),
            expect=expect,
            must_keep=_as_list(d.get("must_keep"), "must_keep"),
            base=str(d.get("base", "")),
        )

    @classmethod
    def load(cls, path: str) -> "Spec":
        with open(path, "r", encoding="utf-8") as f:
            try:
                d = json.load(f)
            except json.JSONDecodeError as e:
                raise SpecError("{}: not valid JSON: {}".format(path, e))
        return cls.from_dict(d, source=path)

    # ----------------------------------------------------------------- emit
    def prompt(self) -> str:
        """The full text handed to the implementer."""
        parts = [self.objective.strip(), ""]
        if self.notes.strip():
            parts += ["## What you need to know", self.notes.strip(), ""]
        parts += ["## Rules"]
        parts += ["- " + r for r in HOUSE_RULES]
        parts += ["- " + r for r in self.forbid]
        if self.must_keep:
            parts += [
                "",
                "## Must still be present when you finish",
                "These strings must remain in real, executed code - not in a comment,"
                " not in disabled code, not in a string table you stopped reading:",
            ]
            parts += ["- " + s for s in self.must_keep]
        parts += ["", "## How this is judged", "```", self.verify, "```"]
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
