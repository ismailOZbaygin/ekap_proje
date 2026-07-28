"""EKAP v2 client — uses Playwright headless browser to bypass WAF/CryptoJS.

EKAP v2 is a JavaScript SPA with client-side security (CryptoJS token
generation, Cloudflare WAF).  Plain HTTP requests are rejected with 406.
This module launches a headless Chromium browser, performs the search in
the real UI, and intercepts the XHR/fetch responses that contain the
actual data (including ``ilanList`` with ``veriHtml``).

Strategy:
1. Launch headless Chromium via Playwright.
2. Navigate to the EKAP search page.
3. Fill in the İKN field and submit the search.
4. Intercept network responses looking for JSON containing ``ilanList``.
5. Parse the intercepted data with ``parser.py``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Response, TimeoutError as PwTimeout

import config
from models import ContractRecord
from parser import parse_api_response, parse_veri_html, find_contract_html

logger = logging.getLogger(__name__)


class EkapClientError(Exception):
    """Raised for EKAP-specific errors (not-found, unexpected format, …)."""


class EkapClient:
    """Playwright-based client for EKAP v2.

    Keeps a single browser instance alive across queries for efficiency.
    Call ``close()`` when done.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page: Optional[Page] = None
        self._intercepted: list[dict] = []

    # ── Lifecycle ──────────────────────────────────────────────────────

    def _ensure_browser(self) -> Page:
        """Launch browser + navigate to search page if not already done."""
        if self._page is not None:
            return self._page

        logger.info("Tarayıcı başlatılıyor (headless Chromium)…")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        self._page = context.new_page()

        # Listen for all responses to intercept API data
        self._page.on("response", self._on_response)

        logger.info("EKAP arama sayfası yükleniyor…")
        self._page.goto(config.SEARCH_PAGE_URL, wait_until="networkidle", timeout=60000)
        logger.info("Arama sayfası hazır.")
        time.sleep(config.REQUEST_DELAY)
        return self._page

    def _on_response(self, response: Response) -> None:
        """Callback: capture JSON responses that might contain ilanList."""
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct and "javascript" not in ct:
                return
            url = response.url
            # Only interested in API-like responses
            if response.status == 200:
                try:
                    body = response.json()
                except Exception:
                    return
                # Check if this response contains ilanList
                if isinstance(body, dict):
                    has_ilan = (
                        "ilanList" in body
                        or ("data" in body and isinstance(body.get("data"), dict) and "ilanList" in body["data"])
                        or ("result" in body and isinstance(body.get("result"), dict) and "ilanList" in body["result"])
                    )
                    if has_ilan:
                        logger.debug("ilanList yakalandı — URL: %s", url)
                        self._intercepted.append(body)
                    # Also capture if it looks like tender/search results
                    elif any(k in body for k in ["ihaleler", "items", "records", "sonuclar", "list"]):
                        logger.debug("Potansiyel veri yakalandı — URL: %s anahtarlar: %s", url, list(body.keys()))
                        self._intercepted.append(body)
        except Exception:
            pass

    def close(self) -> None:
        """Shut down the browser."""
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._page = None
        self._browser = None
        self._pw = None

    # ── Search ─────────────────────────────────────────────────────────

    def fetch_contract(self, ikn: str) -> ContractRecord:
        """Search for *ikn* and return a ContractRecord.

        Raises EkapClientError if nothing is found.
        """
        page = self._ensure_browser()
        self._intercepted.clear()

        logger.info("İKN '%s' aranıyor…", ikn)

        try:
            # Try to find and fill the İKN input field
            # EKAP v2 is an Angular SPA — we need to locate the right input
            self._perform_search(page, ikn)

            # Wait for API responses to be intercepted
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(3)  # Extra wait for any delayed XHR

        except PwTimeout:
            logger.warning("Ağ bekleme zaman aşımı — mevcut verilerle devam ediliyor.")

        except Exception as exc:
            raise EkapClientError(f"Arama sırasında hata: {exc}") from exc

        # Process intercepted responses
        if not self._intercepted:
            # Fallback: try to extract from the rendered page
            record = self._extract_from_page(page, ikn)
            if record:
                return record
            raise EkapClientError(
                f"İKN '{ikn}' için sözleşme verisi bulunamadı (API yanıtı yakalanmadı)."
            )

        # Parse the intercepted JSON data
        for data in reversed(self._intercepted):  # newest first
            record = parse_api_response(data, ikn)
            if record is not None:
                return record

        # If parse_api_response returned None for all intercepted data,
        # try direct veriHtml extraction
        for data in self._intercepted:
            record = self._extract_ilan_list_deep(data, ikn)
            if record is not None:
                return record

        raise EkapClientError(
            f"İKN '{ikn}' için sözleşme verisi bulunamadı."
        )

    def _perform_search(self, page: Page, ikn: str) -> None:
        """Fill the search form and submit."""
        # Wait for the Angular app to render
        page.wait_for_timeout(2000)

        # Try various strategies to find the İKN input
        selectors = [
            'input[formcontrolname="ikn"]',
            'input[placeholder*="İKN"]',
            'input[placeholder*="IKN"]',
            'input[placeholder*="ikn"]',
            'input[placeholder*="Kayıt"]',
            'input[name*="ikn"]',
            'input[name*="IKN"]',
            'input[id*="ikn"]',
            'input[id*="IKN"]',
            # DevExtreme components use nested inputs
            'dx-text-box input',
            'input.dx-texteditor-input',
        ]

        input_found = False
        for selector in selectors:
            try:
                el = page.query_selector(selector)
                if el and el.is_visible():
                    el.click()
                    el.fill("")
                    page.wait_for_timeout(300)
                    el.type(ikn, delay=50)
                    input_found = True
                    logger.debug("İKN input bulundu: %s", selector)
                    break
            except Exception:
                continue

        if not input_found:
            # Broader fallback: try all visible text inputs
            inputs = page.query_selector_all('input[type="text"], input:not([type])')
            for inp in inputs:
                try:
                    if inp.is_visible():
                        placeholder = inp.get_attribute("placeholder") or ""
                        aria_label = inp.get_attribute("aria-label") or ""
                        if any(k in (placeholder + aria_label).lower() for k in ["ikn", "kayıt", "ihale"]):
                            inp.click()
                            inp.fill(ikn)
                            input_found = True
                            logger.debug("İKN input bulundu (fallback): placeholder=%s", placeholder)
                            break
                except Exception:
                    continue

        if not input_found:
            # Last resort: fill the first visible text input
            inputs = page.query_selector_all('input[type="text"], input:not([type])')
            for inp in inputs:
                try:
                    if inp.is_visible():
                        inp.click()
                        inp.fill(ikn)
                        input_found = True
                        logger.debug("İKN input bulundu (ilk input)")
                        break
                except Exception:
                    continue

        if not input_found:
            raise EkapClientError("İKN giriş alanı bulunamadı.")

        # Submit the search
        page.wait_for_timeout(500)
        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Ara")',
            'button:has-text("ara")',
            'button:has-text("Search")',
            'dx-button:has-text("Ara")',
            '.dx-button:has-text("Ara")',
            'button.btn-primary',
            'button.dx-button',
        ]

        submitted = False
        for selector in submit_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    submitted = True
                    logger.debug("Arama butonu tıklandı: %s", selector)
                    break
            except Exception:
                continue

        if not submitted:
            # Try Enter key as fallback
            page.keyboard.press("Enter")
            logger.debug("Enter tuşu ile arama gönderildi.")

        # Wait for results
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PwTimeout:
            pass

    def _extract_from_page(self, page: Page, ikn: str) -> Optional[ContractRecord]:
        """Fallback: extract contract data from the rendered DOM."""
        try:
            html = page.content()
            # Look for a table with contract data in the rendered page
            if "Yüklenici" in html or "Sözleşme" in html:
                logger.debug("DOM'dan veri çıkarılıyor…")
                record = parse_veri_html(html, ikn)
                if any(v != "" for v in record.to_row()[1:]):
                    return record
        except Exception as exc:
            logger.debug("DOM extract başarısız: %s", exc)
        return None

    def _extract_ilan_list_deep(self, data: dict, ikn: str) -> Optional[ContractRecord]:
        """Recursively search for veriHtml in any nested structure."""
        try:
            # Walk the entire dict looking for veriHtml strings
            html_contents = []
            self._find_veri_html(data, html_contents)
            if html_contents:
                best_html = find_contract_html(
                    [{"veriHtml": h} for h in html_contents]
                )
                if best_html:
                    record = parse_veri_html(best_html, ikn)
                    if any(v != "" for v in record.to_row()[1:]):
                        return record
        except Exception:
            pass
        return None

    def _find_veri_html(self, obj, results: list) -> None:
        """Recursively find all veriHtml values."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "veriHtml" and isinstance(v, str) and v.strip():
                    results.append(v)
                else:
                    self._find_veri_html(v, results)
        elif isinstance(obj, list):
            for item in obj:
                self._find_veri_html(item, results)
