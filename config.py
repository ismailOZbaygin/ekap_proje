"""Configuration settings for EKAP Contract Data Extractor."""

import os

# ── Base URLs ──────────────────────────────────────────────────────────────────
BASE_URL = "https://ekapv2.kik.gov.tr"
SEARCH_PAGE_URL = f"{BASE_URL}/ekap/search"

# ── API Endpoints ──────────────────────────────────────────────────────────────
# Primary search endpoint — POST with İKN payload
SEARCH_ENDPOINT = f"{BASE_URL}/api/IhaleArama/Search"
# Fallback search endpoint
SEARCH_ENDPOINT_ALT = f"{BASE_URL}/api/Ihale/GetListByParameters"
# Tender detail endpoint
TENDER_DETAIL_ENDPOINT = f"{BASE_URL}/api/Ihale/GetIhaleDetay"
# Contract detail endpoint
CONTRACT_DETAIL_ENDPOINT = f"{BASE_URL}/api/Ihale/GetSozlesmeDetay"

# ── Request Headers ────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE_URL}/ekap/search",
    "Origin": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
}

# ── Request Behaviour ──────────────────────────────────────────────────────────
REQUEST_DELAY = 2       # seconds between consecutive requests
MAX_RETRIES = 3         # retry count on transient failures
RETRY_BACKOFF = 2       # exponential back-off multiplier
REQUEST_TIMEOUT = 30    # seconds before a single request times out

# ── Output Settings ────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
OUTPUT_FILE = "sonuclar.csv"
CSV_DELIMITER = ";"          # Noktalı virgül (Türkiye / Excel Türkçe bölge ayarı ile uyumlu)
CSV_ENCODING = "utf-8-sig"   # BOM so Excel auto-detects UTF-8
EXPORT_XLSX = True           # Otomatik .xlsx dosyası da oluştur
ERROR_LOG = "errors.log"

