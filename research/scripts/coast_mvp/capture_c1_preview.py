"""Capture self-contained local C1 preview pages using an installed Chromium.

No HTTP server or download. A separate invocation/profile for each static page.
"""
from __future__ import annotations
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import subprocess
import tempfile


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.scripts = 0
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.scripts += 1
        if tag == 'img':
            self.images.append(dict(attrs).get('src'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(root: Path, browser: Path, no_sandbox: bool = False) -> dict:
    root = root.resolve()
    evidence = json.loads((root / 'receipt.json').read_text())
    result = {'status': 'review_required', 'mode': evidence['mode'],
              'manifest_sha256': evidence['manifest_sha256'], 'screenshots': [],
              'network': 'file URLs only; no server; no scripts; remote DNS blocked',
              'sandbox_disabled': no_sandbox}
    for view in evidence['views']:
        name = view['id']
        if name not in ('overview', 'morro-estero', 'buchon-close'):
            raise ValueError('unexpected view id')
        page = root / f'{name}.html'
        content = page.read_text()
        parsed = Page()
        parsed.feed(content)
        if parsed.scripts or parsed.images != [f'{name}-hillshade.png']:
            raise ValueError('only the generated static image page may be captured')
        for required in ('NOT FOR NAVIGATION', 'review_required', 'rights.html', 'Vertical datums are unresolved', 'no C2 contours'):
            if required not in content:
                raise ValueError(f'page missing {required}')
        image = root / parsed.images[0]
        if digest(image) != view['png_sha256']:
            raise ValueError('hillshade image hash mismatch')
        target = root / f'{name}-screenshot.png'
        if target.exists():
            raise ValueError('refusing to overwrite screenshot')
        with tempfile.TemporaryDirectory(prefix='chrome-preview-') as profile:
            command = [str(browser), '--headless', '--disable-gpu', '--disable-background-networking',
                       '--disable-extensions', '--no-first-run', '--no-default-browser-check',
                       '--host-resolver-rules=MAP * ~NOTFOUND', '--window-size=1440,1100',
                       f'--user-data-dir={profile}', '--virtual-time-budget=1500',
                       f'--screenshot={target}', page.as_uri()]
            if no_sandbox:
                command.insert(1, '--no-sandbox')
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            (root / f'{name}-browser.log').write_text(completed.stdout + completed.stderr)
            completed.check_returncode()
        raw = target.read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or struct.unpack('!II', raw[16:24]) != (1440, 1100):
            raise ValueError('unexpected screenshot dimensions or format')
        result['screenshots'].append({'view': name, 'file': target.name, 'sha256': digest(target),
                                      'html_sha256': digest(page), 'size': [1440, 1100],
                                      'browser_returncode': completed.returncode})
    (root / 'browser-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', required=True, type=Path)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--no-sandbox', action='store_true', help='Explicit local test-only opt-in; recorded in receipt')
    args = parser.parse_args()
    print(json.dumps(capture(args.preview, args.browser, args.no_sandbox), indent=2))


if __name__ == '__main__':
    main()
