#!/usr/bin/env python3
"""F1 Fantasy 2026: sync Pascal GP 1 to an ideal team.

This script uses Playwright to:
- load current team state from https://fantasy.formula1.com/en/my-team/<team_id>
- diff vs an ideal spec (drivers, constructors, boost_driver)
- apply only the required changes
- persist via Continue -> Confirm Changes
- save a local JSON snapshot and archive it into state/history/

Notes
- Avoid automating login. Use a persistent Playwright profile that you log into once.
- This is intentionally "2026-season" targeted, not a fully generic engine.

Example:
  python3 scripts/f1_2026_sync_team.py --team-id 1 --ideal ideal_team.json --headful

First-time login bootstrapping:
  python3 scripts/f1_2026_sync_team.py --team-id 1 --ideal ideal_team.json --headful --no-apply
  # In the opened browser window, log in manually, then close.
"""

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

BASE_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = BASE_DIR / "state"
HISTORY_DIR = STATE_DIR / "history"
ARTIFACTS_DIR = STATE_DIR / "artifacts"

FANTASY_TEAM_URL = "https://fantasy.formula1.com/en/my-team/{team_id}"
FANTASY_HOME_URL = "https://fantasy.formula1.com/en/my-team"


def utcstamp():
    # timezone-aware UTC timestamp (avoids datetime.utcnow() deprecation warnings)
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_filename(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "file"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def as_set(names):
    return set(normalize_name(n) for n in (names or []))


def ensure_dirs():
    for d in (STATE_DIR, HISTORY_DIR, ARTIFACTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def take_screenshot(page, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=True)


def log(msg):
    print(msg, flush=True)


class FantasySync:
    def __init__(self, page, team_id: int, expected_team_name: str | None, run_dir: Path):
        self.page = page
        self.team_id = team_id
        self.expected_team_name = expected_team_name
        self.run_dir = run_dir

    # ---------- navigation & validation ----------
    def goto_team(self):
        url = FANTASY_TEAM_URL.format(team_id=self.team_id)
        self.page.goto(url, wait_until="domcontentloaded")
        # Wait for team-builder content to render (important when reusing copied cookies/profile)
        # We wait for a known item from the available-driver list to ensure the SPA finished rendering.
        try:
            self.page.wait_for_selector('img[alt="Max Verstappen"]', timeout=45000)
        except PwTimeout:
            # fallback: at least the budget/continue area
            self.page.wait_for_selector('text=Cost Cap', timeout=45000)
        self.page.wait_for_timeout(250)
        self._assert_correct_team_page()

    def _assert_correct_team_page(self):
        url = self.page.url
        if f"/my-team/{self.team_id}" not in url:
            raise RuntimeError(f"Not on expected team URL. expected contains /my-team/{self.team_id}, got {url}")

        body_text = (self.page.inner_text("body") or "")
        if "Pascal GP 2" in body_text or "Pascal GP 3" in body_text:
            raise RuntimeError("Safety check failed: page contains Pascal GP 2/3 strings; aborting")

        if self.expected_team_name:
            if self.expected_team_name not in body_text:
                raise RuntimeError(f"Expected team name '{self.expected_team_name}' not found on page")

    # ---------- scraping ----------
    def _selected_names_by_selected_region(self):
        """Return selected driver/constructor names from the *selected* section above the lists.

        With CSS off, it’s visually obvious: selected items live in a container above the available lists.
        In DOM terms, we observed a stable container: `div.si-cmo__container-lhs` that contains exactly
        the selected 5 drivers + 2 constructors as `img[alt]`.

        Fallback: if the container changes, we fall back to "take alts before Max Verstappen".
        """
        js = r"""
() => {
  const preferred = document.querySelector('div.si-cmo__container-lhs');
  const extract = (root) => {
    if (!root) return [];
    const alts = [...root.querySelectorAll('img[alt]')]
      .map(i => (i.getAttribute('alt') || '').trim())
      .filter(Boolean);
    const seen = new Set();
    const uniq = [];
    for (const a of alts) {
      const k = a.toLowerCase();
      if (seen.has(k)) continue;
      seen.add(k);
      uniq.push(a);
    }
    return uniq;
  };

  const preferredAlts = extract(preferred);
  if (preferredAlts.length >= 5) return preferredAlts;

  // fallback: parse first unique alts before available list starts
  const root = document.querySelector('.si-main__row') || document.body;
  const stopAlts = new Set([
    'Max Verstappen','George Russell','Lando Norris','Oscar Piastri','Kimi Antonelli'
  ].map(s => s.toLowerCase()));

  const alts = [];
  for (const img of root.querySelectorAll('img[alt]')) {
    const alt = (img.getAttribute('alt') || '').trim();
    if (!alt) continue;
    const k = alt.toLowerCase();
    if (stopAlts.has(k)) break;
    if (k === 'australia' || k === 'melbourne' || k.includes('formula 1') || k.includes('f1 fantasy')) continue;
    alts.push(alt);
  }
  // unique preserving order
  const seen = new Set();
  const uniq = [];
  for (const a of alts) {
    const k = a.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    uniq.push(a);
  }
  return uniq;
}
"""
        return self.page.evaluate(js)

    def get_current_state(self):
        """Scrape current state from the team page."""
        # Selected drivers+constructors are rendered inside the budget region
        selected = self._selected_names_by_selected_region()

        # Heuristic split: drivers are people names (contain space), constructors are team names (may contain space too),
        # but we know there are exactly 5 drivers + 2 constructors when complete.
        # If incomplete, this list may be shorter.
        drivers = []
        constructors = []
        for n in selected:
            # Constructors commonly match known teams list; keep a simple whitelist-based split.
            if normalize_name(n) in {
                "mclaren",
                "ferrari",
                "mercedes",
                "red bull racing",
                "alpine",
                "williams",
                "aston martin",
                "haas f1 team",
                "audi",
                "racing bulls",
                "cadillac",
            }:
                constructors.append(n)
            else:
                drivers.append(n)

        boost = self.get_boost_driver_fallback(drivers)

        return {
            "ts_utc": utcstamp(),
            "team_id": self.team_id,
            "team_name": self.expected_team_name,
            "drivers": drivers,
            "constructors": constructors,
            "boost_driver": boost,
            "url": self.page.url,
            "source": "site",
        }

    def get_boost_driver_fallback(self, selected_drivers):
        """Try to identify boosted driver.

        Primary method: find a selected driver card that contains visible '2x'.
        Fallback: regex on body text like '2x G.BORTOLETO'.
        """
        # Try within selected driver cards: locate any element with text 2x then grab nearest img alt.
        two_x = self.page.locator(':text("2x")')
        if two_x.count() > 0:
            # find a nearby selected driver img
            el = two_x.first
            card = el.locator("xpath=ancestor::li[1]")
            img = card.locator("img[alt]").first
            if img.count() > 0:
                alt = img.get_attribute("alt")
                if alt:
                    return alt

        body = (self.page.inner_text("body") or "")
        m = re.search(r"2x\s*([A-Z]\.[A-Z]+)", body, flags=re.I)
        if m and selected_drivers:
            # map abbreviation to selected driver if possible
            abbr = m.group(1).lower()
            for d in selected_drivers:
                parts = d.lower().split()
                if len(parts) >= 2:
                    cand = f"{parts[0][0]}.{parts[-1]}".lower()
                    if cand == abbr:
                        return d
        return None

    # ---------- interactions ----------
    def click_drivers_tab(self):
        self.page.evaluate(
            """() => {
              const a = [...document.querySelectorAll('a')].find(x => (x.textContent||'').trim().toLowerCase()==='drivers');
              if (a) { a.scrollIntoView({block:'center'}); a.click(); return true; }
              return false;
            }"""
        )
        self.page.wait_for_timeout(250)

    def click_constructors_tab(self):
        self.page.evaluate(
            """() => {
              const a = [...document.querySelectorAll('a')].find(x => (x.textContent||'').trim().toLowerCase()==='constructors');
              if (a) { a.scrollIntoView({block:'center'}); a.click(); return true; }
              return false;
            }"""
        )
        self.page.wait_for_timeout(250)

    def remove_selected_driver(self, full_name: str):
        # Scope to the selected team lineup container (.si-formation__container)
        container = self.page.locator('div.si-formation__container').first
        img = container.locator(f'img[alt="{full_name}"]').first
        if img.count() == 0:
            return False
        card = img.locator("xpath=ancestor::li[1]")

        # remove button is an icon button containing f1i-close
        btn = card.locator('button:has(i.f1i-close)').first
        if btn.count() == 0:
            btns = card.locator("button")
            if btns.count() == 0:
                return False
            btn = btns.nth(btns.count() - 1)

        btn.scroll_into_view_if_needed()
        btn.click(force=True)
        # wait until removed from selected lineup
        try:
            self.page.wait_for_selector(f'div.si-formation__container img[alt="{full_name}"]', state="detached", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(350)
        return True

    def remove_selected_constructor(self, name: str):
        container = self.page.locator('div.si-formation__container').first
        img = container.locator(f'img[alt="{name}"]').first
        if img.count() == 0:
            return False
        card = img.locator("xpath=ancestor::li[1]")

        btn = card.locator('button:has(i.f1i-close)').first
        if btn.count() == 0:
            btns = card.locator("button")
            if btns.count() == 0:
                return False
            btn = btns.nth(btns.count() - 1)

        btn.scroll_into_view_if_needed()
        btn.click(force=True)
        # wait until removed from selected lineup
        try:
            self.page.wait_for_selector(f'div.si-formation__container img[alt="{name}"]', state="detached", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(350)
        return True

    def add_driver_via_search_list(self, full_name: str):
        sb = self.page.locator('input[aria-label="Search Drivers"], input[placeholder*="Search" i]').first
        if sb.count() == 0:
            raise RuntimeError("Search Drivers box not found")

        # Ensure the list is mounted (some parts lazy-render after scroll)
        sb.scroll_into_view_if_needed()
        self.page.evaluate("() => window.scrollBy(0, 600)")
        self.page.wait_for_timeout(250)

        # Filter (best effort; list is virtualized)
        sb.fill(full_name)
        self.page.evaluate(
            """(q) => {
              const inp = document.querySelector('input[aria-label="Search Drivers"]');
              if (!inp) return false;
              inp.value = q;
              inp.dispatchEvent(new Event('input', {bubbles:true}));
              return true;
            }""",
            full_name,
        )

        # Poll until the add button becomes available+enabled, then click it.
        deadline_ms = 20000
        step_ms = 500
        waited = 0
        last = None
        clicked = False
        while waited <= deadline_ms:
            last = self.page.evaluate(
                """(name) => {
                  const rows = [...document.querySelectorAll('li')].filter(li => {
                    const img = li.querySelector('img[alt]');
                    if (!img) return false;
                    if ((img.getAttribute('alt')||'') !== name) return false;
                    const hasClose = !!li.querySelector('i.f1i-close');
                    const addBtn = li.querySelector('button.si-btn__primary-dark');
                    return !hasClose && !!addBtn;
                  });
                  if (!rows.length) return {ok:false, err:'no available row with add button'};
                  const row = rows[rows.length-1];
                  row.scrollIntoView({block:'center'});
                  const btn = row.querySelector('button.si-btn__primary-dark');
                  if (!btn) return {ok:false, err:'no add btn'};
                  const cls = (btn.className||'').toString();
                  const disabled = !!btn.disabled || cls.includes('si-disabled');
                  return {ok:true, disabled, className: cls};
                }""",
                full_name,
            )
            if last and last.get('ok') and (not last.get('disabled')):
                break

            # scroll to help virtualization load the row
            self.page.evaluate("() => window.scrollBy(0, 900)")
            self.page.wait_for_timeout(step_ms)
            waited += step_ms

        if not last or not last.get('ok'):
            take_screenshot(self.page, self.run_dir / f"add_driver_no_row_{safe_filename(full_name)}.png")
            raise RuntimeError(f"Driver '{full_name}' row not found for add")

        if last.get('disabled'):
            take_screenshot(self.page, self.run_dir / f"add_driver_still_disabled_{safe_filename(full_name)}.png")
            raise RuntimeError(f"Driver '{full_name}' add button stayed disabled: {last}")

        # Click
        res = self.page.evaluate(
            """(name) => {
              const rows = [...document.querySelectorAll('li')].filter(li => {
                const img = li.querySelector('img[alt]');
                if (!img) return false;
                if ((img.getAttribute('alt')||'') !== name) return false;
                const hasClose = !!li.querySelector('i.f1i-close');
                const addBtn = li.querySelector('button.si-btn__primary-dark');
                return !hasClose && !!addBtn;
              });
              if (!rows.length) return {ok:false, err:'no available row with add button'};
              const row = rows[rows.length-1];
              row.scrollIntoView({block:'center'});
              const btn = row.querySelector('button.si-btn__primary-dark');
              if (!btn) return {ok:false, err:'no add btn'};
              const cls = (btn.className||'').toString();
              const disabled = !!btn.disabled || cls.includes('si-disabled');
              if (disabled) return {ok:false, err:'add btn disabled', className: cls};
              btn.click();
              return {ok:true, clicked:true, className: cls};
            }""",
            full_name,
        )

        if not res or not res.get('ok'):
            take_screenshot(self.page, self.run_dir / f"add_driver_failed_{safe_filename(full_name)}.png")
            raise RuntimeError(f"Failed to add driver '{full_name}': {res}")

        self.page.wait_for_selector(f'div.si-formation__container img[alt="{full_name}"]', timeout=20000)
        self.page.wait_for_timeout(250)
        sb.fill("")
        self.page.wait_for_timeout(150)

    def add_constructor_via_search_list(self, name: str):
        sb = self.page.locator('input[aria-label="Search Constructors"], input[placeholder*="Search" i]').first
        if sb.count() == 0:
            raise RuntimeError("Search Constructors box not found")
        sb.fill(name)
        self.page.wait_for_timeout(300)

        # Wait for the constructor add button to become enabled (can lag after removals)
        deadline_ms = 20000
        step_ms = 500
        waited = 0
        last = None
        while waited <= deadline_ms:
            last = self.page.evaluate(
                """(nm) => {
                  const li = [...document.querySelectorAll('li')].find(li => {
                    const img = li.querySelector('img[alt]');
                    if (!img) return false;
                    if ((img.getAttribute('alt')||'') !== nm) return false;
                    return !!li.querySelector('button.si-btn__primary-dark');
                  });
                  if (!li) return {ok:false, err:'no li'};
                  li.scrollIntoView({block:'center'});
                  const btn = li.querySelector('button.si-btn__primary-dark');
                  const cls = (btn.className||'').toString();
                  const disabled = !!btn.disabled || cls.includes('si-disabled');
                  return {ok:true, disabled, className: cls};
                }""",
                name,
            )
            if last and last.get("ok") and (not last.get("disabled")):
                break
            self.page.wait_for_timeout(step_ms)
            waited += step_ms

        if not last or not last.get("ok"):
            take_screenshot(self.page, self.run_dir / f"add_constructor_no_row_{safe_filename(name)}.png")
            raise RuntimeError(f"Constructor '{name}' row not found for add")

        if last.get("disabled"):
            take_screenshot(self.page, self.run_dir / f"add_constructor_still_disabled_{safe_filename(name)}.png")
            raise RuntimeError(f"Constructor '{name}' add button stayed disabled: {last}")

        # Click the available-list add button (primary-dark) for the constructor.
        res = self.page.evaluate(
            """(nm) => {
              const li = [...document.querySelectorAll('li')].find(li => {
                const img = li.querySelector('img[alt]');
                if (!img) return false;
                if ((img.getAttribute('alt')||'') !== nm) return false;
                return !!li.querySelector('button.si-btn__primary-dark');
              });
              if (!li) return {ok:false, err:'no li'};
              li.scrollIntoView({block:'center'});
              const btn = li.querySelector('button.si-btn__primary-dark');
              if (!btn) return {ok:false, err:'no add btn'};
              const cls = (btn.className||'').toString();
              const disabled = !!btn.disabled || cls.includes('si-disabled');
              if (disabled) return {ok:false, err:'add btn disabled', className: cls};
              btn.click();
              return {ok:true, clicked:'addBtn', className: cls};
            }""",
            name,
        )
        if not res or not res.get('ok'):
            take_screenshot(self.page, self.run_dir / f"add_constructor_failed_{safe_filename(name)}.png")
            raise RuntimeError(f"Failed to add constructor '{name}': {res}")

        # Wait until constructor appears in selected lineup container
        self.page.wait_for_selector(f'div.si-formation__container img[alt="{name}"]', timeout=15000)

        self.page.wait_for_timeout(250)
        sb.fill("")
        self.page.wait_for_timeout(150)

    def set_boost(self, full_name: str):
        # Click selected driver image inside selected team lineup container
        container = self.page.locator('div.si-formation__container').first
        img = container.locator(f'img[alt="{full_name}"]').first
        if img.count() == 0:
            raise RuntimeError(f"Boost target driver '{full_name}' not found in selected lineup container")
        img.scroll_into_view_if_needed()
        (img.locator("xpath=ancestor::button[1]").first if img.locator("xpath=ancestor::button[1]").count() else img).click()
        self.page.wait_for_timeout(400)

        add_boost = self.page.locator('button:has-text("Add Boost")')
        if add_boost.count() > 0:
            add_boost.first.click()
            self.page.wait_for_timeout(300)

        done = self.page.locator('button:has-text("Done")')
        if done.count() > 0:
            done.first.click()
            self.page.wait_for_timeout(250)

    def persist_continue_confirm(self):
        # Click Continue, wait for Team Changes modal, click Confirm
        cont = self.page.locator('button:has-text("Continue")').first
        if cont.count() == 0:
            raise RuntimeError("Continue button not found")
        # If disabled, fail fast with artifact
        if cont.is_disabled():
            take_screenshot(self.page, self.run_dir / "continue_disabled.png")
            raise RuntimeError("Continue button is disabled; team likely invalid or add/remove did not apply")
        cont.click(force=True)

        # modal
        self.page.wait_for_timeout(500)
        try:
            self.page.wait_for_selector('text=Team Changes', timeout=15000)
        except PwTimeout:
            # still take a screenshot for debugging
            take_screenshot(self.page, self.run_dir / "continue_no_modal.png")
            raise

        take_screenshot(self.page, self.run_dir / "team_changes_modal.png")

        confirm = self.page.locator('button:has-text("Confirm")').first
        if confirm.count() == 0:
            raise RuntimeError("Confirm Changes button not found in modal")
        confirm.click()

        # Should return to home list
        self.page.wait_for_timeout(1500)
        self.page.goto(FANTASY_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(500)

    # ---------- main sync ----------
    def sync_to_ideal(self, ideal, apply=True):
        self.goto_team()
        self.click_drivers_tab()

        current = self.get_current_state()
        take_screenshot(self.page, self.run_dir / "state_start.png")

        diff = compute_diff(current, ideal)
        write_json(self.run_dir / "diff.json", diff)
        log("Diff computed: " + json.dumps(diff, indent=2))

        if not apply:
            return current, diff

        # If truly no-op, just return current (still useful for writing local snapshot)
        if diff.get("noop"):
            return current, diff

        # Removals first (free budget before any adds)
        # Drivers removals
        self.click_drivers_tab()
        for d in diff["drivers_remove"]:
            log(f"Removing driver: {d}")
            self.remove_selected_driver(d)
        take_screenshot(self.page, self.run_dir / "after_remove_drivers.png")

        # Constructors removals
        self.click_constructors_tab()
        for c in diff["constructors_remove"]:
            log(f"Removing constructor: {c}")
            self.remove_selected_constructor(c)
        take_screenshot(self.page, self.run_dir / "after_remove_constructors.png")

        # Adds next (constructors first, then drivers)
        for c in diff["constructors_add"]:
            log(f"Adding constructor via list/search: {c}")
            self.add_constructor_via_search_list(c)
        take_screenshot(self.page, self.run_dir / "after_add_constructors.png")

        self.click_drivers_tab()
        for d in diff["drivers_add"]:
            log(f"Adding driver via list/search: {d}")
            self.add_driver_via_search_list(d)
        take_screenshot(self.page, self.run_dir / "after_add_drivers.png")

        # Boost (drivers tab)
        if diff["boost_change"]:
            log(f"Setting boost to: {ideal['boost_driver']}")
            self.set_boost(ideal["boost_driver"])
        take_screenshot(self.page, self.run_dir / "after_boost.png")

        # Persist
        self.persist_continue_confirm()
        take_screenshot(self.page, self.run_dir / "home_after_confirm.png")

        # Re-scrape for final state (from team page)
        self.goto_team()
        self.click_drivers_tab()
        final_state = self.get_current_state()
        take_screenshot(self.page, self.run_dir / "state_final.png")

        # Robust verification: final state must match ideal (set equality + boost)
        verify = compute_diff(final_state, ideal)
        write_json(self.run_dir / "diff_final_vs_ideal.json", verify)
        if not verify.get("noop"):
            take_screenshot(self.page, self.run_dir / "verify_failed.png")
            raise RuntimeError("Post-apply verification failed (final state != ideal). See diff_final_vs_ideal.json")

        return final_state, diff


def compute_diff(current_state, ideal):
    cur_dr = current_state.get("drivers", [])
    cur_con = current_state.get("constructors", [])
    cur_boost = current_state.get("boost_driver")

    ideal_dr = ideal.get("drivers", [])
    ideal_con = ideal.get("constructors", [])
    ideal_boost = ideal.get("boost_driver")

    # membership-based diffs
    cur_dr_set = as_set(cur_dr)
    ideal_dr_set = as_set(ideal_dr)

    cur_con_set = as_set(cur_con)
    ideal_con_set = as_set(ideal_con)

    drivers_remove = [d for d in cur_dr if normalize_name(d) not in ideal_dr_set]
    drivers_add = [d for d in ideal_dr if normalize_name(d) not in cur_dr_set]

    constructors_remove = [c for c in cur_con if normalize_name(c) not in ideal_con_set]
    constructors_add = [c for c in ideal_con if normalize_name(c) not in cur_con_set]

    boost_change = (ideal_boost is not None) and (normalize_name(cur_boost) != normalize_name(ideal_boost))

    # no-op check can be strict or relaxed; here: strict membership + boost equality
    noop = (
        cur_dr_set == ideal_dr_set
        and cur_con_set == ideal_con_set
        and not boost_change
    )

    return {
        "noop": noop,
        "drivers_remove": drivers_remove,
        "drivers_add": drivers_add,
        "constructors_remove": constructors_remove,
        "constructors_add": constructors_add,
        "boost_change": boost_change,
        "current_boost": cur_boost,
        "ideal_boost": ideal_boost,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", type=int, default=1)
    parser.add_argument("--ideal", required=True, help="Path to ideal_team.json")
    parser.add_argument("--profile-dir", default=str(BASE_DIR / ".playwright-profile"), help="Persistent Playwright profile dir")
    parser.add_argument("--expected-team-name", default="Pascal GP 1")
    parser.add_argument("--headful", action="store_true", help="Run with a visible browser window")
    parser.add_argument("--no-apply", action="store_true", help="Do not apply changes (just compute diff)")
    parser.add_argument("--force", action="store_true", help="Apply even if local state matches ideal")
    args = parser.parse_args()

    ensure_dirs()

    ideal_path = Path(args.ideal)
    ideal = read_json(ideal_path)
    if not ideal:
        raise SystemExit(f"Ideal spec not found/empty: {ideal_path}")

    required = ["drivers", "constructors", "boost_driver"]
    for k in required:
        if k not in ideal:
            raise SystemExit(f"Ideal spec missing key: {k}")

    # Sanity checks
    if not isinstance(ideal.get("drivers"), list) or len(ideal.get("drivers")) != 5:
        raise SystemExit("Ideal spec must have exactly 5 drivers")
    if not isinstance(ideal.get("constructors"), list) or len(ideal.get("constructors")) != 2:
        raise SystemExit("Ideal spec must have exactly 2 constructors")
    bd = ideal.get("boost_driver")
    if bd and normalize_name(bd) not in as_set(ideal.get("drivers", [])):
        raise SystemExit("Ideal spec boost_driver must be one of the 5 drivers")

    # Local state check
    state_path = STATE_DIR / "team_state.json"
    local = read_json(state_path, default=None)
    if local and not args.force:
        # compare membership + boost
        local_diff = compute_diff(local, ideal)
        if local_diff["noop"]:
            log("Local state already matches ideal; exiting without changes.")
            return 0

    run_ts = utcstamp().replace(":", "-")
    run_dir = ARTIFACTS_DIR / f"run_{run_ts}_team{args.team_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "ideal.json", ideal)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=(not args.headful),
            viewport={"width": 900, "height": 1600},
        )
        page = browser.new_page()

        sync = FantasySync(page, args.team_id, args.expected_team_name, run_dir)

        try:
            final_state, diff = sync.sync_to_ideal(ideal, apply=(not args.no_apply))
        except Exception as e:
            try:
                take_screenshot(page, run_dir / "error.png")
            except Exception:
                pass
            raise
        finally:
            browser.close()

    if args.no_apply:
        log("No-apply run complete.")
        return 0

    # Save latest state + archive
    write_json(state_path, final_state)
    hist_name = f"team_state_{safe_filename(final_state['ts_utc'])}_team{args.team_id}.json"
    shutil.copy2(state_path, HISTORY_DIR / hist_name)

    # Save last applied ideal
    write_json(STATE_DIR / "last_applied.json", {"ts_utc": utcstamp(), "ideal": ideal})

    log(f"Saved state to {state_path} and archived to {HISTORY_DIR / hist_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
