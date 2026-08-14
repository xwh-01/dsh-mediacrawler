from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


async def _launch(chromium: Any, name: str, channel: str | None) -> dict[str, Any]:
    profile = Path(tempfile.mkdtemp(prefix=f"dsh-mediacrawler-{name}-"))
    context = None
    try:
        options: dict[str, Any] = {"headless": True}
        if channel is not None:
            options["channel"] = channel
        context = await chromium.launch_persistent_context(str(profile), **options)
        return {"browser": name, "passed": True}
    except Exception as exc:  # noqa: BLE001 - probe must report dependency failures
        error = str(exc).splitlines()[0] or type(exc).__name__
        return {"browser": name, "passed": False, "error": error}
    finally:
        if context is not None:
            await context.close()
        shutil.rmtree(profile, ignore_errors=True)


async def probe() -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return {
            "passed": False,
            "checks": [],
            "error": f"Playwright import failed: {exc}",
        }

    async with async_playwright() as playwright:
        checks = [
            await _launch(playwright.chromium, "system-chrome", "chrome"),
        ]
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def main() -> None:
    result = asyncio.run(probe())
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
