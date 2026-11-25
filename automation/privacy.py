"""Mask known credential values in textual outcomes without changing execution data."""

import re

IDENTITY_KEYS = {"id", "step_id", "case_id", "command", "phase", "status", "browser", "evidence", "runtime_id"}


def credential_values(variables):
    return {str(value) for key, value in variables.items() if value and
            re.search(r"password|passwd|secret|token|api[_-]?key", key, re.I)}


def redact(value, secrets):
    if isinstance(value, str):
        for secret in sorted((v for v in secrets if v), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: item if key in IDENTITY_KEYS else redact(item, secrets) for key, item in value.items()}
    return value
