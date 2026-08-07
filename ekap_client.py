"""EKAP v2 client — Playwright headless browser.

EKAP v2 is a JavaScript SPA (Angular + DevExtreme) with client-side
security (CryptoJS, Cloudflare WAF).  Plain HTTP requests → 406.

Strategy:
  1. Launch headless Chromium via Playwright.
  2. Navigate to the EKAP search page.
  3. Fill İKN (year → #ikn-yil, number → #ikn-no).
  4. Click Filtrele (#search-ihale).
  5. Click the result badge "Sonuç İlanı Yayımlanmış".
  6. Intercept the XHR response (GetByIhaleIdIhaleDetay) → JSON.
  7. Parse with parser.py → ContractRecord.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from playwright.sync_api import (
    sync_playwright,
    Page,
    Response,
    TimeoutError as PwTimeout,
)

import config
from models import ContractRecord
from parser import parse_api_response, parse_veri_html, find_contract_html

logger = logging.getLogger(__name__)


class EkapClientError(Exception):
    """Raised for EKAP-specific errors."""


class EkapClient:
    """Playwright-based client for EKAP v2.

    Keeps a single browser instance alive across queries.
    Call ``close()`` when done.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page: Optional[Page] = None
        self._intercepted: list[dict] = []

    #  Lifecycle

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

        # Intercept only the detail API response
        self._page.on("response", self._on_response)

        logger.info("EKAP arama sayfası yükleniyor…")
        self._page.goto(
            config.SEARCH_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        # Dismiss the tutorial overlay that blocks all pointer events.
        self._dismiss_tutorial(self._page)

        logger.info("Arama sayfası hazır.")
        time.sleep(config.REQUEST_DELAY)
        return self._page

    def _on_response(self, response: Response) -> None:
        """Capture the detail API response (early exit for irrelevant URLs)."""
        if "GetByIhaleIdIhaleDetay" not in response.url:
            return
        try:
            body = response.json()
            self._intercepted.append(body)
            logger.debug("İhale detay verisi yakalandı: %s", response.url)
        except Exception as exc:
            logger.exception("JSON parse hatası: %s", exc)

    @staticmethod
    def _dismiss_tutorial(page: Page) -> None:
        """Remove the <ekap-tutorial> overlay that blocks pointer events."""
        try:
            # Inject CSS to hide all overlays and disable pointer events
            page.add_style_tag(content="""
                ekap-tutorial, div.overlay, .introjs-overlay, .cdk-overlay-container:has(ekap-tutorial) {
                    display: none !important;
                    pointer-events: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                }
            """)
        except Exception as exc:
            logger.debug("CSS overlay gizleme hatası: %s", exc)

        try:
            # Remove the elements entirely via JavaScript
            removed = page.evaluate("""
                () => {
                    const selectors = ['ekap-tutorial', 'div.overlay', '.introjs-overlay'];
                    let count = 0;
                    selectors.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => {
                            el.remove();
                            count++;
                        });
                    });
                    return count;
                }
            """)
            if removed > 0:
                logger.info("Tutorial overlay kaldırıldı (%d element).", removed)
                page.wait_for_timeout(300)
        except Exception as exc:
            logger.debug("JS overlay kaldırma başarısız: %s", exc)

    def close(self) -> None:
        """Shut down the browser."""
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._page = None
        self._browser = None
        self._pw = None

    # ══════════════════════════════════════════════════════════════════
    #  Public API
    # ══════════════════════════════════════════════════════════════════

    def fetch_contract(self, ikn: str) -> ContractRecord:
        """End-to-end: search → click result → intercept → parse."""
        if "/" not in ikn:
            raise EkapClientError(
                f"Geçersiz İKN formatı: '{ikn}' — beklenen: YIL/NUMARA"
            )
        ikn_yil, ikn_no = [p.strip() for p in ikn.split("/", 1)]

        # 1. Tarayıcıyı getir (ilk seferde başlatır, sonrakilerde açık olanı verir)
        page = self._ensure_browser()
        
        # 2. STATE TEMİZLİĞİ: Her yeni İKN için sayfayı sıfırla (Hard Reset)
        logger.info("Sekme sıfırlanıyor (eski filtreler ve DOM temizleniyor)...")
        page.goto(config.SEARCH_PAGE_URL, wait_until="domcontentloaded", timeout=30000)
        
        # Sayfa yenilendiği için tutorial/pop-up tekrar çıkabilir, onu eziyoruz.
        self._dismiss_tutorial(page)

        self._intercepted.clear()
        logger.info("İKN '%s' aranıyor…", ikn)

        # ── Steps 1–4: Fill form & click result ────────────────────────
        self._fill_and_search(page, ikn_yil, ikn_no)

        # ── Step 5: Click result badge & intercept XHR ─────────────────
        try:
            result_badge = page.locator(
                "span.badge", has_text="Sonuç İlanı Yayımlanmış"
            ).first
            result_badge.wait_for(state="visible", timeout=10000)

            # Click badge while expecting the detail API response
            with page.expect_response(
                lambda r: "GetByIhaleIdIhaleDetay" in r.url and r.status == 200,
                timeout=10000,
            ) as resp_info:
                result_badge.click(force=True)

            raw_data = resp_info.value.json()
            logger.debug("API yanıtı başarıyla yakalandı.")

            record = parse_api_response(raw_data, ikn)
            if record is not None:
                return record

        except PwTimeout:
            logger.warning("Sonuç ilanı veya API yanıtı zaman aşımına uğradı.")
        except Exception as exc:
            logger.warning("XHR intercept hatası: %s", exc)

        # ── Fallback: check anything intercepted by _on_response ───────
        for data in reversed(self._intercepted):
            record = parse_api_response(data, ikn)
            if record is not None:
                return record

        # ── Fallback: extract from rendered DOM ────────────────────────
        record = self._extract_from_page(page, ikn)
        if record is not None:
            return record

        raise EkapClientError(
            f"İKN '{ikn}' için sözleşme verisi bulunamadı."
        )

    # ══════════════════════════════════════════════════════════════════
    #  Private — Form Interaction
    # ══════════════════════════════════════════════════════════════════

    def _fill_and_search(self, page: Page, ikn_yil: str, ikn_no: str) -> None:
        """Formu kullanıcı eylemlerini simüle ederek doldurur ve arar."""
        
        # Her ihtimale karşı form doldurmadan önce overlay temizliğini tekrar çağır
        self._dismiss_tutorial(page)

        # Sayfanın ve form elemanlarının DOM'da hazır olmasını bekle
        page.wait_for_selector("#ikn-yil", state="visible", timeout=15000)

        # ── Adım 1: İKN Yılı (Dropdown / Portal Mekanizması) ──
        # Kutuya tıkla ve portalın (listenin) açılmasını sağla
        page.locator("#ikn-yil").click(force=True)
        
        # Açılan listede hedef yılı (tam eşleşme ile) bul ve tıkla
        year_option = page.locator(".dx-dropdowneditor-overlay").get_by_text(ikn_yil, exact=True)
        year_option.wait_for(state="visible", timeout=5000)
        year_option.click(force=True)

        # ── Adım 2: İKN Numarası (Text Input Mekanizması) ──
        # NumberBox içindeki gerçek input alanını hedefle ve rakamları sırayla yaz
        no_input = page.locator("#ikn-no input.dx-texteditor-input")
        no_input.click(force=True)  # Focus almak için
        no_input.fill("")
        no_input.press_sequentially(ikn_no, delay=50) # Klavyeden yazıyormuş gibi

        # ── Adım 3: Filtrele ──
        page.locator("#search-ihale").click(force=True)

        # Sonuçların API'den dönüp DOM'a yansımasını bekle
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PwTimeout:
            logger.debug("domcontentloaded zaman aşımına uğradı, işleme devam ediliyor.")

    def _extract_from_page(self, page: Page, ikn: str) -> Optional[ContractRecord]:
        """Fallback: extract contract data from the rendered DOM."""
        try:
            html = page.content()
            if "Yüklenici" in html or "Sözleşme" in html:
                logger.debug("DOM'dan veri çıkarılıyor…")
                record = parse_veri_html(html, ikn)
                if any(v != "" for v in record.to_row()[1:]):
                    return record
        except Exception as exc:
            logger.debug("DOM extract başarısız: %s", exc)
        return None
