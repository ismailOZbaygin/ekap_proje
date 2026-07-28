"""Data models for EKAP Contract Data Extractor."""

from dataclasses import dataclass


@dataclass
class ContractRecord:
    """A single contract record extracted from EKAP.

    Every field is stored as a string.  Missing / empty values are
    represented by the empty string — never None.
    """

    ikn: str = ""
    sozlesme_tarihi: str = ""
    sozlesme_bedeli: str = ""
    sozlesme_suresi: str = ""
    yuklenici_adi: str = ""
    yuklenici_uyrugu: str = ""
    yuklenici_adresi: str = ""

    # ── CSV helpers ────────────────────────────────────────────────────

    @staticmethod
    def csv_headers() -> list[str]:
        """Return CSV column headers (Turkish display names)."""
        return [
            "İKN",
            "Sözleşme Tarihi",
            "Sözleşme Bedeli",
            "Sözleşme Süresi",
            "Yüklenici Adı",
            "Yüklenici Uyruğu",
            "Yüklenici Adresi",
        ]

    def to_row(self) -> list[str]:
        """Return field values as an ordered list matching *csv_headers*."""
        return [
            self.ikn,
            self.sozlesme_tarihi,
            self.sozlesme_bedeli,
            self.sozlesme_suresi,
            self.yuklenici_adi,
            self.yuklenici_uyrugu,
            self.yuklenici_adresi,
        ]

    def to_dict(self) -> dict[str, str]:
        """Return {header: value} mapping for display / debugging."""
        return dict(zip(self.csv_headers(), self.to_row()))

    def __str__(self) -> str:
        parts = [f"  {k}: {v}" for k, v in self.to_dict().items()]
        return "\n".join(parts)
