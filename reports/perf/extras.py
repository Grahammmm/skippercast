#!/usr/bin/env python3
"""PERF-BASELINE-1 extras: per (page, profile, pass) medians of figures the main summary does not carry.

Usage: python3 reports/perf/extras.py <raw.json> ... > reports/perf/raw/extras.json
- warmNetworkRequests / warmNetworkBytes: requests on the pass that still went to the network (not from the
  browser cache), and their bytes; on a warm pass this is what cache headers fail to keep local.
- noStoreBytes: bytes of responses sent with Cache-Control no-store.
- thirdPartyRequests / thirdPartyBytes: requests to hosts other than skippercast.com and the local test server.
- scriptMs / settledMs: JS script time and the network-settle window, reported side by side. They are NOT divided into
  a duty cycle: in the earlier runs the CPU counters were read after page.evaluate (which waits for a busy main thread),
  so the counter window was longer than settledMs (phone-wifi brief: 23 s of script in a 12.2 s settle window). Runs made
  with the fixed measure.mjs also carry metricsWindowS (CDP monotonic clock over the exact counter window); only then is
  scriptMs / metricsWindowS reported (scriptShareOfWindow), and ScriptDuration under CPU throttling is still unvalidated.
- requestsBeforeFcp: requests started before the first contentful paint.
"""
import gzip
import json
import statistics
import sys
from collections import defaultdict
from urllib.parse import urlparse


def med(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 3) if v else None


groups = defaultdict(list)
for path in sys.argv[1:]:
    doc = json.load(gzip.open(path, 'rt') if path.endswith('.gz') else open(path))
    own = urlparse(doc['base']).hostname
    for r in doc['results']:
        if 'error' in r:
            continue
        reqs = r['requests']
        net = [q for q in reqs if not q['fromCache'] and not q['url'].startswith('data:')]
        third = [q for q in reqs if urlparse(q['url']).hostname not in (own, None) and not q['url'].startswith('data:')]
        reqs = [q for q in reqs if not q['url'].startswith(('data:', 'blob:'))]
        nostore = [q for q in reqs if (q.get('cacheControl') or '').find('no-store') >= 0]
        groups[(r['page'], r['profile'], r['pass'])].append({
            'warmNetworkRequests': len(net), 'warmNetworkBytes': sum(q['bytes'] or 0 for q in net),
            'noStoreRequests': len(nostore), 'noStoreBytes': sum(q['bytes'] or 0 for q in nostore),
            'thirdPartyRequests': len(third), 'thirdPartyBytes': sum(q['bytes'] or 0 for q in third),
            'thirdPartyHosts': sorted({urlparse(q['url']).hostname for q in third}),
            'scriptMs': r.get('scriptMs'), 'metricsWindowS': r.get('metricsWindowS'),
            'scriptShareOfWindow': round(r['scriptMs'] / (r['metricsWindowS'] * 1000), 3) if r.get('metricsWindowS') else None,
            'requestsBeforeFcp': r.get('requestsBeforeFcp'), 'settledMs': r.get('settledMs'), 'domNodes': r.get('domNodes'),
        })
out = []
for (page, prof, pas), runs in sorted(groups.items()):
    row = {'page': page, 'profile': prof, 'pass': pas, 'runs': len(runs)}
    for k in runs[0]:
        row[k] = runs[0][k] if k == 'thirdPartyHosts' else med([x[k] for x in runs])
    out.append(row)
print(json.dumps(out, indent=1))
