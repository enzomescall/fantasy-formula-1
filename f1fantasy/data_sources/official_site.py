from __future__ import annotations

import re

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

from .. import config
from ..models import BudgetSnapshot
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
