#!/usr/bin/env python3
"""EKAP Sözleşme Veri Çekici — CLI entry point.

Usage
-----
Interactive mode (default):
    $ python main.py

The program prompts for İKN values one at a time.  Type 'q' to quit.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import config
from ekap_client import EkapClient, EkapClientError
from storage import append_to_csv, is_duplicate, prompt_overwrite, remove_row

# ── Logging Setup ──────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """Configure root logger + file handler for errors."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Error log file
    error_log_path = os.path.join(
        config.OUTPUT_DIR, config.ERROR_LOG
    )
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    fh = logging.FileHandler(error_log_path, encoding="utf-8")
    fh.setLevel(logging.WARNING)
    fh.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(fh)


# ── Banner ─────────────────────────────────────────────────────────────────────

BANNER = r"""
╔══════════════════════════════════════════════════╗
║    EKAP Sözleşme Veri Çekici  v1.0               ║
║    İKN girin, sözleşme verilerini CSV'ye kaydedin ║
╚══════════════════════════════════════════════════╝
"""


# ── Main Loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    _setup_logging()
    logger = logging.getLogger("main")

    print(BANNER)

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

        # ── Duplicate check ────────────────────────────────────────────
        if is_duplicate(ikn):
            overwrite = prompt_overwrite(ikn)
            if not overwrite:
                print(f"  ⏭  İKN '{ikn}' atlandı.")
                skip_count += 1
                continue
            else:
                remove_row(ikn)
                print(f"  🔄 Eski kayıt silindi, yeni veri çekiliyor…")

        # ── Fetch & save ───────────────────────────────────────────────
        try:
            print(f"  ⏳ İKN '{ikn}' sorgulanıyor…")
            record = client.fetch_contract(ikn)
            path = append_to_csv(record)
            print(f"  ✔  Sözleşme verisi bulundu, {path} dosyasına eklendi.")
            print(record)
            success_count += 1

        except EkapClientError as exc:
            print(f"  ✘  {exc}")
            logger.error("İKN '%s' — %s", ikn, exc)
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
          f"{error_count} hata, {skip_count} atlandı.")

    csv_path = os.path.join(config.OUTPUT_DIR, config.OUTPUT_FILE)
    if os.path.isfile(csv_path):
        print(f"Çıktı dosyası: {csv_path}")


if __name__ == "__main__":
    main()
