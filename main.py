#!/usr/bin/env python3
"""EKAP Sözleşme Veri Çekici — CLI entry point.

Pipeline:
  Phase 1 — State Hydration:    Load existing IKNs into set()
  Phase 2 — Ingestion:          Playwright fetches from EKAP
  Phase 3 — Defensive Parsing:  BeautifulSoup extracts veriHtml fields
  Phase 4 — Dedup & I/O:        Set check → CSV batch append
"""

from __future__ import annotations

import logging
import os
import sys

import config
from ekap_client import EkapClient, EkapClientError
from storage import IKNCache, append_record

# ── Logging Setup ──────────────────────────────────────────────────────────────
def contains(self, ikn: str) -> bool:
        """O(1) lookup in dictionary. API Contract for main.py."""
        return ikn in self._data

def _setup_logging() -> None:
    """Configure root logger + file handler for errors."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    error_log_path = os.path.join(config.OUTPUT_DIR, config.ERROR_LOG)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    fh = logging.FileHandler(error_log_path, encoding="utf-8")
    fh.setLevel(logging.WARNING)
    fh.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(fh)


# ── Banner ─────────────────────────────────────────────────────────────────────

BANNER = r"""
╔═══════════════════════════════════════════════════╗
║    EKAP Sözleşme Veri Çekici  v1.0                ║
║    İKN girin, sözleşme verilerini CSV'ye kaydedin ║
╚═══════════════════════════════════════════════════╝
"""


# ── Main Loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()
    logger = logging.getLogger("main")

    print(BANNER)

    # ── Phase 1: State Hydration ───────────────────────────────────────
    cache = IKNCache()
    loaded = cache.load()
    print(f"  Cache: {loaded} mevcut İKN yüklendi.\n")

    # Initialise client (browser will be launched on first query)
    client = EkapClient()

    success_count = 0
    error_count = 0
    skip_count = 0

    while True:
        try:
            ikn = input("İKN girin ('q' çıkış): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not ikn or ikn.lower() == "q":
            break

        # ── Phase 2 + 3: Ingestion & Parsing ───────────────────────────
        try:
            print(f"  ⏳ İKN '{ikn}' sorgulanıyor…")
            record = client.fetch_contract(ikn)

            # ── Phase 4b: Dedup & I/O ──────────────────────────────────
            written = append_record(record, cache)
            if written:
                print("  ✔  Sözleşme verisi bulundu, CSV'ye eklendi.")
                print(record)
                success_count += 1
            else:
                print(f"  ⏭  İKN '{ikn}' kopya — güncellendi.")
                skip_count += 1

        except EkapClientError as exc:
            print(f"  ✘  {exc}")
            # Log with exception info to include traceback for diagnostics
            logger.exception("İKN '%s' — %s", ikn, exc)
            error_count += 1

        except Exception as exc:
            print(f"  ✘  Beklenmeyen hata: {exc}")
            logger.exception("İKN '%s' — beklenmeyen hata", ikn)
            error_count += 1

    # ── Cleanup ────────────────────────────────────────────────────────
    client.close()

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print(f"Bitti.  {success_count} kayıt eklendi, "
          f"{error_count} hata, {skip_count} güncellendi.")

    csv_path = os.path.join(config.OUTPUT_DIR, config.OUTPUT_FILE)
    if os.path.isfile(csv_path):
        print(f"Çıktı dosyası: {csv_path}")


if __name__ == "__main__":
    main()
