"""Minimal bootstrap executed by MediaCrawler's Python environment.

The adapter sends query and target values over stdin so they never appear in the
process command line. This module intentionally uses only the standard library.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import sys
from functools import wraps
from pathlib import Path
from typing import Any

_DETAIL_ATTRIBUTES = {
    "xhs": "XHS_SPECIFIED_NOTE_URL_LIST",
    "dy": "DY_SPECIFIED_ID_LIST",
    "ks": "KS_SPECIFIED_ID_LIST",
    "bili": "BILI_SPECIFIED_ID_LIST",
    "wb": "WEIBO_SPECIFIED_ID_LIST",
    "tieba": "TIEBA_SPECIFIED_ID_LIST",
    "zhihu": "ZHIHU_SPECIFIED_ID_LIST",
}
_CREATOR_ATTRIBUTES = {
    "xhs": "XHS_CREATOR_ID_LIST",
    "dy": "DY_CREATOR_ID_LIST",
    "ks": "KS_CREATOR_ID_LIST",
    "bili": "BILI_CREATOR_ID_LIST",
    "wb": "WEIBO_CREATOR_ID_LIST",
    "tieba": "TIEBA_CREATOR_URL_LIST",
    "zhihu": "ZHIHU_CREATOR_URL_LIST",
}


def _read_spec() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(256 * 1024 + 1)
    if not raw or len(raw) > 256 * 1024:
        raise RuntimeError("Missing or oversized adapter launch specification")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Invalid adapter launch specification")
    return value


def _tieba_detail(value: str) -> str:
    match = re.search(r"/p/(\d+)", value)
    return match.group(1) if match else value


def _tieba_creator(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    return f"https://tieba.baidu.com/home/main?id={value}"


def _force_system_chrome() -> None:
    from playwright.async_api import BrowserType  # type: ignore[import-not-found]

    original_launch = BrowserType.launch
    original_persistent = BrowserType.launch_persistent_context

    @wraps(original_launch)
    async def launch(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("channel", "chrome")
        return await original_launch(self, *args, **kwargs)

    @wraps(original_persistent)
    async def launch_persistent_context(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("channel", "chrome")
        return await original_persistent(self, *args, **kwargs)

    BrowserType.launch = launch
    BrowserType.launch_persistent_context = launch_persistent_context


def main() -> None:
    spec = _read_spec()
    root = Path(str(spec.get("root", ""))).expanduser().resolve()
    main_file = root / "main.py"
    if not main_file.is_file():
        raise RuntimeError("MediaCrawler main.py is unavailable")

    platform = str(spec.get("platform", ""))
    mode = str(spec.get("mode", ""))
    browser_mode = str(spec.get("browser_mode", "isolated"))
    browser_profile_template = str(spec.get("browser_profile_template", ""))
    query = spec.get("query")
    targets = spec.get("targets") or []
    if not isinstance(targets, list) or not all(
        isinstance(item, str) for item in targets
    ):
        raise RuntimeError("Invalid adapter target list")

    os.chdir(root)
    sys.path.insert(0, str(root))
    import config  # type: ignore[import-not-found]

    if browser_mode == "isolated":
        if not browser_profile_template or "%s" not in browser_profile_template:
            raise RuntimeError("Missing isolated browser profile template")
        config.ENABLE_CDP_MODE = False
        config.SAVE_LOGIN_STATE = True
        config.USER_DATA_DIR = browser_profile_template
        _force_system_chrome()
    elif browser_mode == "existing_cdp":
        config.ENABLE_CDP_MODE = True
        config.CDP_CONNECT_EXISTING = True
    else:
        raise RuntimeError("Invalid adapter browser mode")

    if mode == "search":
        config.KEYWORDS = str(query or "")
    elif mode == "detail":
        if platform == "tieba":
            targets = [_tieba_detail(item) for item in targets]
        setattr(config, _DETAIL_ATTRIBUTES[platform], targets)
    elif mode == "creator":
        if platform == "tieba":
            targets = [_tieba_creator(item) for item in targets]
        setattr(config, _CREATOR_ATTRIBUTES[platform], targets)
    else:
        raise RuntimeError("Invalid adapter collection mode")

    sys.argv[0] = str(main_file)
    runpy.run_path(str(main_file), run_name="__main__")


if __name__ == "__main__":
    main()
