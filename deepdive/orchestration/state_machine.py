TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXCEEDED", "TIMED_OUT"}
TRANSITIONS = {
    "CREATED": {"PLANNING"},
    "PLANNING": {"RESEARCHING"},
    "RESEARCHING": {"VERIFYING"},
    "VERIFYING": {"NEEDS_MORE_RESEARCH", "WRITING"},
    "NEEDS_MORE_RESEARCH": {"RESEARCHING", "WRITING"},
    "WRITING": {"COMPLETED"},
}


def validate_transition(old, new):
    if old in TERMINAL or (new not in TRANSITIONS.get(old, set()) and new not in TERMINAL - {"COMPLETED"}):
        raise ValueError("Invalid research state transition")
