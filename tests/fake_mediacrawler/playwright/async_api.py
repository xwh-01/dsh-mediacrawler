from __future__ import annotations


class _BrowserContext:
    async def close(self) -> None:
        return None


class BrowserType:
    last_channel: str | None = None

    async def launch(self, **options: object) -> _BrowserContext:
        type(self).last_channel = options.get("channel")  # type: ignore[assignment]
        return _BrowserContext()

    async def launch_persistent_context(
        self, user_data_dir: str, **options: object
    ) -> _BrowserContext:
        del user_data_dir
        type(self).last_channel = options.get("channel")  # type: ignore[assignment]
        return _BrowserContext()


class _Chromium(BrowserType):
    pass


class _Playwright:
    chromium = _Chromium()


class _PlaywrightManager:
    async def __aenter__(self) -> _Playwright:
        return _Playwright()

    async def __aexit__(self, *args: object) -> None:
        del args


def async_playwright() -> _PlaywrightManager:
    return _PlaywrightManager()
