"""Parser for extracting contract fields from EKAP veriHtml responses.

The EKAP v2 API returns contract data embedded as HTML inside the
``veriHtml`` field of each item in ``ilanList``.  The HTML is a
``<table>`` whose rows follow this pattern:

    <tr>
      <td valign="top"><b> Label</b>\r\n          </td>
      <td valign="top">:</td>
      <td valign="top">Value</td>
    </tr>

This module extracts the six required contract fields by matching row
labels to a known set of Turkish field names.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from models import ContractRecord

logger = logging.getLogger(__name__)

# ── Label → dataclass attribute mapping ────────────────────────────────────────
# Keys are normalised (lower-cased, stripped) label text that may appear
# inside the <b> tags.  We list several variants to be resilient against
# minor wording differences across tender types.
_LABEL_MAP: dict[str, str] = {
    # Sözleşme Tarihi
    "tarihi": "sozlesme_tarihi",
    "sözleşme tarihi": "sozlesme_tarihi",
    "sozlesme tarihi": "sozlesme_tarihi",
    # Sözleşme Bedeli
    "bedeli": "sozlesme_bedeli",
    "sözleşme bedeli": "sozlesme_bedeli",
    "sozlesme bedeli": "sozlesme_bedeli",
    # Sözleşme Süresi
    "süresi": "sozlesme_suresi",
    "sözleşme süresi": "sozlesme_suresi",
    "sozlesme süresi": "sozlesme_suresi",
    # Yüklenici Adı
    "yüklenicisi": "yuklenici_adi",
    "yüklenici adı": "yuklenici_adi",
    "yüklenici": "yuklenici_adi",
    # Yüklenicinin Uyruğu
    "yüklenicinin uyruğu": "yuklenici_uyrugu",
    "uyruğu": "yuklenici_uyrugu",
    # Yüklenicinin Adresi
    "yüklenicinin adresi": "yuklenici_adresi",
    "adresi": "yuklenici_adresi",
}


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace, strip."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _match_label(raw_label: str) -> Optional[str]:
    """Return the dataclass attribute name for *raw_label*, or None."""
    norm = _normalise(raw_label)
    # Exact match first
    if norm in _LABEL_MAP:
        return _LABEL_MAP[norm]
    # Partial / ends-with match (e.g. "4) Sözleşme Tarihi" → "sözleşme tarihi")
    for key, attr in _LABEL_MAP.items():
        if norm.endswith(key):
            return attr
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_veri_html(html_content: str, ikn: str) -> ContractRecord:
    """Parse a single ``veriHtml`` string and return a `ContractRecord`.

    Parameters
    ----------
    html_content:
        Raw HTML string from the ``veriHtml`` field.
    ikn:
        The İKN used for the query — stored in the record as-is.

    Returns
    -------
    ContractRecord
        Populated with whatever fields could be found; missing fields
        default to the empty string.
    """
    record = ContractRecord(ikn=ikn)
    soup = BeautifulSoup(html_content, "html.parser")

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        # The label lives inside a <b> in the first <td>
        b_tag = tds[0].find("b")
        if b_tag is None:
            continue

        label_text = b_tag.get_text()
        attr = _match_label(label_text)
        if attr is None:
            continue

        # The value is in the last <td> of the row
        value = tds[-1].get_text(strip=True)
        setattr(record, attr, value)

    # Log which fields were found / missing
    found = [h for h, v in record.to_dict().items() if v]
    missing = [h for h, v in record.to_dict().items() if not v and h != "İKN"]
    if found:
        logger.debug("İKN %s — bulunan alanlar: %s", ikn, ", ".join(found))
    if missing:
        logger.warning("İKN %s — eksik alanlar: %s", ikn, ", ".join(missing))

    return record


def find_contract_html(ilan_list: list[dict]) -> Optional[str]:
    """Pick the ilan whose ``veriHtml`` contains contract data.

    Heuristic: look for an ilan whose HTML mentions any of the six
    target labels.  If multiple match, prefer the one with the most
    matches.  Returns *None* if nothing looks relevant.
    """
    if not ilan_list:
        return None

    contract_keywords = [
        "Yüklenicisi", "Yüklenici", "Sözleşme Tarihi",
        "Sözleşme Bedeli", "Sözleşme Süresi",
        "Yüklenicinin uyruğu", "Yüklenicinin adresi",
        "Tarihi", "Bedeli", "Süresi",
    ]

    best_html: Optional[str] = None
    best_score = 0

    for ilan in ilan_list:
        html = ilan.get("veriHtml", "") or ""
        if not html:
            continue
        score = sum(1 for kw in contract_keywords if kw in html)
        if score > best_score:
            best_score = score
            best_html = html

    return best_html


def parse_api_response(response_data: dict, ikn: str) -> Optional[ContractRecord]:
    """High-level: extract a `ContractRecord` from the full API response.

    Navigates the JSON structure to find ``ilanList`` → ``veriHtml``,
    then delegates to `parse_veri_html`.

    Returns *None* if no contract data is found.
    """
    # Try common JSON structures
    ilan_list = None

    # Direct top-level
    if isinstance(response_data, dict):
        ilan_list = response_data.get("ilanList")
        # Nested under "data"
        if ilan_list is None and "data" in response_data:
            data = response_data["data"]
            if isinstance(data, dict):
                ilan_list = data.get("ilanList")
            elif isinstance(data, list):
                ilan_list = data
        # Nested under "result"
        if ilan_list is None and "result" in response_data:
            result = response_data["result"]
            if isinstance(result, dict):
                ilan_list = result.get("ilanList")

    if not ilan_list:
        logger.error("İKN %s — API yanıtında 'ilanList' bulunamadı.", ikn)
        return None

    html = find_contract_html(ilan_list)
    if not html:
        logger.error("İKN %s — ilanList içinde sözleşme verisi bulunamadı.", ikn)
        return None

    record = parse_veri_html(html, ikn)

    # Check if we actually found any useful data
    if all(v == "" for v in record.to_row()[1:]):
        logger.error("İKN %s — veriHtml parse edildi ama hiçbir alan bulunamadı.", ikn)
        return None

    return record
