from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "abogus",
    "accesstoken",
    "authorization",
    "clientsecret",
    "cookie",
    "cookies",
    "idtoken",
    "mstoken",
    "odintt",
    "password",
    "passwd",
    "refreshtoken",
    "secret",
    "secretkey",
    "session",
    "sessionid",
    "signature",
    "svwebid",
    "token",
    "xsectoken",
    "ttwid",
    "verifyfp",
    "verifyuuid",
    "webid",
    "xbogus",
    "apikey",
    "appkey",
}
_SENSITIVE_PARAMETER_NAMES = (
    "a_bogus",
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "id_token",
    "msToken",
    "odin_tt",
    "refresh_token",
    "s_v_web_id",
    "session_id",
    "signature",
    "token",
    "ttwid",
    "verifyFp",
    "verifyUuid",
    "webid",
    "X-Bogus",
    "xsec_token",
)
_SENSITIVE_PARAMETER_PATTERN = "|".join(
    sorted(
        (re.escape(name) for name in _SENSITIVE_PARAMETER_NAMES), key=len, reverse=True
    )
)
_TEXT_PATTERNS = (
    re.compile(r"(?im)(\b(?:authorization|set-cookie|cookie)\s*:\s*)[^\r\n]*"),
    re.compile(
        rf"""(?i)(["'](?:{_SENSITIVE_PARAMETER_PATTERN}|cookies?|password|passwd|secret(?:_key)?|session)["']\s*:\s*["'])(.*?)(["'])"""
    ),
    re.compile(r"(?i)(\b(?:authorization|cookies?)\b\s*=\s*)[^\r\n]*"),
    re.compile(
        rf"(?i)(\b(?:{_SENSITIVE_PARAMETER_PATTERN}|password|passwd|secret(?:_key)?|session)\b\s*[:=]\s*)([^\s,;&#]+)"
    ),
    re.compile(rf"(?i)([?&](?:{_SENSITIVE_PARAMETER_PATTERN})=)([^&#\s]+)"),
    re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]+)"),
)


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _TEXT_PATTERNS:
        redacted = pattern.sub(
            lambda match: (
                f"{match.group(1)}{REDACTED}{match.group(3) if match.lastindex == 3 else ''}"
            ),
            redacted,
        )
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): REDACTED
            if _normalized_key(key) in _SENSITIVE_KEYS
            else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_log_message(value: str) -> str:
    """Redact both structured JSON log lines and ordinary text."""
    try:
        import json

        parsed = json.loads(value)
    except (TypeError, ValueError):
        return redact_text(value)
    return json.dumps(redact_value(parsed), ensure_ascii=False, separators=(",", ":"))


def truncate_value(value: Any, max_string: int = 2_000) -> Any:
    if isinstance(value, dict):
        return {
            str(key): truncate_value(item, max_string) for key, item in value.items()
        }
    if isinstance(value, list):
        return [truncate_value(item, max_string) for item in value]
    if isinstance(value, str) and len(value) > max_string:
        return value[:max_string] + "...[truncated]"
    return value
