#!/usr/bin/env python3
"""Confirm the public site serves the feed generation this run just published.

    python scripts/verify_published_feed.py <public-feed-url> <run_id> [--published-at <iso>]

The Worker serves /feeds/* from R2 first, so a publish is only done when the
public copy carries this run's `run_id` (and, for the live job, which runs many
cycles inside one GitHub run, this cycle's `published_at`). Retries cover edge
caches and brief propagation; any other outcome exits non-zero.
"""
import argparse
import json
import sys
import time
from urllib.parse import urlsplit, urlunsplit, urlencode
from urllib.request import Request, urlopen


def fetch_json(url, timeout=30):
    request = Request(url, headers={'User-Agent': 'SkipperCast-publish-verify/1.0', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def bust(url, token):
    """The same URL with a cache-busting query, so no cache answers for the origin."""
    parts = urlsplit(url)
    query = (parts.query + '&' if parts.query else '') + urlencode({'verify': token})
    return urlunsplit(parts._replace(query=query))


def check(feed, run_id, published_at=None):
    """Return (ok, message) for one fetched feed."""
    if not isinstance(feed, dict):
        return False, 'public feed is not a JSON object'
    seen = feed.get('run_id')
    if seen != run_id:
        return False, f'public feed run_id is {seen!r}, expected {run_id!r}'
    if published_at is not None and feed.get('published_at') != published_at:
        return False, f"public feed published_at is {feed.get('published_at')!r}, expected {published_at!r}"
    return True, f"public feed serves run {run_id} (published {feed.get('published_at')})"


def verify(url, run_id, published_at=None, *, attempts=8, delay=15.0, fetch=None, sleep=time.sleep):
    """Poll the public URL until it serves this run; return (ok, message)."""
    fetch = fetch or fetch_json
    message = 'not checked'
    for attempt in range(1, attempts + 1):
        try:
            feed = fetch(bust(url, f'{run_id}-{attempt}-{int(time.time())}'))
        except Exception as error:  # network, HTTP or JSON failure: retry, then fail
            message = f'could not fetch public feed: {type(error).__name__}: {str(error)[:200]}'
        else:
            ok, message = check(feed, run_id, published_at)
            if ok:
                return True, f'{message} after {attempt} attempt(s)'
        if attempt < attempts:
            sleep(delay)
    return False, f'{url}: {message} after {attempts} attempt(s)'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('url', help='public feed URL, e.g. https://skippercast.example/feeds/conditions/latest.json')
    parser.add_argument('run_id')
    parser.add_argument('--published-at', help='also require this published_at (one cycle of a multi-cycle run)')
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--delay', type=float, default=15.0, help='seconds between attempts')
    args = parser.parse_args(argv)
    ok, message = verify(args.url, args.run_id, args.published_at or None, attempts=args.attempts, delay=args.delay)
    if ok:
        print(f'Verified: {message}')
        return 0
    print(f'::error title=Public feed not updated::{message}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
