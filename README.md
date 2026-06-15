Very simple website that check distance between suburbs in Sydney. Useful to choose your casual gig around the city on a day 2 day basis.
More helpful as part of a automated environment checking directly against the job offers.

Can check distance between 2 suburbs and driving distance by leveraging the [Ooenroute service API](https://openrouteservice.org/).

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
