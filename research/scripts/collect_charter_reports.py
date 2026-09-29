"""Read public landing-reported trip facts, retaining source URLs and coverage."""
import argparse, concurrent.futures, datetime, hashlib, html, json, re, time, urllib.request
from pathlib import Path
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--start', required=True, type=datetime.date.fromisoformat)
parser.add_argument('--end', required=True, type=datetime.date.fromisoformat)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
if args.end < args.start:
    parser.error('End must be on or after start')
ROOT = args.output.resolve()
ROOT.mkdir(parents=True, exist_ok=True)
RAW = ROOT / 'raw'
RAW.mkdir(exist_ok=True)

def plain(s):
    return re.sub('\\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', s))).strip()

def collect(day):
    url = 'https://www.socalfishreports.com/dock_totals/boats.php?date=' + day
    path = RAW / ('counts-' + day + '.html')
    meta = path.with_suffix('.meta.json')
    try:
        if not path.exists() or not meta.exists():
            with urllib.request.urlopen(url, timeout=25) as r:
                b = r.read()
                path.write_bytes(b)
                meta.write_text(json.dumps({'url': url, 'http_status': r.status, 'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sha256': hashlib.sha256(b).hexdigest()}, indent=2))
            time.sleep(0.2)
        s = path.read_text()
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
            rows.append({'date': day, 'boat': plain(boat[1]), 'port': 'Morro Bay' if 'Morro Bay, CA' in td[0] else 'Avila Beach', 'ground': plain(ground[1]) if ground else None, 'species': species, 'trip': plain(td[1]), 'reported_catch': count, 'source_url': url, 'vessel_source_url': 'https://www.socalfishreports.com' + links[0]})
        return {'date': day, 'status': 'ok', 'records': rows}
    except Exception as e:
        return {'date': day, 'status': 'failed', 'error': str(e)}
start = args.start
end = args.end
days = [(start + datetime.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for n, r in enumerate(pool.map(collect, days), 1):
        results.append(r)
        if n % 15 == 0:
            print('Reviewed', n, 'of', len(days), 'dates', flush=True)
rows = [x for r in results if r['status'] == 'ok' for x in r['records']]
(ROOT / 'trip-facts.json').write_text(json.dumps({'coverage': results, 'records': rows}, indent=2))
from collections import Counter
print(json.dumps({'pages': len(results), 'failed': [r for r in results if r['status'] != 'ok'], 'local_trips': len(rows), 'grounds': dict(Counter((x['ground'] or '(not reported)' for x in rows)))}, indent=2))
