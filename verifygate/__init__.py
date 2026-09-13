"""verifygate - delegate work only when a machine can tell you it was done.

The rule the tool exists to enforce: an order without a verification command is
not accepted.  Whether you can write that command is the test of whether the
job can be handed over at all.

Everything else here is about the gap between "the command exited zero" and
"the work was done":

* the baseline - a check that was already green proves nothing
* the comment check - text parked in a comment satisfies a presence check
  without satisfying the job
* the diff shape - an adding job that mostly deletes is a regression
* isolation - each run gets its own worktree and branch, so nothing lands
  anywhere by accident and two runs cannot collide
"""

__version__ = "0.1.0"

from .spec import Spec, SpecError, HOUSE_RULES          # noqa: E402,F401
from .runner import Runner, RunResult, CommandResult     # noqa: E402,F401
from .guards import Finding                              # noqa: E402,F401
from . import comments, guards, gitutil                  # noqa: E402,F401

__all__ = [
    "Spec", "SpecError", "HOUSE_RULES",
    "Runner", "RunResult", "CommandResult", "Finding",
    "comments", "guards", "gitutil", "__version__",
]
