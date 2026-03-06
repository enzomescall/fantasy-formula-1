from __future__ import annotations

from playwright.sync_api import BrowserContext


def launch_persistent_context(*, playwright, profile_dir: str, headful: bool) -> BrowserContext:
    # Use a desktop-ish viewport. The F1 Fantasy UI changes DOM significantly on narrow viewports,
    # which makes selectors brittle (e.g., add buttons/rows differ in mobile layout).
    return playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=(not headful),
        viewport={"width": 1280, "height": 720},
    )
