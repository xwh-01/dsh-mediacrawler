from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .errors import AdapterError

PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"}
MODES = {"search", "detail", "creator"}
LOGIN_TYPES = {"qrcode"}
BROWSER_MODES = {"isolated", "existing_cdp"}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _clean_targets(targets: Iterable[str] | None) -> tuple[str, ...]:
    values = tuple(str(item).strip() for item in (targets or ()) if str(item).strip())
    for value in values:
        if "," in value:
            raise AdapterError(
                "INVALID_REQUEST",
                "Each target must be a separate list item and cannot contain a comma.",
            )
        if any(ord(char) < 32 for char in value):
            raise AdapterError(
                "INVALID_REQUEST", "Targets cannot contain control characters."
            )
        if len(value) > 2_048:
            raise AdapterError("INVALID_REQUEST", "A target exceeds 2,048 characters.")
    if len(values) > 20:
        raise AdapterError("INVALID_REQUEST", "At most 20 targets are allowed per run.")
    return values


@dataclass(frozen=True, slots=True)
class CollectRequest:
    platform: str
    mode: str
    query: str | None
    targets: tuple[str, ...]
    login_type: str
    max_items: int
    include_comments: bool
    include_nested_comments: bool
    max_comments_per_item: int
    headless: bool
    browser_mode: str
    start_page: int
    timeout_minutes: int
    request_id: str | None

    @classmethod
    def create(
        cls,
        *,
        platform: str,
        mode: str,
        query: str | None = None,
        targets: Iterable[str] | None = None,
        login_type: str = "qrcode",
        max_items: int = 20,
        include_comments: bool = True,
        include_nested_comments: bool = False,
        max_comments_per_item: int = 50,
        headless: bool = False,
        browser_mode: str = "isolated",
        start_page: int = 1,
        timeout_minutes: int = 30,
        request_id: str | None = None,
    ) -> CollectRequest:
        platform = str(platform).strip().lower()
        mode = str(mode).strip().lower()
        login_type = str(login_type).strip().lower()
        browser_mode = str(browser_mode).strip().lower()
        query = query.strip() if isinstance(query, str) and query.strip() else None
        clean_targets = _clean_targets(targets)

        if platform not in PLATFORMS:
            raise AdapterError(
                "INVALID_REQUEST",
                f"Unsupported platform: {platform!r}. Supported: {', '.join(sorted(PLATFORMS))}.",
            )
        if mode not in MODES:
            raise AdapterError(
                "INVALID_REQUEST", "mode must be search, detail, or creator."
            )
        if login_type not in LOGIN_TYPES:
            raise AdapterError(
                "INVALID_REQUEST",
                "login_type must be qrcode; phone and cookie login are intentionally unavailable.",
            )
        if browser_mode not in BROWSER_MODES:
            raise AdapterError(
                "INVALID_REQUEST",
                "browser_mode must be isolated or existing_cdp.",
            )
        if mode == "search":
            if query is None:
                raise AdapterError(
                    "INVALID_REQUEST", "query is required in search mode."
                )
            if len(query) > 500:
                raise AdapterError(
                    "INVALID_REQUEST", "query cannot exceed 500 characters."
                )
            if "," in query:
                raise AdapterError(
                    "INVALID_REQUEST",
                    "query cannot contain a comma because MediaCrawler treats it as multiple searches.",
                )
            if clean_targets:
                raise AdapterError(
                    "INVALID_REQUEST", "targets are not accepted in search mode."
                )
        else:
            if not clean_targets:
                raise AdapterError(
                    "INVALID_REQUEST", f"targets are required in {mode} mode."
                )
            if query is not None:
                raise AdapterError(
                    "INVALID_REQUEST", f"query is not accepted in {mode} mode."
                )
            if mode == "creator" and len(clean_targets) > 5:
                raise AdapterError(
                    "INVALID_REQUEST", "At most 5 creator targets are allowed per run."
                )
        if not 1 <= max_items <= 100:
            raise AdapterError(
                "INVALID_REQUEST", "max_items must be between 1 and 100."
            )
        if not 0 <= max_comments_per_item <= 200:
            raise AdapterError(
                "INVALID_REQUEST", "max_comments_per_item must be between 0 and 200."
            )
        if include_nested_comments and not include_comments:
            raise AdapterError(
                "INVALID_REQUEST",
                "include_nested_comments requires include_comments=true.",
            )
        if not 1 <= start_page <= 100:
            raise AdapterError(
                "INVALID_REQUEST", "start_page must be between 1 and 100."
            )
        if not 1 <= timeout_minutes <= 120:
            raise AdapterError(
                "INVALID_REQUEST", "timeout_minutes must be between 1 and 120."
            )
        if request_id is not None and not _REQUEST_ID.fullmatch(request_id):
            raise AdapterError(
                "INVALID_REQUEST",
                "request_id must be 1-64 letters, digits, dots, underscores, or hyphens.",
            )

        return cls(
            platform=platform,
            mode=mode,
            query=query,
            targets=clean_targets,
            login_type=login_type,
            max_items=max_items,
            include_comments=include_comments,
            include_nested_comments=include_nested_comments,
            max_comments_per_item=max_comments_per_item,
            headless=headless,
            browser_mode=browser_mode,
            start_page=start_page,
            timeout_minutes=timeout_minutes,
            request_id=request_id,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["targets"] = list(self.targets)
        return value

    def fingerprint(self) -> str:
        value = self.public_dict()
        value.pop("request_id", None)
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
