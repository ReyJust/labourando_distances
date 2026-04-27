Scrape Sydney suburbs

Usage

1. Create a virtual environment and install dependencies with uv:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt 
```

2. Run the scraper:

```bash
python3 scripts/scrape_sydney_suburbs.py
```

Outputs are written to `data/sydney_suburbs.txt` and `data/sydney_suburbs.csv`.
