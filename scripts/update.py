#!/usr/bin/env python3
"""Conservative X quote updater for Poke Asset Cloud.
Uses the official X API only, plus an authorized CSV feed. No scraping.
"""
import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
CATALOG = DATA / 'catalog.json'
PRICES = DATA / 'prices.json'
HISTORY = DATA / 'history.json'
JST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(dt.timezone.utc)
MAX_AGE_HOURS = 48


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def age_ok(value):
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.tzinfo is not None and dt.timedelta(0) <= NOW - stamp.astimezone(dt.timezone.utc) <= dt.timedelta(hours=MAX_AGE_HOURS)
    except (TypeError, ValueError):
        return False


def product_names(product):
    return [s.strip() for s in [product['name'], *product.get('aliases', [])] if s.strip() and len(s.strip()) >= 2]


def extract_quote(text, product, all_products):
    """Accept only a clear product/price pair on a single line in a buyback post.

    Ambiguous posts are intentionally skipped rather than assigned a wrong quote.
    """
    if not re.search(r'買取', text):
        return None
    if re.search(r'シュリンクなし|シュリンク無|シュリンク無し|開封済|訳あり', text):
        # Stock condition cannot yet be represented in product master.
        return None
    matches = []
    names = product_names(product)
    for line in text.splitlines():
        # Don't match another SKU's amount in a multi-SKU line.
        if any(any(alias in line for alias in product_names(other)) for other in all_products if other['id'] != product['id']):
            continue
        for name in names:
            # Strongly require amount next to the precise product name.
            m = re.search(re.escape(name) + r'[^\n\d]{0,18}(?:[¥￥]\s*)?([1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{2,6})\s*円?', line)
            if m:
                amount = int(m.group(1).replace(',', ''))
                if 500 <= amount <= 2_000_000:
                    matches.append(amount)
    return matches[0] if len(set(matches)) == 1 and matches else None


def source_row(price_type):
    return {'price': None, 'count': 0, 'type': price_type, 'samples': []}


def run():
    products = read_json(CATALOG, [])
    if not isinstance(products, list):
        raise ValueError('data/catalog.json must be a JSON array')
    old = read_json(PRICES, {})
    history = read_json(HISTORY, [])
    quotes = {p['id']: {'x': [], 'mercari': [], 'snkrdunk': []} for p in products}
    warnings = []
    feed = os.getenv('AUTHORIZED_PRICE_CSV_URL', '').strip()
    if feed:
        try:
            if not feed.startswith('https://'):
                raise ValueError('CSV feed must use HTTPS')
            req = urllib.request.Request(feed, headers={'User-Agent': 'PokeAssetTracker/1.1'})
            raw = urllib.request.urlopen(req, timeout=20).read(3_000_001)
            if len(raw) > 3_000_000:
                raise ValueError('CSV too large')
            for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
                pid = row.get('id', '').strip()
                source = row.get('source', '').strip().lower()
                kind = row.get('price_type', '').strip()
                if pid not in quotes or source not in quotes[pid]:
                    continue
                if kind != ('buy_offer' if source == 'x' else 'sold') or not age_ok(row.get('observed_at')):
                    continue
                amount = int(float(row.get('price', '0')))
                if 500 <= amount <= 2_000_000:
                    quotes[pid][source].append({'price': amount, 'url': row.get('url', ''), 'observed_at': row['observed_at'], 'type': kind, 'origin': 'authorized_csv'})
        except Exception as e:
            warnings.append('Authorized CSV: ' + str(e)[:160])

    token = os.getenv('X_BEARER_TOKEN', '').strip()
    accounts = [a.strip().lstrip('@') for a in os.getenv('X_SELLER_ACCOUNTS', '').split(',') if a.strip()]
    accounts = list(dict.fromkeys(a for a in accounts if re.fullmatch(r'[A-Za-z0-9_]{1,15}', a)))[:10]
    if token and accounts and products:
        # ONE query for all registered SKUs, rather than one paid request per SKU.
        terms = list(dict.fromkeys(p['name'] for p in products))
        # Query length is limited; don't silently omit SKUs.
        filters = '(' + ' OR '.join('from:' + a for a in accounts) + ')'
        query = '(' + ' OR '.join('"' + s.replace('"', '') + '"' for s in terms) + ') ' + filters + ' -is:retweet'
        if len(query) > 480:
            warnings.append('Too many catalog products for one X query; add search batching before expanding.')
        else:
            try:
                url = 'https://api.x.com/2/tweets/search/recent?' + urllib.parse.urlencode({
                    'query': query, 'max_results': 100, 'tweet.fields': 'created_at'
                })
                req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'PokeAssetTracker/1.1'})
                with urllib.request.urlopen(req, timeout=20) as response:
                    result = json.load(response)
                for tweet in result.get('data', []):
                    if not age_ok(tweet.get('created_at')):
                        continue
                    for p in products:
                        price = extract_quote(tweet.get('text', ''), p, products)
                        if price is not None:
                            quotes[p['id']]['x'].append({
                                'price': price, 'url': 'https://x.com/i/web/status/' + str(tweet['id']),
                                'observed_at': tweet['created_at'], 'type': 'buy_offer', 'origin': 'official_x_api'
                            })
            except urllib.error.HTTPError as e:
                warnings.append('X API HTTP ' + str(e.code) + ' (authentication, billing, or search permission)')
            except Exception as e:
                warnings.append('X API: ' + str(e)[:160])
    elif not token or not accounts:
        warnings.append('X API: token or seller accounts not configured')

    results = {}
    for p in products:
        pid = p['id']
        sources = {}
        source_prices = []
        for source, entries in quotes[pid].items():
            price_type = 'buy_offer' if source == 'x' else 'sold'
            row = source_row(price_type)
            if entries:
                row.update({'price': int(statistics.median(e['price'] for e in entries)),
                            'count': len(entries), 'samples': entries[:12]})
                source_prices.append(row['price'])
            sources[source] = row
        results[pid] = {
            'sources': sources,
            'reference_average': round(statistics.mean(source_prices)) if source_prices else None,
            'source_count': len(source_prices),
            'previous_average': old.get('products', {}).get(pid, {}).get('reference_average')
        }
    record = {
        'updated_at': NOW.astimezone(JST).isoformat(timespec='seconds'),
        'products': results, 'warnings': warnings,
        'method': 'simple mean of available source medians, max age 48h; X buy offers and marketplace sold prices differ'
    }
    PRICES.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    day = NOW.astimezone(JST).date().isoformat()
    snapshot = {'date': day, 'prices': {k: v['reference_average'] for k, v in results.items()}}
    history = [h for h in history if h.get('date') != day] + [snapshot]
    HISTORY.write_text(json.dumps(history[-365:], ensure_ascii=False, indent=2), encoding='utf-8')
    print('Finished:', day, 'priced products', sum(p['source_count'] > 0 for p in results.values()), 'warnings', len(warnings))


if __name__ == '__main__':
    run()
