#!/usr/bin/env python3
"""PERF-BASELINE-1 extras: per (page, profile, pass) medians of figures the main summary does not carry.

Usage: python3 reports/perf/extras.py <raw.json> ... > reports/perf/raw/extras.json
- warmNetworkRequests / warmNetworkBytes: requests on the pass that still went to the network (not from the
  browser cache), and their bytes; on a warm pass this is what cache headers fail to keep local.
- noStoreBytes: bytes of responses sent with Cache-Control no-store.
- thirdPartyRequests / thirdPartyBytes: requests to hosts other than skippercast.com and the local test server.
- (round 2) the former scriptMsPerSecond (ScriptDuration / settledMs) is WITHDRAWN: settledMs is when the network went
  quiet, but CDP's metrics were read after the page's backlog of main-thread work had drained, so the ratio could exceed
  100% (phone-Wi-Fi brief: ~23 s of script over a 12.2 s "window"). The duty cycle is re-measured in readiness.mjs, which
  reads ScriptDuration and CDP's own `Timestamp` metric at the same two instants.
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
        nostore = [q for q in reqs if (q.get('cacheControl') or '').find('no-store') >= 0]
        groups[(r['page'], r['profile'], r['pass'])].append({
            'warmNetworkRequests': len(net), 'warmNetworkBytes': sum(q['bytes'] or 0 for q in net),
            'noStoreRequests': len(nostore), 'noStoreBytes': sum(q['bytes'] or 0 for q in nostore),
            'thirdPartyRequests': len(third), 'thirdPartyBytes': sum(q['bytes'] or 0 for q in third),
            'thirdPartyHosts': sorted({urlparse(q['url']).hostname for q in third}),
            'requestsBeforeFcp': r.get('requestsBeforeFcp'), 'settledMs': r.get('settledMs'), 'domNodes': r.get('domNodes'),
        })
out = []
for (page, prof, pas), runs in sorted(groups.items()):
    row = {'page': page, 'profile': prof, 'pass': pas, 'runs': len(runs)}
    for k in runs[0]:
        row[k] = runs[0][k] if k == 'thirdPartyHosts' else med([x[k] for x in runs])
    out.append(row)
print(json.dumps(out, indent=1))
