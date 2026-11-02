"""Read public landing-reported trip facts, retaining source URLs and coverage."""
import argparse, concurrent.futures, datetime, hashlib, html, json, os, re, time, urllib.request
from pathlib import Path

def plain(s):
    return re.sub('\\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', s))).strip()

def urlopen_fetch(url):
    with urllib.request.urlopen(url, timeout=25) as r:
        return r.read(), r.status

def parse_page(day, s, url):
    rows = []
    date = datetime.date.fromisoformat(day)
    expected = f"{date.strftime('%B')} {date.day}, {date.year}"
    if expected not in s:
        raise ValueError('Returned page date does not match requested date')
    for tr in re.split('<tr\\b[^>]*>', s, flags=re.I):
        td = re.findall('<td\\b[^>]*>(.*?)</td>', tr.split('</tr>')[0], flags=re.S | re.I)
        if len(td) < 3 or not any((x in td[0] for x in ['Morro Bay, CA', 'Avila Beach, CA'])):
            continue
        boat = re.search('<b>(.*?)</b>', td[0], re.S)
        if not boat:
            continue
        ground = re.search('<i>(.*?)</i>', td[1], re.S)
        links = re.findall('href="([^"]+)"', td[0])
        count = plain(td[2])
        species = []
        for pattern, key in [('Lingcod', 'lingcod'), ('Rockcod|Rockfish|Bocaccio|Bolina', 'rockfish'), ('Halibut', 'halibut'), ('King Salmon|Chinook|Salmon', 'salmon'), ('Bluefin', 'bluefin'), ('Albacore', 'albacore'), ('Dungeness', 'dungeness')]:
            if re.search(pattern, count, re.I):
                species.append(key)
        rows.append({'date': day, 'boat': plain(boat[1]), 'port': 'Morro Bay' if 'Morro Bay, CA' in td[0] else 'Avila Beach', 'ground': plain(ground[1]) if ground else None, 'species': species, 'trip': plain(td[1]), 'reported_catch': count, 'source_url': url, 'vessel_source_url': 'https://www.socalfishreports.com' + links[0] if links else None})
    return rows

def collect(day, raw_dir, fetch=urlopen_fetch):
    url = 'https://www.socalfishreports.com/dock_totals/boats.php?date=' + day
    path = Path(raw_dir) / ('counts-' + day + '.html')
    meta = path.with_suffix('.meta.json')
    try:
        if not path.exists() or not meta.exists():
            b, status = fetch(url)
            path.write_bytes(b)
            meta.write_text(json.dumps({'url': url, 'http_status': status, 'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sha256': hashlib.sha256(b).hexdigest()}, indent=2))
            time.sleep(0.2)
        s = path.read_text(encoding='utf-8')
        return {'date': day, 'status': 'ok', 'records': parse_page(day, s, url)}
    except UnicodeDecodeError as e:
        return {'date': day, 'status': 'failed', 'error': 'UnicodeDecodeError: ' + str(e)}
    except Exception as e:
        return {'date': day, 'status': 'failed', 'error': str(e)}

def main(argv=None, fetch=urlopen_fetch):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True, type=datetime.date.fromisoformat)
    parser.add_argument('--end', required=True, type=datetime.date.fromisoformat)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error('End must be on or after start')
    ROOT = args.output.resolve()
    ROOT.mkdir(parents=True, exist_ok=True)
    RAW = ROOT / 'raw'
    RAW.mkdir(exist_ok=True)
    start = args.start
    end = args.end
    days = [(start + datetime.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for n, r in enumerate(pool.map(lambda d: collect(d, RAW, fetch), days), 1):
            results.append(r)
            if n % 15 == 0:
                print('Reviewed', n, 'of', len(days), 'dates', flush=True)
    rows = [x for r in results if r['status'] == 'ok' for x in r['records']]
    tmp = ROOT / 'trip-facts.json.tmp'
    tmp.write_text(json.dumps({'coverage': results, 'records': rows}, indent=2))
    os.replace(tmp, ROOT / 'trip-facts.json')
    from collections import Counter
    print(json.dumps({'pages': len(results), 'failed': [r for r in results if r['status'] != 'ok'], 'local_trips': len(rows), 'grounds': dict(Counter((x['ground'] or '(not reported)' for x in rows)))}, indent=2))

if __name__ == '__main__':
    main()
