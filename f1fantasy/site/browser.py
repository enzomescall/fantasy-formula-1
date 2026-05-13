from __future__ import annotations

from playwright.sync_api import BrowserContext


F1_DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


def launch_persistent_context(*, playwright, profile_dir: str, headful: bool) -> BrowserContext:
    # Use a desktop-ish viewport. The F1 Fantasy UI changes DOM significantly on narrow viewports,
    # which makes selectors brittle (e.g., add buttons/rows differ in mobile layout).
    ctx = playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=(not headful),
        viewport={"width": 1280, "height": 720},
        user_agent=F1_DESKTOP_UA,
        locale="en-US",
        timezone_id="America/New_York",
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(
        """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'platform', { get: () => 'Linux x86_64' });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
        """.strip()
    )
    return ctx
