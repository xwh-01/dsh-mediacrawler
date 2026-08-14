from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import config
from playwright.async_api import BrowserType


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fake MediaCrawler CLI for adapter tests"
    )
    parser.add_argument("--platform", required=True)
    parser.add_argument("--lt", required=True)
    parser.add_argument("--type", required=True)
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--get_comment", required=True)
    parser.add_argument("--get_sub_comment", required=True)
    parser.add_argument("--headless", required=True)
    parser.add_argument("--save_data_option", required=True)
    parser.add_argument("--crawler_max_notes_count", required=True, type=int)
    parser.add_argument("--max_comments_count_singlenotes", required=True, type=int)
    parser.add_argument("--max_concurrency_num", required=True, type=int)
    parser.add_argument("--save_data_path", required=True)
    parser.add_argument("--enable_ip_proxy", required=True)
    parser.add_argument("--keywords")
    parser.add_argument("--specified_id")
    parser.add_argument("--creator_id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configured_targets = {
        ("xhs", "detail"): config.XHS_SPECIFIED_NOTE_URL_LIST,
        ("dy", "detail"): config.DY_SPECIFIED_ID_LIST,
        ("ks", "detail"): config.KS_SPECIFIED_ID_LIST,
        ("bili", "detail"): config.BILI_SPECIFIED_ID_LIST,
        ("wb", "detail"): config.WEIBO_SPECIFIED_ID_LIST,
        ("tieba", "detail"): config.TIEBA_SPECIFIED_ID_LIST,
        ("zhihu", "detail"): config.ZHIHU_SPECIFIED_ID_LIST,
        ("xhs", "creator"): config.XHS_CREATOR_ID_LIST,
        ("dy", "creator"): config.DY_CREATOR_ID_LIST,
        ("ks", "creator"): config.KS_CREATOR_ID_LIST,
        ("bili", "creator"): config.BILI_CREATOR_ID_LIST,
        ("wb", "creator"): config.WEIBO_CREATOR_ID_LIST,
        ("tieba", "creator"): config.TIEBA_CREATOR_URL_LIST,
        ("zhihu", "creator"): config.ZHIHU_CREATOR_URL_LIST,
    }
    targets = configured_targets.get((args.platform, args.type), [])
    control = args.keywords or args.specified_id or args.creator_id
    if not control:
        control = (
            config.KEYWORDS
            if args.type == "search"
            else (targets[0] if targets else "")
        )

    print(f"fake crawler started platform={args.platform} mode={args.type}", flush=True)
    print(
        f"browser_mode_cdp={config.ENABLE_CDP_MODE} profile={config.USER_DATA_DIR}",
        flush=True,
    )
    if not config.ENABLE_CDP_MODE:
        browser_type = BrowserType()
        context = asyncio.run(
            browser_type.launch_persistent_context("fake-profile", headless=True)
        )
        asyncio.run(context.close())
        print(f"browser_channel={BrowserType.last_channel}", flush=True)
    print(
        "cookie=session-cookie token=log-token xsec_token=query-token",
        flush=True,
    )

    if control.startswith("hang-qr"):
        print(
            "MediaCrawler INFO - Waiting for scan code login, remaining time is 20s",
            flush=True,
        )
    if control.startswith("hang-dy-qr"):
        print(
            "MediaCrawler INFO - [DouYinLogin.login_by_qrcode] Begin login douyin by qrcode...",
            flush=True,
        )
    if control.startswith("hang"):
        print("waiting until the adapter stops this process", flush=True)
        while True:
            time.sleep(0.1)
    if control == "fail":
        print("requested failure", flush=True)
        return 7
    if control == "no-data":
        print("completed without records", flush=True)
        return 0
    if control == "soft-error":
        print("MediaCrawler ERROR - upstream detail request failed", flush=True)
        return 0
    if control == "qr-error":
        print(
            "MediaCrawler INFO - Login bilibili failed by qrcode login method",
            flush=True,
        )
        return 0
    if control == "dy-qr-error":
        print(
            "MediaCrawler INFO - [DouYinLogin.begin] login failed please confirm ...",
            flush=True,
        )
        return 0
    if control == "partial-error":
        print("MediaCrawler ERROR - one target failed after partial output", flush=True)
    if control == "recovered-login-error":
        print("MediaCrawler ERROR - login state check failed", flush=True)
        print("MediaCrawler INFO - Login successful then wait for redirect", flush=True)

    output_dir = Path(args.save_data_path) / args.platform
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "search_contents_test.jsonl"
    record = {
        "id": "post-1",
        "title": "fixture record",
        "cookie": "raw-cookie-value",
        "nested": {"xsec_token": "raw-xsec-value", "token": "raw-token-value"},
        "url": "https://example.test/post?id=1&xsec_token=url-secret-value",
    }
    output.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {output}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
