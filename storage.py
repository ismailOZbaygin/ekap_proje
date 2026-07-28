"""CSV / XLSX storage layer for EKAP Contract Data Extractor.

Handles:
- CSV append (creates file + header row on first write)
- Duplicate İKN detection with user prompt
- Optional XLSX export via openpyxl
"""

from __future__ import annotations

import csv
import logging
import os
from typing import Optional

from models import ContractRecord
import config

logger = logging.getLogger(__name__)


def _ensure_output_dir() -> None:
    """Create the output directory if it doesn't exist."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)


def _csv_path() -> str:
    """Return the full path to the output CSV."""
    return os.path.join(config.OUTPUT_DIR, config.OUTPUT_FILE)


def is_duplicate(ikn: str) -> bool:
    """Check whether *ikn* already exists in the CSV file."""
    path = _csv_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding=config.CSV_ENCODING, newline="") as f:
            reader = csv.reader(f, delimiter=config.CSV_DELIMITER)
            next(reader, None)  # skip header
            for row in reader:
                if row and row[0] == ikn:
                    return True
    except Exception as exc:
        logger.warning("Duplicate kontrolü sırasında hata: %s", exc)
    return False


def prompt_overwrite(ikn: str) -> bool:
    """Ask the user whether to overwrite an existing İKN row.

    Returns True if the user wants to overwrite, False to skip.
    """
    while True:
        answer = input(
            f"⚠  İKN '{ikn}' zaten dosyada mevcut. "
            f"Üzerine yazmak ister misiniz? (e/h): "
        ).strip().lower()
        if answer in ("e", "evet", "y", "yes"):
            return True
        if answer in ("h", "hayır", "n", "no"):
            return False
        print("  Lütfen 'e' (evet) veya 'h' (hayır) girin.")


def remove_row(ikn: str) -> None:
    """Remove the existing row for *ikn* from the CSV (for overwrite)."""
    path = _csv_path()
    if not os.path.isfile(path):
        return

    rows: list[list[str]] = []
    with open(path, "r", encoding=config.CSV_ENCODING, newline="") as f:
        reader = csv.reader(f, delimiter=config.CSV_DELIMITER)
        for row in reader:
            if row and row[0] != ikn:
                rows.append(row)

    with open(path, "w", encoding=config.CSV_ENCODING, newline="") as f:
        writer = csv.writer(f, delimiter=config.CSV_DELIMITER)
        writer.writerows(rows)


def append_to_csv(record: ContractRecord) -> str:
    """Append *record* as a new row to the CSV file.

    Creates the file with a header row if it doesn't exist yet.
    Returns the path written to.
    """
    _ensure_output_dir()
    path = _csv_path()
    file_exists = os.path.isfile(path)

    with open(path, "a", encoding=config.CSV_ENCODING, newline="") as f:
        writer = csv.writer(f, delimiter=config.CSV_DELIMITER)
        if not file_exists:
            writer.writerow(ContractRecord.csv_headers())
        writer.writerow(record.to_row())

    logger.info("Kayıt CSV'ye eklendi: %s", path)
    return path


def export_to_xlsx(xlsx_filename: Optional[str] = None) -> str:
    """Convert the current CSV to an XLSX file.

    Parameters
    ----------
    xlsx_filename:
        Target filename (without path).  Defaults to ``sonuclar.xlsx``.

    Returns
    -------
    str  – the full path to the written XLSX file.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        raise RuntimeError(
            "openpyxl yüklü değil.  'pip install openpyxl' komutunu çalıştırın."
        )

    csv_path = _csv_path()
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV dosyası bulunamadı: {csv_path}")

    xlsx_name = xlsx_filename or config.OUTPUT_FILE.replace(".csv", ".xlsx")
    xlsx_path = os.path.join(config.OUTPUT_DIR, xlsx_name)

    wb = Workbook()
    ws = wb.active
    ws.title = "Sözleşme Verileri"

    with open(csv_path, "r", encoding=config.CSV_ENCODING, newline="") as f:
        reader = csv.reader(f, delimiter=config.CSV_DELIMITER)
        for row in reader:
            ws.append(row)

    # Auto-fit column widths (approximate)
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)

    wb.save(xlsx_path)
    logger.info("XLSX dosyası oluşturuldu: %s", xlsx_path)
    return xlsx_path
