# eCourts Scraper

demo video: https://youtu.be/hobXgwJa1So

A live cause-list scraper with a small React UI and a Flask API.

- Real-time hierarchy: State → District → Complex → Court
- Fetch cause lists by date (Civil/Criminal)
- Download single-court PDF and all-courts ZIP
- CNR search and basic stats
- REST API and optional CLI

## Quick start

Requirements: Python 3.10+, Node 16+

### Backend

Windows (PowerShell)
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python api.py
```

Linux/macOS (bash)
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python api.py
```

### Frontend

```
cd ecourts-frontend
npm install
npm run dev
open http://localhost:5173
```

API at http://localhost:5000/api

## How to use (UI)

1. Select State → District → Complex → Court
2. Pick date (DD-MM-YYYY in payload)
3. Click Refresh to load captcha, type it, then:
   - Fetch: show cause list table and filters
   - PDF: download single court's list (remember to install WeasyPrint or wkhtmltopdf(need to set path))
   - ZIP: download all courts in the complex

Note: The site uses captcha; refresh invalidates the previous code.


## Optional: CLI

```
python cli.py --interactive --causelist --date 01-11-2025
python cli.py --today --state-code 4 --dist-code 3 --complex-code 1040029 --court-code "2^7"
```

## PDF generation

The API first tries WeasyPrint, then falls back to wkhtmltopdf (pdfkit).

If PDFs fail, install wkhtmltopdf or WeasyPrint deps. The API writes debug HTML to output/last_causelist.html.

## Output

- output/result_*.json: responses
- output/causelist_*.pdf: PDFs
- output/causelist_all_*.zip: ZIP for all courts
- output/last_causelist.html: raw HTML for debugging

## Troubleshooting

- Invalid captcha: refresh the image, retype, submit within ~1–2 minutes
- No cases found: some courts/dates have no list; try Civil/Criminal toggle, or tomorrow's date
- PDFs not generated: install wkhtmltopdf or WeasyPrint system libs
- Token errors: restart API (the app handles token rotation automatically)

## Notes

- Live hierarchy is fetched from eCourts; no sample data is cached
- Please respect terms of use and fair rate limits