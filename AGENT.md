# AGENT.md — EKAP Contract Data Extractor

## 1. Project Goal

Build a semi-automatic Python tool that, given an **İKN (İhale Kayıt Numarası / Tender Registration Number)**, retrieves the following contract fields from the EKAP v2 platform (`https://ekapv2.kik.gov.tr/ekap/search`) and appends them as a row to a CSV/Excel file:

| Field (code)        | Description (TR)      |
|----------------------|------------------------|
| `sozlesmeTarihi`     | Contract Date          |
| `sozlesmeBedeli`     | Contract Amount        |
| `sozlesmeSuresi`     | Contract Duration      |
| `yukleniciAdi`       | Contractor Name        |
| `yukleniciUyrugu`    | Contractor Nationality |
| `yukleniciAdresi`    | Contractor Address     |

The system is **semi-automatic**: a human enters one İKN at a time (or a batch list), the program does everything else — fetch, parse, validate, save.

## 2. Non-Negotiable Constraints

- Language: **Python 3.11+**
- Output: **CSV** (UTF-8, `;` or `,` delimiter — confirm with user; Excel-opened CSVs from Turkey usually need `;` due to locale), with an option to export `.xlsx` via `openpyxl`/`pandas`.
- No hardcoded İKN values. İKN is always a runtime input.
- Every run must **append**, not overwrite, unless the user explicitly requests a fresh file.
- Respect the source: add request delays (min. 1–2s between requests), a realistic `User-Agent`, and stop-on-error rather than hammering the server on failure.

## 3. Critical Unknown — Investigate Before Coding

**EKAP v2 is a JavaScript single-page application (SPA).** A plain `requests.get()` + BeautifulSoup approach will almost certainly return an empty shell, not the rendered result data. Before writing extraction logic, the agent MUST:

1. Open `https://ekapv2.kik.gov.tr/ekap/search` in a browser with DevTools → Network tab open.
2. Search by a known İKN and identify the underlying **XHR/fetch calls** (likely JSON REST endpoints, e.g. something under `/ekap/api/...` or similar).
3. Inspect the response payload for a tender/contract detail endpoint — the required fields almost certainly live in a nested JSON object (`sozlesmeBilgileri`, `yuklenici`, etc.), not raw HTML.
4. Check whether search/detail endpoints require:
   - a CSRF/session token obtained from an initial page load,
   - specific headers (`Referer`, `X-Requested-With`, `Accept: application/json`),
   - or a login/captcha (if so, this changes the architecture — flag it to the user immediately, do not silently fall back to fragile scraping).

**Reference point:** a public MCP server ("İhale MCP", by saidsurucu, hosted at `ihalemcp.fastmcp.app`) already exposes `search_tenders` and tender-detail tools against EKAP v2. Its existence indicates a stable JSON API is reachable without a full browser. If accessible, inspecting its open-source implementation (search GitHub for `saidsurucu/ihale-mcp`) is a legitimate and fast way to shortcut endpoint discovery — treat it as a reference, not a dependency.

**Fallback plan** if no usable JSON API is found: use **Playwright** (preferred over Selenium — faster, better async support) to load the page headlessly, trigger the search, wait for the result DOM/network idle, and extract via the rendered DOM or by intercepting the same XHR responses through Playwright's `page.on("response")`.

Do not commit to either approach (API vs. browser automation) until step 1–4 above is done. This is the single highest-risk unknown in the project — resolve it first, before any CSV/CLI code.

## 4. Proposed Architecture

```
ekap-extractor/
├── AGENT.md
├── requirements.txt
├── config.py            # delays, output path, delimiter, headers
├── main.py              # CLI entry point — prompts for İKN(s)
├── ekap_client.py        # handles requests/session, auth/token if needed, calls the data source
├── parser.py             # maps raw API/HTML response -> the 6 required fields
├── storage.py             # CSV/XLSX append logic, dedup by İKN
├── models.py              # dataclass: ContractRecord(ikn, sozlesmeTarihi, ... )
└── output/
    └── sonuclar.csv
```

- `ekap_client.py` isolates all network/session logic. If the API approach works, this is a thin `requests.Session` wrapper. If Playwright is required, it lives here.
- `parser.py` is the only place that knows the shape of the raw response — keeps `main.py` stable if EKAP's response format changes.
- `models.py` defines a single `ContractRecord` dataclass with the 6 fields + `ikn` — used everywhere instead of raw dicts, to catch missing-field bugs early.

## 5. Data Handling Rules

- If a field is missing/empty in the response, store an empty string — never guess or fabricate a value.
- Always store the **İKN itself** as the first column (it's the join key even though not in the original field list).
- Deduplicate: if an İKN is already in the output file, either skip it or prompt to overwrite (ask the user which behavior they want — do not decide unilaterally).
- Log every failed İKN lookup (invalid number, not found, network error) to a separate `errors.log`, don't crash the whole batch on one bad İKN.

## 6. CLI Behavior (v1 scope)

```
$ python main.py
Enter İKN (or 'q' to quit): 2024/123456
✔ Contract data found, appended to output/sonuclar.csv
Enter İKN (or 'q' to quit): 2024/999999
✘ Not found / no contract data for this İKN — logged to errors.log
Enter İKN (or 'q' to quit): q
Done. 1 record saved, 1 error.
```

- Also accept a `--file ikn_list.txt` batch mode as a stretch goal, not v1-required.

## 7. Explicitly Out of Scope (for now)

- No GUI.
- No scheduling/automation beyond a single run.
- No handling of tenders with multiple contracts unless the data confirms this is common — ask the user if the discovery step reveals it.

## 8. Definition of Done (v1)

- [ ] Endpoint/rendering strategy confirmed and documented in this file (update Section 3 with actual findings).
- [ ] Given a real, valid İKN, the tool produces a correct one-row CSV output matching the 6 required fields.
- [ ] Given an invalid/nonexistent İKN, the tool fails gracefully with a logged error, no crash.
- [ ] Re-running with the same İKN doesn't silently duplicate the row.
