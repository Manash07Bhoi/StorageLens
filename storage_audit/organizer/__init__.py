"""V2 organization engine — SAFE FILE ORGANIZATION (planning-first).

This package implements the StorageLens V2 organization workflow:

    Scan → Analyze → Plan → Preview → Approve → Execute → Verify → Undo

Safety invariants (enforced in code and tested):

* No operation executes before explicit human approval of the plan.
* No existing destination is ever silently overwritten.
* No source file is removed before the destination has been verified
  (default action is ``copy-keep``; source removal requires a plan built
  with ``--action move`` AND ``--acknowledge-source-removal`` at apply time).
* Symlinks are never followed or moved; special files are refused.
* The organization scope is one explicitly selected, user-owned folder.
  Android/, system, Termux-private, hidden and reserved content is
  default-deny at every level (org-scope-1, see scope.py) — no overrides.
* Destinations (and sources) must stay inside the approved scope; the scope
  is revalidated at plan time, before execution and before undo.
* Every operation is journalled; interrupted operations are detectable.
"""

from .planner import build_plan, PlanError
from .scope import SCOPE_POLICY_VERSION, ScopeRejected, validate_scope
from .executor import apply_plan, undo_operation, reconcile_interrupted, ExecutionError

__all__ = [
    "build_plan", "PlanError",
    "SCOPE_POLICY_VERSION", "ScopeRejected", "validate_scope",
    "apply_plan", "undo_operation", "reconcile_interrupted", "ExecutionError",
]
