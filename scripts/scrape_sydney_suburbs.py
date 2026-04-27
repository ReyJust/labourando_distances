#!/usr/bin/env python3
"""Scrape list of Sydney suburbs from Wikipedia and save to files.

Saves two outputs:
- data/sydney_suburbs.txt (one suburb per line)
- data/sydney_suburbs.csv (CSV with a single column `suburb`)

Usage: python3 scripts/scrape_sydney_suburbs.py
"""

from pathlib import Path
import requests
from bs4 import BeautifulSoup
import urllib.parse
import csv
import re
import time
import random
from typing import Optional

URL = "https://en.wikipedia.org/wiki/List_of_Sydney_suburbs"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
    )
}

OUT_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_html(url: str, timeout: int = 10, tries: int = 2, min_length: int = 40) -> Optional[str]:
    """Fetch URL with timeout, simple retry, and content-type check.

    Returns response text if successful and looks like HTML, otherwise None.
    """
    for attempt in range(tries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            # require successful status
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            ctype = resp.headers.get('Content-Type', '')
            if 'html' not in ctype.lower():
                # not HTML, skip
                raise Exception(f"Not HTML: {ctype}")
            text = resp.text or ''
            if len(text.strip()) < min_length:
                raise Exception("Response content too short")
            return text
        except Exception:
            # small backoff then retry
            time.sleep(0.5 * (attempt + 1))
            continue
    return None


def normalize(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    # remove footnote markers like [1]
    name = re.sub(r"\[.*?\]", "", name)
    # remove common trailing place/state suffixes like ", New South Wales" or ", NSW"
    name = re.sub(r",\s*(New\s+South\s+Wales|NSW|Australia)\.?$", "", name, flags=re.I)
    # remove trailing dashes or hyphens (en-dash, em-dash, plain hyphen) and surrounding space
    name = re.sub(r"\s*[\u2013\u2014-]+\s*$", "", name)
    # remove trailing punctuation like commas/colons/semicolons
    name = re.sub(r"[,:;\.]\s*$", "", name)
    name = name.strip()
    return name


def extract_suburbs_from_soup(soup: BeautifulSoup) -> list:
    content = soup.select_one("div.mw-parser-output")
    if content is None:
        return []
    suburbs = []

    # Collect links from paragraph and list blocks that contain multiple wiki links.
    # On this page suburbs are often in <p> blocks with many <a> tags separated by dashes.
    def collect_from_block(block):
        local = []
        for a in block.find_all('a', href=True):
            href = a.get('href')
            if not href.startswith('/wiki/'):
                continue
            if ':' in href:
                continue
            name = normalize(a.get_text())
            if not name:
                continue
            if re.search(r"\d{4,}|http|www\.|\(|\)", name):
                continue
            url = urllib.parse.urljoin('https://en.wikipedia.org', href)
            local.append((name, url))
        return local

    # paragraphs with many links, but only if the nearest previous h2 is an A-Z or 0–9 section
    for p in content.find_all('p'):
        # skip if this paragraph is inside a navbox/template table
        if p.find_parent('table', class_=lambda c: c and 'navbox' in c):
            continue
        prev_h2 = p.find_previous(lambda tag: tag.name == 'h2')
        if not prev_h2:
            continue
        hid = (prev_h2.get('id') or '')
        if not (hid == '0–9' or (len(hid) == 1 and hid.isalpha())):
            continue
        links = [a for a in p.find_all('a', href=True) if a.get('href','').startswith('/wiki/') and ':' not in a.get('href','')]
        # allow single-link paragraphs (Z section) and multi-link paragraphs
        if len(links) >= 1:
            suburbs.extend(collect_from_block(p))

    # list blocks (ul/ol) with many links
    for lst in content.find_all(['ul', 'ol']):
        # skip navbox/tables
        if lst.find_parent('table', class_=lambda c: c and 'navbox' in c):
            continue
        prev_h2 = lst.find_previous(lambda tag: tag.name == 'h2')
        if not prev_h2:
            continue
        hid = (prev_h2.get('id') or '')
        if not (hid == '0–9' or (len(hid) == 1 and hid.isalpha())):
            continue
        links = [a for a in lst.find_all('a', href=True) if a.get('href','').startswith('/wiki/') and ':' not in a.get('href','')]
        if len(links) >= 1:
            suburbs.extend(collect_from_block(lst))

    # fallback: small multi-column divs
    for div in content.find_all('div', class_=lambda c: c and 'div-col' in c):
        suburbs.extend(collect_from_block(div))

    # deduplicate while preserving order (by name)
    seen = set()
    uniq = []
    for name, url in suburbs:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, url))

    return uniq


def extract_coords_from_soup(soup: BeautifulSoup):
    # Try to find a numeric coordinate pair in hidden .geo span first
    geo = soup.select_one('.geo')
    if geo and geo.get_text(strip=True):
        txt = geo.get_text(strip=True)
        # format often is '-33.86972; 150.86472'
        if ';' in txt:
            parts = [p.strip() for p in txt.split(';')]
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                return lat, lon
            except Exception:
                pass

    # Try geo-dec (e.g., '33.86972°S 150.86472°E') -> fallback to parse decimals
    geo_dec = soup.select_one('.geo-dec')
    if geo_dec and geo_dec.get_text(strip=True):
        txt = geo_dec.get_text(strip=True)
        nums = re.findall(r"-?\d+\.\d+", txt)
        if len(nums) >= 2:
            try:
                lat = float(nums[0])
                lon = float(nums[1])
                # sign may be lost for S/W; attempt to detect S or W markers
                if re.search(r"[NS]", txt.split()[0], re.I):
                    if re.search(r"S", txt.split()[0], re.I):
                        lat = -abs(lat)
                if re.search(r"[EW]", txt.split()[-1], re.I):
                    if re.search(r"W", txt.split()[-1], re.I):
                        lon = -abs(lon)
                return lat, lon
            except Exception:
                pass

    # Try separate latitude/longitude spans
    lat_span = soup.select_one('.latitude')
    lon_span = soup.select_one('.longitude')
    if lat_span and lon_span:
        try:
            lat = float(re.search(r"-?\d+\.\d+", lat_span.get_text()).group())
            lon = float(re.search(r"-?\d+\.\d+", lon_span.get_text()).group())
            return lat, lon
        except Exception:
            pass

    return None, None


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Scrape Sydney suburbs')
    parser.add_argument('--single', help='Process a single local HTML file path or URL')
    parser.add_argument('--write', action='store_true', help='When used with --single, write/update CSV')
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]

    if args.single:
        target = args.single
        # determine if URL or local file
        if urllib.parse.urlparse(target).scheme in ('http', 'https'):
            print(f"Fetching single URL {target}")
            text = fetch_html(target, timeout=15, tries=3)
            if not text:
                raise SystemExit(f"Failed to fetch HTML or non-HTML response: {target}")
            soup = BeautifulSoup(text, 'lxml')
            # attempt to extract page title for name
            title = soup.select_one('h1.firstHeading')
            name = title.get_text(strip=True) if title else target
            url = target
        else:
            # local file
            local = Path(target)
            if not local.exists():
                local = base_dir / target
            if not local.exists():
                raise SystemExit(f"File not found: {target}")
            print(f"Reading local file {local}")
            text = local.read_text(encoding='utf-8')
            soup = BeautifulSoup(text, 'lxml')
            # attempt to extract page title for name
            title = soup.select_one('h1.firstHeading')
            if not title:
                # fallback: infobox name
                inf = soup.select_one('.infobox .fn') or soup.select_one('.infobox .org')
                name = inf.get_text(strip=True) if inf else local.stem
            else:
                name = title.get_text(strip=True)
            url = ''

        lat, lon = extract_coords_from_soup(soup)
        print(f"Single page: {name} -> lat={lat} lon={lon}")

        if args.write:
            # write/update CSV for this single entry
            csv_path = OUT_DIR / 'sydney_suburbs.csv'
            # read existing CSV and collapse duplicates by normalized suburb name
            entries = {}
            order = []
            if csv_path.exists():
                with csv_path.open('r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = normalize(row.get('suburb') or '')
                        if key not in entries:
                            entries[key] = {
                                'suburb': row.get('suburb', ''),
                                'url': row.get('url', ''),
                                'lat': row.get('lat', ''),
                                'lon': row.get('lon', '')
                            }
                            order.append(key)
                        else:
                            # merge missing fields from duplicate rows
                            e = entries[key]
                            if not e.get('url') and row.get('url'):
                                e['url'] = row.get('url')
                            if not e.get('lat') and row.get('lat'):
                                e['lat'] = row.get('lat')
                            if not e.get('lon') and row.get('lon'):
                                e['lon'] = row.get('lon')

            tkey = normalize(name)
            if tkey in entries:
                e = entries[tkey]
                e['url'] = url or e.get('url', '')
                e['lat'] = lat if lat is not None else e.get('lat', '')
                e['lon'] = lon if lon is not None else e.get('lon', '')
            else:
                entries[tkey] = {'suburb': name, 'url': url, 'lat': lat if lat is not None else '', 'lon': lon if lon is not None else ''}
                order.append(tkey)

            rows = [entries[k] for k in order]
            with csv_path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['suburb', 'url', 'lat', 'lon'])
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
            print(f"Wrote/updated {csv_path}")
        return

    # Prefer local copy if available
    local_html = base_dir / 'suburbs.html'
    if local_html.exists():
        print(f"Reading local file {local_html}")
        text = local_html.read_text(encoding='utf-8')
        soup = BeautifulSoup(text, 'lxml')
    else:
        print(f"Fetching {URL} ...")
        text = fetch_html(URL, timeout=20, tries=3)
        if not text:
            raise SystemExit(f"Failed to fetch main page or received non-HTML response: {URL}")
        soup = BeautifulSoup(text, "lxml")

    suburbs = extract_suburbs_from_soup(soup)
    print(f"Found {len(suburbs)} candidate suburbs (after dedupe)")

    # Prepare lookup of local HTML files
    html_files = {p.name.lower(): p for p in base_dir.glob('*.html')}

    csv_path = OUT_DIR / "sydney_suburbs.csv"
    RATE_LIMIT = 0.8
    # If CSV exists, load existing entries to preserve data and avoid refetching
    existing_rows = []
    existing_by_name = {}
    if csv_path.exists():
        with csv_path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                suburb_name = row.get('suburb') or row.get('name') or ''
                url_val = row.get('url', '')
                lat_val = row.get('lat', '')
                lon_val = row.get('lon', '')
                entry = {'suburb': suburb_name, 'url': url_val, 'lat': lat_val, 'lon': lon_val}
                existing_rows.append(entry)
                existing_by_name[normalize(suburb_name)] = entry

    # Ensure CSV has header for incremental appends
    header = ['suburb', 'url', 'lat', 'lon']
    if not csv_path.exists():
        with csv_path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)

    # track which normalized suburbs already have coordinates (to skip)
    processed = set()
    for k, v in existing_by_name.items():
        if v.get('lat') and v.get('lon'):
            processed.add(k)

    results = []

    # open append file to write progress incrementally
    append_f = csv_path.open('a', encoding='utf-8', newline='')
    append_writer = csv.writer(append_f)

    try:
        for idx, (name, url) in enumerate(suburbs, 1):
            nname = normalize(name)
            # If we already have coords recorded, skip fetching
            if nname in processed:
                entry = existing_by_name.get(nname)
                results.append((entry['suburb'], entry['url'], entry['lat'], entry['lon']))
                print(f"{idx}/{len(suburbs)}: {name} - already have coords, skipping")
                continue

            lat = lon = None
            candidate = None

            # attempt to match local HTML copies by slug or normalized name
            parsed = urllib.parse.urlparse(url)
            slug = parsed.path.split('/wiki/')[-1]
            slug_fn = f"{slug}.html".lower()
            if slug_fn in html_files:
                candidate = html_files[slug_fn]
            else:
                norm_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip('_')
                if f"{norm_name}.html" in html_files:
                    candidate = html_files[f"{norm_name}.html"]

            if candidate:
                try:
                    text2 = candidate.read_text(encoding='utf-8')
                    soup2 = BeautifulSoup(text2, 'lxml')
                    lat, lon = extract_coords_from_soup(soup2)
                    print(f"{idx}/{len(suburbs)}: {name} - read local file {candidate.name} -> {lat},{lon}")
                except Exception as e:
                    print(f"{idx}/{len(suburbs)}: {name} - failed reading local file: {e}")
            else:
                # fetch remote page (with retries inside fetch_html)
                try:
                    text2 = fetch_html(url, timeout=12, tries=2)
                    if text2:
                        soup2 = BeautifulSoup(text2, 'lxml')
                        lat, lon = extract_coords_from_soup(soup2)
                        print(f"{idx}/{len(suburbs)}: {name} - fetched remote -> {lat},{lon}")
                    else:
                        print(f"{idx}/{len(suburbs)}: {name} - failed to fetch page or non-HTML")
                except Exception as e:
                    print(f"{idx}/{len(suburbs)}: {name} - fetch exception: {e}")

                # always respect rate limit after remote fetch attempt
                time.sleep(RATE_LIMIT + random.random() * 0.4)

            # record result and append row incrementally
            results.append((name, url, lat if lat is not None else '', lon if lon is not None else ''))
            append_writer.writerow([name, url, lat if lat is not None else '', lon if lon is not None else ''])
            append_f.flush()
            if nname in existing_by_name:
                # update existing entry in-memory
                existing_by_name[nname]['url'] = existing_by_name[nname].get('url') or url
                existing_by_name[nname]['lat'] = lat if lat is not None else existing_by_name[nname].get('lat', '')
                existing_by_name[nname]['lon'] = lon if lon is not None else existing_by_name[nname].get('lon', '')
            else:
                existing_by_name[nname] = {'suburb': name, 'url': url, 'lat': lat if lat is not None else '', 'lon': lon if lon is not None else ''}

            if lat is not None and lon is not None:
                processed.add(nname)

    finally:
        append_f.close()

    # Append any existing rows that were not in the freshly extracted list (preserve them)
    seen = set([normalize(r[0]) for r in results])
    for entry in existing_rows:
        if normalize(entry['suburb']) not in seen:
            results.append((entry['suburb'], entry['url'], entry['lat'], entry['lon']))

    # Final: overwrite CSV with merged, deduplicated entries
    merged = {}
    order = []
    for name, url, lat, lon in results:
        key = normalize(name)
        if key not in merged:
            merged[key] = {'suburb': name, 'url': url, 'lat': lat, 'lon': lon}
            order.append(key)
        else:
            e = merged[key]
            if not e.get('url') and url:
                e['url'] = url
            if (not e.get('lat') or not e.get('lon')) and (lat and lon):
                e['lat'] = lat
                e['lon'] = lon

    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for k in order:
            writer.writerow(merged[k])

    # Append any existing rows that were not in the freshly extracted list (preserve them)
    seen = set([normalize(r[0]) for r in results])
    for entry in existing_rows:
        if normalize(entry['suburb']) not in seen:
            results.append((entry['suburb'], entry['url'], entry['lat'], entry['lon']))

    # Save text file (tab-separated name, url, lat, lon)
    txt_path = OUT_DIR / "sydney_suburbs.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        for name, url, lat, lon in results:
            f.write(f"{name}\t{url}\t{lat}\t{lon}\n")

    with csv_path.open("w", encoding="utf-8", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["suburb", "url", "lat", "lon"])
        for name, url, lat, lon in results:
            writer.writerow([name, url, lat if lat is not None else '', lon if lon is not None else ''])

    print(f"Saved {len(results)} suburbs to {txt_path} and {csv_path}")


if __name__ == '__main__':
    main()
