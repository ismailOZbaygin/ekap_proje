"""CSV / XLSX storage layer — YAGNI architecture.

Implements a flat-file storage approach with in-memory Set caching
for O(1) duplicate detection.  No database, no upsert — first snapshot
is immutable.

Pipeline Phases Handled Here:
  Phase 1 — State Hydration:  ``IKNCache.load()``
  Phase 4 — Dedup & I/O:     ``IKNCache.contains()`` + ``append_batch()``
"""

from __future__ import annotations

import csv
import logging
import os
from typing import Optional

from models import ContractRecord
import config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Phase 1 — State Hydration (In-Memory IKN Cache)
# ═══════════════════════════════════════════════════════════════════════

class IKNCache:
    """Hash-set of IKNs already persisted in the CSV.

    Lookups are O(1).  The set is updated eagerly when new records
    are appended so that duplicates *within the same session* are
    also caught.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    # ── loading ────────────────────────────────────────────────────────

    def load(self, filepath: Optional[str] = None) -> int:
        """Read existing CSV and populate the set.

        Returns the number of IKNs loaded.
        """
        path = filepath or _csv_path()
        if not os.path.isfile(path):
            logger.info("CSV dosyası bulunamadı — boş cache ile başlanıyor.")
            return 0

        count = 0
        try:
            with open(path, "r", encoding=config.CSV_ENCODING, newline="") as f:
                reader = csv.reader(f, delimiter=config.CSV_DELIMITER)
                next(reader, None)          # skip header
                for row in reader:
                    if row:
                        self._seen.add(row[0])  # first column = İKN
                        count += 1
        except Exception as exc:
            logger.warning("CSV okuma hatası (cache): %s", exc)

        logger.info("Cache yüklendi — %d İKN mevcut.", count)
        return count

    # ── queries ────────────────────────────────────────────────────────

    def contains(self, ikn: str) -> bool:
        """O(1) duplicate check."""
        return ikn in self._seen

    def add(self, ikn: str) -> None:
        """Register an IKN (called right after append to keep set fresh)."""
        self._seen.add(ikn)

    def __len__(self) -> int:
        return len(self._seen)


# ═══════════════════════════════════════════════════════════════════════
#  Phase 4 — Deduplication & I/O
# ═══════════════════════════════════════════════════════════════════════

def _ensure_output_dir() -> None:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)


def _csv_path() -> str:
    return os.path.join(config.OUTPUT_DIR, config.OUTPUT_FILE)


def append_record(record: ContractRecord, cache: IKNCache) -> bool:
    """Append a single record if it is not a duplicate.

    Updates the in-memory cache immediately.
    Returns True if the record was written, False if dropped as dup.
    """
    if cache.contains(record.ikn):
        logger.info("Duplicate atlandı: %s", record.ikn)
        return False

    _ensure_output_dir()
    path = _csv_path()
    file_exists = os.path.isfile(path)

    with open(path, "a", encoding=config.CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=ContractRecord.csv_headers(),
            delimiter=config.CSV_DELIMITER,
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(record.to_dict())

    cache.add(record.ikn)
    logger.info("Kayıt eklendi: %s", record.ikn)
    return True


def append_batch(records: list[ContractRecord], cache: IKNCache) -> int:
    """Append a batch of records, skipping duplicates.

    Checks both the persistent cache AND intra-batch duplicates.
    Writes all new records in a single I/O operation.
    Returns the number of records actually written.
    """
    new_records: list[ContractRecord] = []
    for rec in records:
        if cache.contains(rec.ikn):
            logger.info("Duplicate atlandı: %s", rec.ikn)
            continue
        new_records.append(rec)
        cache.add(rec.ikn)  # prevent intra-batch duplicates

    if not new_records:
        return 0

    _ensure_output_dir()
    path = _csv_path()
    file_exists = os.path.isfile(path)

    with open(path, "a", encoding=config.CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=ContractRecord.csv_headers(),
            delimiter=config.CSV_DELIMITER,
        )
        if not file_exists:
            writer.writeheader()
        for rec in new_records:
            writer.writerow(rec.to_dict())

    logger.info("Batch yazıldı — %d yeni kayıt.", len(new_records))
    return len(new_records)


# ═══════════════════════════════════════════════════════════════════════
#  Optional XLSX Export
# ═══════════════════════════════════════════════════════════════════════

def export_to_xlsx(xlsx_filename: Optional[str] = None) -> str:
    """Convert the current CSV to an XLSX file."""
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

    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)

    wb.save(xlsx_path)
    logger.info("XLSX oluşturuldu: %s", xlsx_path)
    return xlsx_path
