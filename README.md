# Screwfix Impact Wrench Scraper & Dashboard

Scrapes all **impact wrench** products from Screwfix.com — search listings + full detail-page spec sheets (29+ specs per product).

## Data

- **110 products** across **7 brands** (Milwaukee, DEWALT, Makita, Bosch, Einhell, Erbauer, Skil)
- **Full spec tables** extracted: Max Torque, Battery Chemistry, Chuck Type, No Load Speed, etc.
- Outputs: SQLite (`screwfix_impact.db`) + CSV (`screwfix_impact.csv`)

## Usage

```bash
python3 screwfix_impact_wrench.py --search "impact wrench" --db impact.db --csv impact.csv
python3 screwfix_impact_wrench.py --no-details  # skip detail pages
```

## Dashboard

Live at: https://nutcelvischen-jpg.github.io/screwfix-impact-wrench/

## Tech

- Two-layer scraping: LD+JSON ItemList (search) + HTML spec table (detail)
- Plotly.js charts, CRT/industrial dark theme
- GitHub Pages auto-deploy via GitHub Actions