from __future__ import annotations

import pytest

from dsh_mediacrawler.errors import AdapterError
from dsh_mediacrawler.models import PLATFORMS, CollectRequest


def request(**overrides: object) -> CollectRequest:
    values: dict[str, object] = {
        "platform": "xhs",
        "mode": "search",
        "query": "adapter test",
    }
    values.update(overrides)
    return CollectRequest.create(**values)


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_all_supported_platforms_are_accepted(platform: str) -> None:
    assert request(platform=platform).platform == platform


@pytest.mark.parametrize(
    ("overrides", "message_fragment"),
    [
        ({"platform": "unknown"}, "Unsupported platform"),
        ({"mode": "browse"}, "mode must be"),
        ({"browser_mode": "shared"}, "browser_mode must be"),
        ({"query": None}, "query is required"),
        ({"targets": ["unexpected"]}, "targets are not accepted"),
        ({"mode": "detail", "query": None}, "targets are required"),
        (
            {"mode": "detail", "query": None, "targets": ["one,two"]},
            "cannot contain a comma",
        ),
        (
            {"login_type": "cookie"},
            "phone and cookie login are intentionally unavailable",
        ),
        (
            {"login_type": "phone"},
            "phone and cookie login are intentionally unavailable",
        ),
        ({"query": "one,two"}, "query cannot contain a comma"),
        ({"max_items": 0}, "max_items must be between"),
        ({"max_items": 101}, "max_items must be between"),
        ({"max_comments_per_item": -1}, "max_comments_per_item must be between"),
        ({"max_comments_per_item": 201}, "max_comments_per_item must be between"),
        (
            {"include_comments": False, "include_nested_comments": True},
            "requires include_comments=true",
        ),
        ({"start_page": 0}, "start_page must be between"),
        ({"start_page": 101}, "start_page must be between"),
        ({"timeout_minutes": 0}, "timeout_minutes must be between"),
        ({"timeout_minutes": 121}, "timeout_minutes must be between"),
        ({"request_id": "contains space"}, "request_id must be"),
    ],
)
def test_invalid_requests_are_rejected(
    overrides: dict[str, object], message_fragment: str
) -> None:
    with pytest.raises(AdapterError) as caught:
        request(**overrides)

    assert caught.value.code == "INVALID_REQUEST"
    assert message_fragment in caught.value.message


@pytest.mark.parametrize(
    ("mode", "targets"),
    [("detail", ["post-a", "post-b"]), ("creator", ["creator-a"])],
)
def test_target_modes_are_accepted(mode: str, targets: list[str]) -> None:
    result = request(mode=mode, query=None, targets=targets)

    assert result.mode == mode
    assert result.targets == tuple(targets)


def test_request_fingerprint_ignores_request_id() -> None:
    first = request(request_id="first")
    second = request(request_id="second")

    assert first.fingerprint() == second.fingerprint()


def test_isolated_browser_is_the_default() -> None:
    assert request().browser_mode == "isolated"


def test_comments_require_explicit_opt_in() -> None:
    assert request().include_comments is False
