"""Bounded, structured control flow. No Python expressions or eval are accepted."""

from __future__ import annotations

CONDITIONS = {"if_equal", "if_contains", "if_visible"}
CONTROL = CONDITIONS | {"else", "end_if", "repeat", "end_repeat"}
MAX_REPEAT = 100
MAX_EXPANDED_STEPS = 10000


def repeat_count(value):
    if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= MAX_REPEAT:
        raise ValueError(f"Repeat Value must be an integer from 0 to {MAX_REPEAT}")
    return int(value)


def flow_plan(steps, phase):
    """Match blocks independently per phase; disabled steps have no effect."""
    stack, ends, alternatives, owners = [], {}, {}, {}
    for i, step in enumerate(steps):
        if step["phase"] != phase or not step["enabled"]:
            continue
        command = step["command"]
        if command in CONDITIONS | {"repeat"}:
            stack.append((i, command))
            if len(stack) > 8:
                raise ValueError("Control flow supports at most eight nested blocks")
        elif command == "else":
            if not stack or stack[-1][1] not in CONDITIONS or stack[-1][0] in alternatives:
                raise ValueError(f"Step {i + 1}: else needs one unmatched if in the same phase")
            alternatives[stack[-1][0]] = i
        elif command in {"end_if", "end_repeat"}:
            wanted = CONDITIONS if command == "end_if" else {"repeat"}
            if not stack or stack[-1][1] not in wanted:
                raise ValueError(f"Step {i + 1}: {command} has no matching opener in the same phase")
            start, _ = stack.pop()
            ends[start], owners[i] = i, start
            if start in alternatives:
                owners[alternatives[start]] = start
    if stack:
        raise ValueError(f"Step {stack[-1][0] + 1}: block needs a matching end in the same phase")
    return dict(ends=ends, alternatives=alternatives, owners=owners)


def validate_flow(steps):
    from automation.schema import PHASES
    for phase in PHASES:
        flow_plan(steps, phase)


def top_level_actions(steps, phase):
    plan = flow_plan(steps, phase)
    return {s["id"] for i, s in enumerate(steps) if s["enabled"] and s["phase"] == phase and s["command"] not in CONTROL | {"note"}
            and not any(start < i < end for start, end in plan["ends"].items())}


def check_budget(steps, phase, variables):
    """Use a conservative upper bound for runtime-derived iteration counts."""
    from automation.schema import resolve
    flow_plan(steps, phase)
    variables = dict(variables)
    for step in steps:
        if step["enabled"]:
            if step["command"] in {"repeat", "set_variable"}:
                variables[step["target"]] = "<runtime value>"
            elif step["command"] in {"store_text", "store_value"}:
                variables[step["value"]] = "<runtime value>"
    factors, factor, total = [], 1, 0
    for step in steps:
        if step["phase"] != phase or not step["enabled"]:
            continue
        total += factor
        if step["command"] == "repeat":
            try:
                value = resolve(step["value"], variables)
                count = MAX_REPEAT if value.startswith("<runtime") else repeat_count(value)
            except ValueError:
                count = MAX_REPEAT
            factors.append(factor)
            factor *= count
        elif step["command"] == "end_repeat":
            factor = factors.pop()
        if total > MAX_EXPANDED_STEPS:
            raise ValueError(f"Expanded {phase} exceeds {MAX_EXPANDED_STEPS} steps; reduce repeat counts or nesting")
    return total
