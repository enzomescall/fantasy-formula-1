from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PwTimeout

from .. import config
from ..io.artifacts import safe_filename, write_json
from ..logic.diff import compute_diff, normalize_name, as_set


def take_screenshot(page, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=True)


def log(msg: str) -> None:
    print(msg, flush=True)


class FantasySync:
    """Playwright-based syncer for the official F1 Fantasy team page.

    This is a near-direct move of the old scripts/f1_2026_sync_team.py class to keep behavior stable.
    """

    def __init__(self, page, team_id: int, expected_team_name: str | None, run_dir: Path):
        self.page = page
        self.team_id = team_id
        self.expected_team_name = expected_team_name
        self.run_dir = run_dir

    # ---------- navigation & validation ----------
    def goto_team(self):
        url = config.FANTASY_TEAM_URL.format(team_id=self.team_id)
        self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_selector('img[alt="Max Verstappen"]', timeout=45000)
        except PwTimeout:
            self.page.wait_for_selector('text=Cost Cap', timeout=45000)
        self.page.wait_for_timeout(250)
        self._assert_correct_team_page()

    def _assert_correct_team_page(self):
        url = self.page.url
        if f"/my-team/{self.team_id}" not in url:
            raise RuntimeError(
                f"Not on expected team URL. expected contains /my-team/{self.team_id}, got {url}"
            )

        body_text = self.page.inner_text("body") or ""
        if "Pascal GP 2" in body_text or "Pascal GP 3" in body_text:
            raise RuntimeError("Safety check failed: page contains Pascal GP 2/3 strings; aborting")

        if self.expected_team_name:
            if self.expected_team_name not in body_text:
                raise RuntimeError(f"Expected team name '{self.expected_team_name}' not found on page")

    # ---------- scraping ----------
    def _selected_names_by_selected_region(self):
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
        selected = self._selected_names_by_selected_region()

        drivers = []
        constructors = []
        for n in selected:
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
            "ts_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "team_id": self.team_id,
            "team_name": self.expected_team_name,
            "drivers": drivers,
            "constructors": constructors,
            "boost_driver": boost,
            "url": self.page.url,
            "source": "site",
        }

    def get_boost_driver_fallback(self, selected_drivers):
        two_x = self.page.locator(':text("2x")')
        if two_x.count() > 0:
            el = two_x.first
            card = el.locator("xpath=ancestor::li[1]")
            img = card.locator("img[alt]").first
            if img.count() > 0:
                alt = img.get_attribute("alt")
                if alt:
                    return alt

        body = self.page.inner_text("body") or ""
        m = re.search(r"2x\s*([A-Z]\.[A-Z]+)", body, flags=re.I)
        if m and selected_drivers:
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
        container = self.page.locator('div.si-formation__container').first
        img = container.locator(f'img[alt="{full_name}"]').first
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
        try:
            self.page.wait_for_selector(
                f'div.si-formation__container img[alt="{full_name}"]',
                state="detached",
                timeout=15000,
            )
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
        try:
            self.page.wait_for_selector(
                f'div.si-formation__container img[alt="{name}"]',
                state="detached",
                timeout=15000,
            )
        except Exception:
            pass
        self.page.wait_for_timeout(350)
        return True

    def add_driver_via_search_list(self, full_name: str):
        sb = self.page.locator('input[aria-label="Search Drivers"], input[placeholder*="Search" i]').first
        if sb.count() == 0:
            raise RuntimeError("Search Drivers box not found")

        sb.scroll_into_view_if_needed()
        self.page.evaluate("() => window.scrollBy(0, 600)")
        self.page.wait_for_timeout(250)

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

        deadline_ms = 20000
        step_ms = 500
        waited = 0
        last = None
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
            if last and last.get("ok") and (not last.get("disabled")):
                break
            self.page.evaluate("() => window.scrollBy(0, 900)")
            self.page.wait_for_timeout(step_ms)
            waited += step_ms

        if not last or not last.get("ok"):
            take_screenshot(self.page, self.run_dir / f"add_driver_no_row_{safe_filename(full_name)}.png")
            raise RuntimeError(f"Driver '{full_name}' row not found for add")

        if last.get("disabled"):
            take_screenshot(
                self.page, self.run_dir / f"add_driver_still_disabled_{safe_filename(full_name)}.png"
            )
            raise RuntimeError(f"Driver '{full_name}' add button stayed disabled: {last}")

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

        if not res or not res.get("ok"):
            take_screenshot(self.page, self.run_dir / f"add_driver_failed_{safe_filename(full_name)}.png")
            raise RuntimeError(f"Failed to add driver '{full_name}': {res}")

        self.page.wait_for_selector(f'div.si-formation__container img[alt="{full_name}"]', timeout=20000)
        self.page.wait_for_timeout(250)
        sb.fill("")
        self.page.wait_for_timeout(150)

    def add_constructor_via_search_list(self, name: str):
        sb = self.page.locator(
            'input[aria-label="Search Constructors"], input[placeholder*="Search" i]'
        ).first
        if sb.count() == 0:
            raise RuntimeError("Search Constructors box not found")
        sb.fill(name)
        self.page.wait_for_timeout(300)

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
            take_screenshot(
                self.page, self.run_dir / f"add_constructor_still_disabled_{safe_filename(name)}.png"
            )
            raise RuntimeError(f"Constructor '{name}' add button stayed disabled: {last}")

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
        if not res or not res.get("ok"):
            take_screenshot(self.page, self.run_dir / f"add_constructor_failed_{safe_filename(name)}.png")
            raise RuntimeError(f"Failed to add constructor '{name}': {res}")

        self.page.wait_for_selector(f'div.si-formation__container img[alt="{name}"]', timeout=15000)

        self.page.wait_for_timeout(250)
        sb.fill("")
        self.page.wait_for_timeout(150)

    def set_boost(self, full_name: str):
        container = self.page.locator('div.si-formation__container').first
        img = container.locator(f'img[alt="{full_name}"]').first
        if img.count() == 0:
            raise RuntimeError(
                f"Boost target driver '{full_name}' not found in selected lineup container"
            )
        img.scroll_into_view_if_needed()
        (
            img.locator("xpath=ancestor::button[1]").first
            if img.locator("xpath=ancestor::button[1]").count()
            else img
        ).click()
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
        cont = self.page.locator('button:has-text("Continue")').first
        if cont.count() == 0:
            raise RuntimeError("Continue button not found")
        if cont.is_disabled():
            take_screenshot(self.page, self.run_dir / "continue_disabled.png")
            raise RuntimeError("Continue button is disabled; team likely invalid or add/remove did not apply")
        cont.click(force=True)

        self.page.wait_for_timeout(500)
        try:
            self.page.wait_for_selector('text=Team Changes', timeout=15000)
        except PwTimeout:
            take_screenshot(self.page, self.run_dir / "continue_no_modal.png")
            raise

        take_screenshot(self.page, self.run_dir / "team_changes_modal.png")

        confirm = self.page.locator('button:has-text("Confirm")').first
        if confirm.count() == 0:
            raise RuntimeError("Confirm Changes button not found in modal")
        confirm.click()

        self.page.wait_for_timeout(1500)
        self.page.goto(config.FANTASY_HOME_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(500)

    # ---------- main sync ----------
    def sync_to_ideal(self, ideal, apply: bool = True):
        self.goto_team()
        self.click_drivers_tab()

        current = self.get_current_state()
        take_screenshot(self.page, self.run_dir / "state_start.png")

        diff = compute_diff(current, ideal)
        write_json(self.run_dir / "diff.json", diff)
        log("Diff computed: " + json.dumps(diff, indent=2))

        if not apply:
            return current, diff

        if diff.get("noop"):
            return current, diff

        self.click_drivers_tab()
        for d in diff["drivers_remove"]:
            log(f"Removing driver: {d}")
            self.remove_selected_driver(d)
        take_screenshot(self.page, self.run_dir / "after_remove_drivers.png")

        self.click_constructors_tab()
        for c in diff["constructors_remove"]:
            log(f"Removing constructor: {c}")
            self.remove_selected_constructor(c)
        take_screenshot(self.page, self.run_dir / "after_remove_constructors.png")

        for c in diff["constructors_add"]:
            log(f"Adding constructor via list/search: {c}")
            self.add_constructor_via_search_list(c)
        take_screenshot(self.page, self.run_dir / "after_add_constructors.png")

        self.click_drivers_tab()
        for d in diff["drivers_add"]:
            log(f"Adding driver via list/search: {d}")
            self.add_driver_via_search_list(d)
        take_screenshot(self.page, self.run_dir / "after_add_drivers.png")

        if diff["boost_change"]:
            log(f"Setting boost to: {ideal['boost_driver']}")
            self.set_boost(ideal["boost_driver"])
        take_screenshot(self.page, self.run_dir / "after_boost.png")

        self.persist_continue_confirm()
        take_screenshot(self.page, self.run_dir / "home_after_confirm.png")

        self.goto_team()
        self.click_drivers_tab()
        final_state = self.get_current_state()
        take_screenshot(self.page, self.run_dir / "state_final.png")

        verify = compute_diff(final_state, ideal)
        write_json(self.run_dir / "diff_final_vs_ideal.json", verify)
        if not verify.get("noop"):
            take_screenshot(self.page, self.run_dir / "verify_failed.png")
            raise RuntimeError(
                "Post-apply verification failed (final state != ideal). See diff_final_vs_ideal.json"
            )

        return final_state, diff
