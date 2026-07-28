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
    with open("debug_veri.html", "w", encoding="utf-8") as f:
        f.write(html_content)
        
    record = ContractRecord(ikn=ikn)
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Bağlam Sınırını (Scope Boundary) daha güvenli bul
    sozlesme_basligi = None
    for tag in soup.find_all(["span", "b", "td"]):
        if "4- Sözleşmenin" in tag.get_text(strip=True):
            sozlesme_basligi = tag
            break
            
    if not sozlesme_basligi:
        logger.warning("İKN %s — '4- Sözleşmenin' başlığı bulunamadı. Kapsam daraltılamıyor.", ikn)
        return record

    baslangic_satiri = sozlesme_basligi.find_parent("tr")
    
    if not baslangic_satiri:
        logger.warning("İKN %s — Başlık satırı (tr) bulunamadı.", ikn)
        return record

    # 2. Sadece başlığın altındaki satırları tara
    for tr in baslangic_satiri.find_next_siblings("tr"):
        try:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue

            # b etiketini boşver, tüm hücrenin metnini ("a) Tarihi") al.
            raw_text = tds[0].get_text(strip=True)
            
            # Regex: Başlangıçtan kapanış parantezine kadar olan kısmı (örn: "a) ", "d) ") ve sonrasındaki boşlukları sil.
            clean_text = re.sub(r'^.*?\)\s*', '', raw_text)

            attr = _match_label(clean_text)
            if attr is None:
                continue

            # Veriyi al (son td)
            value = tds[-1].get_text(strip=True)
            setattr(record, attr, value)
            
        except Exception as exc:
            logger.warning("İKN %s — satır parse hatası (atlanıyor): %s", ikn, exc)
            continue

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


def parse_api_response(raw_data: dict, ikn: str) -> Optional[ContractRecord]:
    # 1. Root objeyi güvenli şekilde al. JSON yapısına göre 'ilanList' doğrudan kökteyse:
    ilan_list = raw_data.get("item", {}).get("ilanList")
    
    # Hata kontrolü: Ya API yapısı değişirse veya boş dönerse? (Defensive Programming)
    if not ilan_list or not isinstance(ilan_list, list):
        logger.error("İKN %s — API yanıtında 'ilanList' dizisi bulunamadı veya boş.", ikn)
        return None

    # 2. Tip 4 olan (Sonuç İlanı) objeyi bul. 
    # next(generator, default_value) -> Bulamazsa None döner, kodu patlatmaz.
    sonuc_ilani = next((ilan for ilan in ilan_list if str(ilan.get("ilanTip")) == "4"), None)

    if not sonuc_ilani:
        logger.warning("İKN %s — 'ilanList' içinde ilanTip='4' olan sonuç ilanı bulunamadı.", ikn)
        return None

    # 3. HTML verisini çek ve asıl HTML parser'ına gönder
    veri_html = sonuc_ilani.get("veriHtml")
    if not veri_html:
        logger.warning("İKN %s — Sonuç ilanının 'veriHtml' alanı boş.", ikn)
        return None

    logger.debug("İKN %s — Tip 4 ilan bulundu, HTML ayrıştırılıyor...", ikn)
    return parse_veri_html(veri_html, ikn)
