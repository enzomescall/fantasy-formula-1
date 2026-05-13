from __future__ import annotations

import re

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

from .. import config
from ..io.artifacts import utcstamp
from ..models import BudgetSnapshot, TransferStatus
from ..site.browser import F1_DESKTOP_UA, launch_persistent_context


def _parse_money_millions(text: str) -> float | None:
    if not text:
        return None

    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*M", text, flags=re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*million", text, flags=re.I)
    if m:
        return float(m.group(1))

    return None


def _dismiss_overlays(page) -> None:
    try:
        for frame in page.frames:
            for label in ["Accept All", "Reject All", "Continue without accepting"]:
                loc = frame.get_by_role("button", name=label)
                if loc.count():
                    loc.first.click(timeout=2000)
                    page.wait_for_timeout(800)
                    return
    except Exception:
        pass

    for label in ["Cancel", "Close", "×"]:
        try:
            loc = page.get_by_role("button", name=label)
            if loc.count():
                loc.first.click(force=True, timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def _submit_formula1_login(page) -> None:
    """Fill F1 account credentials and submit in the same way a user does.

    The Formula 1 account page appears sensitive to immediate forced button clicks:
    clicking SIGN IN right after Playwright fill() can produce a generic
    "Sorry something went wrong" error. A short settle delay followed by Enter
    from the password field has proven closer to the manual login flow.
    """

    page.locator('input[name="Login"]').fill(config.F1_EMAIL)
    page.wait_for_timeout(700)
    password = page.locator('input[name="Password"]')
    password.fill(config.F1_PASSWORD)
    page.wait_for_timeout(1200)
    password.press("Enter")


def _clear_formula1_auth_state(page) -> None:
    """Clear stale F1 account state that can poison a persistent profile login."""

    try:
        page.context.clear_cookies()
    except Exception:
        pass
    try:
        page.goto(config.F1_LOGIN_URL, wait_until="domcontentloaded")
        page.evaluate("""() => { localStorage.clear(); sessionStorage.clear(); }""")
    except Exception:
        pass


def _ensure_logged_in(page) -> None:
    body = ""
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""

    looks_logged_out = (
        "SIGN IN" in body and "REGISTER" in body and "Pick your team" in body
    ) or ("account.formula1.com" in (page.url or ""))

    if not looks_logged_out:
        return

    if not config.F1_EMAIL or not config.F1_PASSWORD:
        raise RuntimeError("F1 login required but F1_EMAIL/F1_PASSWORD are not configured")

    last_body_after = ""
    for attempt in range(2):
        page.goto(config.F1_LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        _dismiss_overlays(page)
        _submit_formula1_login(page)
        page.wait_for_timeout(8000)
        if "my-account" in (page.url or "") or "fantasy.formula1.com" in (page.url or ""):
            return
        last_body_after = page.locator("body").inner_text(timeout=5000)
        if attempt == 0 and "Sorry something went wrong" in last_body_after:
            _clear_formula1_auth_state(page)
            page.wait_for_timeout(1000)
            continue
        break
    raise RuntimeError(f"Login did not complete successfully. URL={page.url} BODY={last_body_after[:400]}")


def _open_logged_in_stealth_page(*, playwright, url: str):
    last_err = None
    for _ in range(3):
        browser = playwright.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        ctx = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent=F1_DESKTOP_UA,
            locale='en-US',
            timezone_id='America/New_York',
        )
        ctx.add_init_script(
            """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'platform', { get: () => 'Linux x86_64' });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
            """.strip()
        )
        page = ctx.new_page()
        page.goto(config.F1_LOGIN_URL, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        _dismiss_overlays(page)
        _submit_formula1_login(page)
        page.wait_for_timeout(8000)
        if 'my-account' in (page.url or '') or 'fantasy.formula1.com' in (page.url or ''):
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_timeout(5000)
            return browser, ctx, page
        body_after = page.locator('body').inner_text(timeout=5000)
        last_err = f"Login did not complete successfully. URL={page.url} BODY={body_after[:400]}"
        browser.close()
    raise RuntimeError(last_err or 'Login did not complete successfully')


def _open_team_page_with_profile(*, playwright, team_id: int, profile_dir: str, headful: bool):
    """Open the fantasy team page using the caller's persistent profile.

    This preserves the manual/headful-login workflow. Credentials are only used by
    _ensure_logged_in when the persistent profile is actually logged out.
    """

    url = config.FANTASY_TEAM_URL.format(team_id=team_id)
    ctx = launch_persistent_context(playwright=playwright, profile_dir=profile_dir, headful=headful)
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        _dismiss_overlays(page)
        _ensure_logged_in(page)
        if url not in (page.url or ""):
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            _dismiss_overlays(page)
        return ctx, page
    except Exception:
        ctx.close()
        raise


def _parse_selected_price_values(text: str) -> list[float]:
    """Extract selected-team prices from a scoped formation/team text block."""

    if not text:
        return []
    if re.search(r"\b(available\s+(drivers?|constructors?)|driver\s+market|constructor\s+market|pick\s+a)\b", text, flags=re.I):
        return []

    prices: list[float] = []
    skip_next_money = False
    for line in text.splitlines():
        if re.search(r"\b(cost\s*cap|budget|bank|remaining)\b", line, flags=re.I):
            skip_next_money = "$" not in line
            continue
        if "$" not in line:
            continue
        if skip_next_money:
            skip_next_money = False
            continue
        if re.search(r"\b(available|market|pick|select|transfers?)\b", line, flags=re.I):
            continue
        for m in re.finditer(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*M", line, flags=re.I):
            prices.append(float(m.group(1)))

    # A valid F1 Fantasy selected team has 5 drivers + 2 constructors. The
    # current site shows each selected asset as two money values: asset price
    # followed by valuation change, e.g. "$24.0M" then "$0.3M". In that layout
    # a clean selected-team region has 14 prices, so keep every first value.
    if len(prices) == 14:
        prices = prices[::2]

    # If the scoped text does not look like a selected team, fail safe rather
    # than using a market list or the whole document body.
    if len(prices) != 7:
        return []
    return prices


def _best_selected_price_values(region_texts: list[str]) -> list[float]:
    for txt in region_texts or []:
        prices = _parse_selected_price_values(txt)
        if prices:
            return prices
    return []


def scrape_budget_snapshot(*, team_id: int, profile_dir: str, headful: bool) -> BudgetSnapshot:
    """Scrape remaining budget and infer total cap from the official team page.

    cap ≈ remaining + sum(selected driver/constructor prices)

    Returns BudgetSnapshot(remaining_m, used_m, cap_m)
    """

    with sync_playwright() as p:
        ctx, page = _open_team_page_with_profile(playwright=p, team_id=team_id, profile_dir=profile_dir, headful=headful)

        try:
            try:
                page.wait_for_selector('text=Cost Cap', timeout=10000)
            except PwTimeout:
                _dismiss_overlays(page)
                try:
                    if page.locator('text=Manage your team').count():
                        page.locator('text=Manage your team').first.click(force=True, timeout=5000)
                        page.wait_for_timeout(7000)
                except Exception:
                    pass

            try:
                page.wait_for_selector('text=Cost Cap', timeout=60000)
            except PwTimeout:
                raise RuntimeError(f"Could not load team page / budget widget after login check. URL={page.url}")

            remaining = None
            try:
                txt = page.locator('body').inner_text(timeout=5000)
                m = re.search(r"Cost\s*Cap:\s*\$\s*([0-9]+(?:\.[0-9]+)?)\s*M", txt, flags=re.I)
                if m:
                    remaining = float(m.group(1))
            except Exception:
                remaining = None

            if remaining is None:
                html = page.content()
                m = re.search(
                    r"Cost\s*Cap:\s*</span><em>\$\s*([0-9]+(?:\.[0-9]+)?)\s*M",
                    html,
                    flags=re.I,
                )
                if m:
                    remaining = float(m.group(1))

            region_texts = page.evaluate(
                r"""() => {
                  const selectors = [
                    'div.si-cmo__container-lhs',
                    '[class*="formation" i]',
                    '[class*="pitch" i]',
                    '[class*="lineup" i]',
                    '[class*="selected" i][class*="team" i]',
                    '[class*="my-team" i]',
                    'div.si-cmo__container'
                  ];
                  const seen = new Set();
                  const out = [];
                  for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                      if (seen.has(el)) continue;
                      seen.add(el);
                      const txt = el.innerText || '';
                      if ((txt.match(/\$\s*[0-9]+(?:\.[0-9]+)?\s*M/gi) || []).length >= 7) {
                        out.push(txt);
                      }
                    }
                  }
                  return out;
                }"""
            )
            selected_prices = _best_selected_price_values(region_texts)
            if not selected_prices:
                raise RuntimeError("Could not parse selected team prices from scoped formation/team region")
            used = float(sum(selected_prices))
        finally:
            ctx.close()

    if remaining is None:
        raise RuntimeError("Could not parse remaining Cost Cap from page")

    cap = remaining + used
    return BudgetSnapshot(
        remaining_m=round(float(remaining), 3),
        used_m=round(float(used), 3),
        cap_m=round(float(cap), 3),
        source="fantasy.formula1.com",
    )


def _parse_transfer_status_text(txt: str) -> tuple[int | None, int | None]:
    if not txt:
        return None, None

    # Free transfers. Current site can render either "2 free transfers" or
    # stacked labels like "Free Transfers\n2 of 2".
    m = re.search(r"(?im)(?:^\s*|\byou\s+have\s+)(\d+)\s+free\s+transfers?\b", txt)
    if not m:
        m = re.search(r"\bfree\s+transfers?\b\s*(\d+)\s+of\s+\d+", txt, flags=re.I)
    free = int(m.group(1)) if m else None

    # Penalty points per extra transfer (if shown)
    # Common patterns: "10 pts" near "transfer" / "penalty" or "-10".
    penalty = None
    m = re.search(r"\b(?:penalty|transfer\s+penalty)[^0-9-]{0,20}(-?\d+)\s*(?:pts|points)?\b", txt, flags=re.I)
    if m:
        penalty = abs(int(m.group(1)))

    return free, penalty


def scrape_transfer_status(*, team_id: int, profile_dir: str, headful: bool) -> TransferStatus:
    """Scrape current transfer limits from the official team page."""

    url = config.FANTASY_TEAM_URL.format(team_id=team_id)
    with sync_playwright() as p:
        ctx, page = _open_team_page_with_profile(playwright=p, team_id=team_id, profile_dir=profile_dir, headful=headful)

        try:
            def _team_page_loaded() -> bool:
                return bool(page.locator('div.si-cmo__container').count() or page.locator('text=Cost Cap').count())

            if not _team_page_loaded():
                _dismiss_overlays(page)
                try:
                    if page.locator('text=Manage your team').count():
                        page.locator('text=Manage your team').first.click(force=True, timeout=5000)
                        page.wait_for_timeout(7000)
                except Exception:
                    pass

            if not _team_page_loaded():
                raise RuntimeError(f"Could not load team page after login check. URL={page.url}")

            txt = page.evaluate(
                r"""() => {
                  const root = document.body;
                  return root.innerText || '';
                }"""
            )
        finally:
            ctx.close()

    free, penalty = _parse_transfer_status_text(txt)
    if free is None:
        raise RuntimeError("Could not find 'free transfers' on team page")

    return TransferStatus(
        ts_utc=utcstamp(),
        team_id=team_id,
        free_transfers=int(free),
        penalty_points_per_extra=(int(penalty) if penalty is not None else None),
        url=url,
        source="fantasy.formula1.com",
    )
