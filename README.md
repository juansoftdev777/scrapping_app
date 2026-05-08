# Event Scraping Dashboard

Modular Streamlit app for scraping event data from a venue list `.docx` and exporting records in the target schema from `.xlsx`.

## What it does

- Loads venue sources from your Word file (`Type X`, venue name, URLs).
- Loads target output fields from your Excel template headers.
- Scrapes selected venues on demand from a simple dashboard UI.
- Prioritizes required fields:
  - `name` (event name)
  - `venuesName` (venue name)
  - `startDate`
  - `startTime`
- Attempts to collect additional fields where available (description, tickets link, city/state, price, etc.).
- Exports as CSV and Excel.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Usage

1. Set the `.docx` and `.xlsx` paths in the sidebar or upload both files.
2. Choose categories and optionally search venues.
3. Click **Start Scraping**.
4. Review results and export.

## Modularity

- Add/update source sites by editing the `.docx` only.
- Add/update output fields by editing the `.xlsx` header row.
- Scraping logic is split into reusable modules:
  - `scraper/source_loader.py`
  - `scraper/field_schema.py`
  - `scraper/extractors.py`
  - `scraper/service.py`

## Note

Some sites are JavaScript-heavy and may require a browser-rendered scraper (Playwright/Selenium adapter) for deeper coverage. The current implementation uses HTTP + HTML/JSON-LD extraction for speed and portability.
