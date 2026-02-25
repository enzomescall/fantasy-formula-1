from __future__ import annotations

from playwright.sync_api import BrowserContext


def launch_persistent_context(*, playwright, profile_dir: str, headful: bool) -> BrowserContext:
    return playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=(not headful),
        viewport={"width": 900, "height": 1600},
    )
