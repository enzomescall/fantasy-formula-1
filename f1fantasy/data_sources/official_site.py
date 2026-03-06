from __future__ import annotations

import re

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

from .. import config
from ..io.artifacts import utcstamp
from ..models import BudgetSnapshot, TransferStatus
from ..site.browser import launch_persistent_context


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


def scrape_budget_snapshot(*, team_id: int, profile_dir: str, headful: bool) -> BudgetSnapshot:
    """Scrape remaining budget and infer total cap from the official team page.

    cap ≈ remaining + sum(selected driver/constructor prices)

    Returns BudgetSnapshot(remaining_m, used_m, cap_m)
    """

    url = config.FANTASY_TEAM_URL.format(team_id=team_id)
    with sync_playwright() as p:
        ctx = launch_persistent_context(playwright=p, profile_dir=profile_dir, headful=headful)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('text=Cost Cap', timeout=60000)
        except PwTimeout:
            ctx.close()
            raise RuntimeError(f"Could not load team page / budget widget. Are we logged in? URL={page.url}")

        remaining = None
        try:
            txt = page.locator("text=Cost Cap").first.locator("xpath=ancestor::section[1]").inner_text()
            remaining = _parse_money_millions(txt)
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

        selected_sum = page.evaluate(
            r"""() => {
              const cont = document.querySelector('div.si-formation__container') || document.body;
              const txt = cont.innerText || '';
              const matches = [...txt.matchAll(/\$\s*([0-9]+(?:\.[0-9]+)?)\s*M/gi)];
              const nums = matches.map(m => parseFloat(m[1])).filter(n => Number.isFinite(n));
              return nums;
            }"""
        )
        used = float(sum(selected_sum or []))

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

    # Free transfers
    m = re.search(r"\b(\d+)\s+free\s+transfers?\b", txt, flags=re.I)
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
        ctx = launch_persistent_context(playwright=p, profile_dir=profile_dir, headful=headful)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")

        # Wait for core team-builder container to exist.
        try:
            page.wait_for_selector('div.si-cmo__container, text=Cost Cap', timeout=60000)
        except PwTimeout:
            ctx.close()
            raise RuntimeError(f"Could not load team page. Are we logged in? URL={page.url}")

        txt = page.evaluate(
            r"""() => {
              const root = document.querySelector('div.si-cmo__container') || document.body;
              return root.innerText || '';
            }"""
        )
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
