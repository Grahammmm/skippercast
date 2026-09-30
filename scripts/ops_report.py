#!/usr/bin/env python3
"""Daily operations report from Workers Analytics Engine, as Markdown.

Queries the dataset the Worker writes (server/analytics.ts, dataset
`skippercast_events`) through Cloudflare's Analytics Engine SQL API for the last
24 hours: request counts by route and status class with p95 latency, LLM usage,
queue batches, cron runs, the client funnel and the top client errors
(web/telemetry.ts via /api/telemetry). Prints a Markdown report and appends it to
$GITHUB_STEP_SUMMARY when set.

Needs CF_ANALYTICS_TOKEN (an API token with Account · Account Analytics · Read)
and CLOUDFLARE_ACCOUNT_ID. Without them it prints why and exits 0, so the
scheduled workflow stays green until the owner opts in. A query the API
rejects exits 1.
"""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATASET = 'skippercast_events'
API = 'https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql'
WINDOW = "timestamp > NOW() - INTERVAL '1' DAY"

# Column positions are fixed per kind in server/analytics.ts. Request rows carry
# a weight in double3 (sampled /feeds/ reads), and Analytics Engine may sample
# rows itself (_sample_interval), so counts multiply both.
QUERIES = {
    'routes': f"""SELECT blob2 AS route,
  SUM(_sample_interval * double3) AS requests,
  sumIf(_sample_interval * double3, double1 < 300) AS s2xx,
  sumIf(_sample_interval * double3, double1 >= 300 AND double1 < 400) AS s3xx,
  sumIf(_sample_interval * double3, double1 >= 400 AND double1 < 500) AS s4xx,
  sumIf(_sample_interval * double3, double1 >= 500) AS s5xx,
  quantileExactWeighted(0.95)(double2, _sample_interval) AS p95_ms
FROM {DATASET} WHERE index1 = 'request' AND {WINDOW}
GROUP BY route ORDER BY requests DESC LIMIT 40""",
    'llm': f"""SELECT blob2 AS feature, blob4 AS model, blob3 AS outcome,
  SUM(_sample_interval) AS calls, SUM(_sample_interval * double1) AS input_tokens,
  SUM(_sample_interval * double2) AS output_tokens, SUM(_sample_interval * double3) AS web_searches
FROM {DATASET} WHERE index1 = 'llm' AND {WINDOW}
GROUP BY feature, model, outcome ORDER BY calls DESC LIMIT 20""",
    'queue': f"""SELECT blob2 AS queue, blob3 AS outcome, SUM(_sample_interval) AS batches,
  SUM(_sample_interval * double1) AS messages, SUM(_sample_interval * double5) AS trips_checked,
  SUM(_sample_interval * double7) AS delivered, SUM(_sample_interval * double8) AS held,
  quantileExactWeighted(0.95)(double10, _sample_interval) AS p95_ms
FROM {DATASET} WHERE index1 = 'queue_batch' AND {WINDOW}
GROUP BY queue, outcome ORDER BY batches DESC LIMIT 20""",
    'cron': f"""SELECT blob3 AS watchdog, blob4 AS trip_checks, blob5 AS prune, SUM(_sample_interval) AS runs,
  max(double1) AS max_ms
FROM {DATASET} WHERE index1 = 'cron' AND {WINDOW}
GROUP BY watchdog, trip_checks, prune ORDER BY runs DESC LIMIT 20""",
    'funnel': f"""SELECT blob2 AS event, SUM(_sample_interval) AS events
FROM {DATASET} WHERE index1 = 'client_event' AND {WINDOW}
GROUP BY event ORDER BY events DESC LIMIT 20""",
    'client_errors': f"""SELECT blob3 AS message, blob4 AS source, double1 AS line, blob2 AS kind, blob5 AS build,
  SUM(_sample_interval) AS reports
FROM {DATASET} WHERE index1 = 'client_error' AND {WINDOW}
GROUP BY message, source, line, kind, build ORDER BY reports DESC LIMIT 10""",
}

# Funnel steps in the order a visit takes them (server/telemetry.ts FUNNEL_EVENTS).
FUNNEL = ('port_selected', 'map_viewed', 'forecast_viewed', 'spot_saved', 'offline_saved', 'install')

# Text columns; every other column is a number (the API may return numbers as strings).
LABELS = frozenset({'route', 'feature', 'model', 'outcome', 'queue', 'watchdog', 'trip_checks', 'prune',
                    'event', 'message', 'source', 'line', 'kind', 'build'})

TITLES = {
    'routes': 'Requests by route (last 24 h)',
    'llm': 'LLM calls (last 24 h)',
    'queue': 'Trip-check queue batches (last 24 h)',
    'cron': 'Cron runs (last 24 h)',
    'funnel': 'Client funnel (last 24 h)',
    'client_errors': 'Top client errors (last 24 h)',
}

NOTES = {
    'funnel': ('Each step counts once per page load and region, not per person: there are no visitor ids. '
               'Browsers with Do Not Track or Global Privacy Control send nothing.'),
}


def query(sql, *, account, token, opener=urlopen):
    """Rows (list of dicts) for one SQL statement."""
    request = Request(API.format(account=account), data=sql.encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain',
                               'User-Agent': 'SkipperCast-ops-report/1'})
    with opener(request, timeout=30) as response:
        return json.load(response).get('data', [])


# Columns whose text a browser supplied (client error message and file name):
# printed as code spans so no link, image or HTML in them renders.
BROWSER_TEXT = frozenset({'message', 'source'})


def code_cell(value):
    text = str(value if value is not None else '').replace('`', '').replace('\n', ' ').replace('\r', ' ').strip()
    return f"`{text.replace('|', chr(92) + '|')}`" if text else '—'


def cell(value):
    if isinstance(value, float):
        return f'{value:,.0f}' if abs(value) >= 10 or value == int(value) else f'{value:.1f}'
    if isinstance(value, int):
        return f'{value:,}'
    # Keep any other text inert in the Markdown summary too.
    text = str(value if value is not None else '').replace('|', '\\|').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')
    return text or '—'


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def line_number(value):
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return value


def funnel_rows(rows):
    """Funnel steps in visit order, zero where nothing was recorded, then any unknown names."""
    counts = {str(r.get('event')): number(r.get('events')) for r in rows}
    ordered = [{'event': name, 'events': counts.pop(name, 0)} for name in FUNNEL]
    return ordered + [{'event': name, 'events': value} for name, value in counts.items()]


def table(rows):
    if not rows:
        return '_No data points in this window._\n'
    columns = list(rows[0])
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join('---' for _ in columns) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(code_cell(row.get(c)) if c in BROWSER_TEXT else cell(row.get(c) if c in LABELS else number(row.get(c)))
                                      for c in columns) + ' |')
    return '\n'.join(lines) + '\n'


def report(results):
    out = ['# SkipperCast operations report', '']
    routes = results.get('routes') or []
    total = sum(float(r.get('requests') or 0) for r in routes)
    errors = sum(float(r.get('s5xx') or 0) for r in routes)
    if routes:
        out += [f'Requests: {total:,.0f}; 5xx: {errors:,.0f} ({(errors / total * 100 if total else 0):.2f} %).', '']
    for key in QUERIES:
        rows = results.get(key) or []
        if key == 'funnel' and rows:
            rows = funnel_rows(rows)
        if key == 'client_errors':
            rows = [{**r, 'line': line_number(r.get('line'))} for r in rows]
        out += [f'## {TITLES[key]}', '']
        if key in NOTES:
            out += [NOTES[key], '']
        out.append(table(rows))
    return '\n'.join(out)


def main(argv=None, environ=None, opener=urlopen):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    token, account = environ.get('CF_ANALYTICS_TOKEN', '').strip(), environ.get('CLOUDFLARE_ACCOUNT_ID', '').strip()
    summary = environ.get('GITHUB_STEP_SUMMARY')
    if not token or not account:
        text = ('Operations report skipped: set the CF_ANALYTICS_TOKEN secret (Account Analytics: Read) '
                'and CLOUDFLARE_ACCOUNT_ID to enable it (docs/cloudflare.md#observability).\n')
        print(text, end='')
        if summary:
            with open(summary, 'a') as handle:
                handle.write(text)
        return 0
    results = {}
    for key, sql in QUERIES.items():
        try:
            results[key] = query(sql, account=account, token=token, opener=opener)
        except HTTPError as error:
            body = error.read().decode(errors='replace')[:500]
            # A dataset that has never been written does not exist yet.
            if error.code in (400, 404) and DATASET in body and ('not found' in body.lower() or 'does not exist' in body.lower() or 'unknown table' in body.lower()):
                print(f'::warning title=Ops report::dataset {DATASET} has no data yet (is ENABLE_ANALYTICS set?)')
                results[key] = []
                continue
            print(f'::error title=Ops report::Analytics Engine SQL API HTTP {error.code} for {key}: {body}')
            return 1
        except (URLError, TimeoutError, ValueError) as error:
            print(f'::error title=Ops report::Analytics Engine SQL API unavailable for {key}: {error}')
            return 1
    text = report(results)
    print(text)
    if summary:
        with open(summary, 'a') as handle:
            handle.write(text + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
