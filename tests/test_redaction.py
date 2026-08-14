from __future__ import annotations

import json

from dsh_mediacrawler.redaction import (
    REDACTED,
    redact_log_message,
    redact_text,
    redact_value,
)


def test_cookie_header_is_fully_redacted() -> None:
    value = "Cookie: a=1; b=2; session=SECRET\nnext line"

    redacted = redact_text(value)

    assert redacted == f"Cookie: {REDACTED}\nnext line"
    assert "SECRET" not in redacted


def test_authorization_header_is_fully_redacted() -> None:
    value = "Authorization: Bearer VERY-SECRET-TOKEN\nnext line"

    redacted = redact_text(value)

    assert redacted == f"Authorization: {REDACTED}\nnext line"
    assert "VERY-SECRET-TOKEN" not in redacted


def test_json_log_line_is_structurally_redacted() -> None:
    value = json.dumps(
        {
            "cookie": "COOKIE-SECRET",
            "access_token": "ACCESS-SECRET",
            "client_secret": "CLIENT-SECRET",
            "session_id": "SESSION-SECRET",
            "safe": "visible",
        }
    )

    redacted = json.loads(redact_log_message(value))

    assert redacted["safe"] == "visible"
    assert {redacted[key] for key in redacted if key != "safe"} == {REDACTED}


def test_nested_sensitive_keys_are_redacted() -> None:
    value = {"nested": {"refresh_token": "secret", "id_token": "secret"}}

    assert redact_value(value) == {
        "nested": {"refresh_token": REDACTED, "id_token": REDACTED}
    }


def test_platform_tracking_credentials_are_redacted() -> None:
    value = {
        "msToken": "MS-TOKEN",
        "a_bogus": "A-BOGUS",
        "verifyFp": "VERIFY-FP",
        "verifyUuid": "VERIFY-UUID",
        "webid": "WEB-ID",
    }

    assert set(redact_value(value).values()) == {REDACTED}


def test_platform_credentials_are_redacted_from_urls_and_text() -> None:
    value = (
        "https://example.test/path?msToken=MS-TOKEN&a_bogus=A-BOGUS"
        "&verifyFp=VERIFY-FP&X-Bogus=X-BOGUS"
    )

    redacted = redact_text(value)

    assert "MS-TOKEN" not in redacted
    assert "A-BOGUS" not in redacted
    assert "VERIFY-FP" not in redacted
    assert "X-BOGUS" not in redacted


def test_platform_credentials_are_redacted_from_prefixed_python_dict_logs() -> None:
    value = "MediaCrawler ERROR - {'msToken': 'MS-TOKEN', 'a_bogus': 'A-BOGUS'}"

    redacted = redact_text(value)

    assert "MS-TOKEN" not in redacted
    assert "A-BOGUS" not in redacted


def test_pii_is_not_misrepresented_as_anonymized() -> None:
    value = {"phone": "13800138000", "email": "user@example.com"}

    assert redact_value(value) == value
