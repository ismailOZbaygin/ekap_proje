"""Quick smoke test for the parser module."""

from parser import parse_veri_html, parse_api_response

# ── Test 1: parse_veri_html with realistic HTML ───────────────────────────────

test_html = """
<table>
<tr><td valign="top"><b> Tarihi</b>
          </td><td valign="top">:</td><td valign="top">15.05.2024</td></tr>
<tr><td valign="top"><b> Bedeli</b>
          </td><td valign="top">:</td><td valign="top">1.250.000,00 TRY</td></tr>
<tr><td valign="top"><b> Süresi</b>
          </td><td valign="top">:</td><td valign="top">180 Gün</td></tr>
<tr><td valign="top"><b> Yüklenicisi</b>
          </td><td valign="top">:</td><td valign="top">ABC İnşaat Taahhüt San. ve Tic. A.Ş.</td></tr>
<tr><td valign="top"><b> Yüklenicinin uyruğu</b>
          </td><td valign="top">:</td><td valign="top">Türkiye</td></tr>
<tr><td valign="top"><b> Yüklenicinin adresi</b>
          </td><td valign="top">:</td><td valign="top">Mehmet Akif Ersoy Mahallesi 274 Sokak A-Blok Apt. No:1 A/55 Yenimahalle/ANKARA</td></tr>
</table>
"""

print("=== Test 1: parse_veri_html ===")
record = parse_veri_html(test_html, "2024/123456")
print(record)
print()
assert record.ikn == "2024/123456"
assert record.sozlesme_tarihi == "15.05.2024"
assert record.sozlesme_bedeli == "1.250.000,00 TRY"
assert record.sozlesme_suresi == "180 Gün"
assert record.yuklenici_adi == "ABC İnşaat Taahhüt San. ve Tic. A.Ş."
assert record.yuklenici_uyrugu == "Türkiye"
assert "Mehmet Akif Ersoy" in record.yuklenici_adresi
print("✔ Test 1 PASSED — all 6 fields correctly extracted\n")

# ── Test 2: parse_api_response with ilanList wrapper ──────────────────────────

print("=== Test 2: parse_api_response (ilanList wrapper) ===")
mock_response = {
    "ilanList": [
        {"veriHtml": test_html}
    ]
}
record2 = parse_api_response(mock_response, "2024/999999")
assert record2 is not None
assert record2.ikn == "2024/999999"
assert record2.sozlesme_tarihi == "15.05.2024"
print(record2)
print("✔ Test 2 PASSED — ilanList → veriHtml correctly parsed\n")

# ── Test 3: parse_api_response with nested data.ilanList ──────────────────────

print("=== Test 3: parse_api_response (data.ilanList wrapper) ===")
mock_response_nested = {
    "success": True,
    "data": {
        "ilanList": [
            {"veriHtml": test_html}
        ]
    }
}
record3 = parse_api_response(mock_response_nested, "2023/111111")
assert record3 is not None
assert record3.yuklenici_adi == "ABC İnşaat Taahhüt San. ve Tic. A.Ş."
print("✔ Test 3 PASSED — nested data.ilanList correctly parsed\n")

# ── Test 4: Empty / missing data ──────────────────────────────────────────────

print("=== Test 4: Missing data returns None ===")
empty_response = {"ilanList": []}
record4 = parse_api_response(empty_response, "2024/000000")
assert record4 is None
print("✔ Test 4 PASSED — empty ilanList returns None\n")

# ── Test 5: CSV roundtrip ────────────────────────────────────────────────────

print("=== Test 5: CSV headers and row ===")
from models import ContractRecord
headers = ContractRecord.csv_headers()
row = record.to_row()
assert len(headers) == len(row) == 7
assert headers[0] == "İKN"
print(f"  Headers: {headers}")
print(f"  Row:     {row}")
print("✔ Test 5 PASSED — CSV structure is correct\n")

print("=" * 50)
print("ALL TESTS PASSED ✔")
