#!/usr/bin/env python3
"""Controller steps for the manual Morro stage preview (.github/workflows/stage-preview.yml).

Runs from the workflow's own reviewed revision, never from the candidate checkout, and
never touches production: no production Worker, bucket, route, schedule or secret.

  scope         the candidate differs from the reviewed controller commit only in
                Morro's data files (DATA_PATHS), so the code built is exactly reviewed code
  place-config  put the planned stage Wrangler config into the built candidate tree,
                after re-checking its digest, its isolation and the preview origin
  copy          copy the candidate pointer's release objects into the separate stage
                bucket (create-only, full read-back), never production
  assets        (box, offline) write the pointer's exact release objects, named as
                GitHub release assets, from a local release directory, for upload to
                the preview-only DRAFT release relief-preview-<region>-<envelope>
  fetch         (workflow fetch job) download that draft release's assets into a
                directory; the copy step then reads them with LocalRelease and
                stage_transport.copy_release re-checks every name, size and digest

Why a draft preview release: the production copy reads only a PUBLISHED release
relief-<region>-<envelope>, which the box stages only after the exact R8 approval
(stage_transport.stage). The preview exists so R8 can judge served bytes, so it
cannot depend on that approval. A draft is not public, never creates a tag and is
invisible to the production reader (it refuses drafts and the preview tag name).

The candidate's data is inert here: nothing in this file writes the repository,
the production bucket or the production Worker. A hosted run needs G's explicit
preview approval and the stage-only credentials; see the workflow header.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CONTROLLER = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(CONTROLLER / 'src'), str(CONTROLLER)]

from scripts.relief import morro_stage_preview as preview  # noqa: E402

PLAN_SCHEMA = 'sc-morro-stage-preview/1'


def data_paths(region: str) -> frozenset:
    """The data a candidate for `region` may change: the relief pointer, the contour import and the
    two published contour files the browser loads (scripts/build_depth_contours.py output).

    A Central region gets its first contours here, so the platform build also rewrites that region's
    dist/regions/<id>/region.json (its `chart_files` list) and the source register rewrites
    dist/sources.html; both are generated data, so the STAGE candidate can be the data PR head itself.
    Morro's set is unchanged."""
    preview.check_region(region)
    paths = {preview.pointer_path(region), preview.contours_path(region),
             f'dist/regions/{region}/depth-contours.geojson',
             f'dist/regions/{region}/depth-contours-overview.geojson'}
    if region in preview.CENTRAL_REGIONS:
        paths |= {f'dist/regions/{region}/region.json', 'dist/sources.html'}
    return frozenset(paths)


DATA_PATHS = data_paths(preview.REGION)
CONFIG_NAME = 'wrangler.stage.json'
_SHA = re.compile(r'[0-9a-f]{40}')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_SUBDOMAIN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


class HoldError(ValueError):
    """The preview is held; the message is safe to log (no URL bodies, tokens or paths)."""


def _git(tree: Path, *args: str) -> bytes:
    try:
        return subprocess.run(['git', '-C', str(tree), *args], check=True, capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        raise HoldError('git could not read the candidate checkout') from None


def scope(tree: Path, base: str, sha: str, region: str = preview.REGION) -> list[str]:
    """Paths the candidate changes against the reviewed base; only the region's data files may differ."""
    allowed = data_paths(region)
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(sha):
        raise HoldError('base and candidate must be full lowercase commit SHAs')
    raw = _git(tree, 'diff', '--name-only', '-z', '--no-renames', '--no-ext-diff', base, sha, '--')
    changed = sorted(path.decode(errors='replace') for path in raw.split(b'\0') if path)
    outside = [path for path in changed if path not in allowed]
    if outside:
        what = 'the Morro data' if region == preview.REGION else f'the {region} data'
        raise HoldError(f'candidate changes files outside {what}: ' + ', '.join(outside[:5]))
    for path in changed:
        listing = _git(tree, 'ls-tree', '-z', sha, '--', path)
        if listing and not listing.startswith(b'100644 blob '):
            raise HoldError(f'candidate {path} is not a regular file')
    return changed


def check_origin(origin: str, worker: str) -> str:
    """The preview Worker's own workers.dev origin; anything else (a custom domain, production) is held."""
    match = re.fullmatch(r'https://([a-z0-9-]+)\.([a-z0-9-]+)\.workers\.dev', origin or '')
    if not match or match.group(1) != worker or not _SUBDOMAIN.fullmatch(match.group(2)):
        raise HoldError('preview origin must be https://<stage worker>.<account>.workers.dev')
    return origin


def load_plan(plan_dir: Path) -> tuple[dict, bytes]:
    """(plan receipt, stage config bytes) as written by morro_stage_preview.py plan; digest re-checked."""
    try:
        receipt = json.loads((plan_dir / 'plan.json').read_bytes())
        config = (plan_dir / CONFIG_NAME).read_bytes()
    except (OSError, ValueError):
        raise HoldError('stage plan is missing or not JSON') from None
    if (not isinstance(receipt, dict) or receipt.get('schema') != PLAN_SCHEMA or receipt.get('region') not in preview.REGIONS
            or not isinstance(receipt.get('commit'), str) or not _SHA.fullmatch(receipt['commit'])
            or not isinstance(receipt.get('pointer_sha256'), str) or not _SHA256.fullmatch(receipt['pointer_sha256'])):
        raise HoldError('stage plan is not a Morro stage preview plan')
    if preview.STAGE_TARGETS[receipt['region']] != (receipt.get('worker'), receipt.get('bucket')):
        raise HoldError('stage plan does not name its region\'s own stage Worker and bucket')
    if hashlib.sha256(config).hexdigest() != receipt.get('config_sha256'):
        raise HoldError('stage config differs from the plan')
    try:
        doc = json.loads(config)
        preview.refuse_production(doc)
    except (ValueError, preview.PreviewError) as error:
        raise HoldError(f'stage config is not isolated: {error}') from None
    if doc.get('name') != receipt.get('worker') or doc['r2_buckets'] != [{'binding': 'FEEDS', 'bucket_name': receipt.get('bucket')}]:
        raise HoldError('stage config does not name the planned Worker and bucket')
    return receipt, config


def place_config(plan_dir: Path, tree: Path, origin: str) -> Path:
    """Write the checked stage config into the candidate tree for Wrangler; refuse to overwrite anything."""
    receipt, config = load_plan(plan_dir)
    check_origin(origin, receipt['worker'])
    head = _git(tree, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    if head != receipt['commit']:
        raise HoldError('candidate checkout is not the planned commit')
    dest = tree / CONFIG_NAME
    try:
        with dest.open('xb') as out:
            out.write(config)
    except FileExistsError:
        raise HoldError(f'{CONFIG_NAME} already exists in the candidate tree') from None
    return dest


class StageR2:
    """Create-only R2 access bound to one *-stage bucket; the production feeds bucket is unreachable.

    Same contract as stage_transport.R2 (full GET, PutObject If-None-Match: *, never HEAD), with
    the bucket fixed at construction instead of the production constant.
    """

    def __init__(self, client, bucket: str):
        if bucket in preview.PRODUCTION_BUCKETS or not bucket.endswith('-stage') or not preview._NAME.fullmatch(bucket):
            raise HoldError('stage copy may only write a *-stage bucket')
        self.client = client
        self.bucket = bucket

    @classmethod
    def connect(cls, token: str, account: str, *, bucket: str):
        from skippercast.relief import stage_transport as stage

        # Reuse the reviewed token check and client settings, then bind the stage bucket.
        return cls(stage.R2.connect(token, account).client, bucket)

    @contextmanager
    def get(self, key):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'NoSuchKey'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404):
                raise
            yield None
            return
        with closing(response['Body']) as stream:
            if response['ResponseMetadata']['HTTPStatusCode'] != 200 or response.get('ContentRange') is not None:
                raise HoldError('stage R2 did not return a full GET')
            yield stream

    def create(self, key, body, size):
        from botocore.exceptions import ClientError

        brotli = key.endswith('.geojson.br')
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentLength=size, IfNoneMatch='*',
                                   **({'ContentEncoding': 'br'} if brotli else {}),
                                   ContentType='application/geo+json' if brotli else
                                   'application/json' if key.endswith('.json') else 'application/octet-stream',
                                   CacheControl='public, max-age=31536000, immutable')
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'PreconditionFailed'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 412):
                raise
            # A racing writer won; copy_release still reads the object back in full.


def candidate_pointer(tree: Path, receipt: dict) -> dict:
    """The planned commit's region pointer, checked against the plan digest and the controller's policy."""
    from skippercast.relief import package

    region = receipt['region']
    data = _git(tree, 'cat-file', 'blob', f"{receipt['commit']}:{preview.pointer_path(region)}")
    if hashlib.sha256(data).hexdigest() != receipt['pointer_sha256']:
        raise HoldError('candidate pointer differs from the planned pointer')
    pointer = package.decode_document(data)
    if pointer.get('region') != region:
        raise HoldError(f'candidate pointer is not for {preview.label(region)}')
    # The controller's reviewed schema and source policy, never the candidate's copies.
    schema = package.pointer_schema()
    registry = package.decode_document((CONTROLLER / 'catalog/sources.json').read_bytes())
    package.validate_schema(pointer, schema)
    package.validate_metadata(pointer, schema, registry)
    return pointer


PREVIEW_PREFIX = 'relief-preview-'
ASSET_MANIFEST = 'preview-assets.json'
ASSET_SCHEMA = 'sc-morro-preview-assets/1'
_ASSET_NAME = re.compile(r'[0-9a-f]{64}\.(?:pmtiles|json|geojson\.br)')
_MAX_PAGES = 10
_LISTING_LIMIT = 8 << 20  # the same bound as stage_transport's metadata reader


def decode_listing(data: bytes) -> list:
    """Decode one page of the GitHub release listing: a JSON ARRAY, bounded, canonical JSON only."""
    from skippercast.relief import package

    if len(data) > _LISTING_LIMIT:
        raise HoldError('GitHub release listing exceeds the byte limit')

    def unique(pairs):
        doc = {}
        for key, value in pairs:
            if key in doc:
                raise HoldError(f'duplicate JSON member {key!r} in the GitHub release listing')
            doc[key] = value
        return doc

    def no_constant(name):
        raise HoldError(f'invalid JSON constant {name} in the GitHub release listing')

    try:
        rows = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HoldError('invalid GitHub release listing') from None
    if not isinstance(rows, list):
        raise HoldError('invalid GitHub release listing')
    package.receipts.canonical(rows)  # reject malformed Unicode, as decode_document does
    return rows


def preview_tag(pointer: dict, region: str = preview.REGION) -> str:
    """The draft release name for this pointer; never the production relief-<region>-<envelope> tag."""
    found, envelope = pointer.get('region'), pointer.get('envelope_sha256')
    if (region not in preview.REGIONS or found != region
            or not isinstance(envelope, str) or not _SHA256.fullmatch(envelope)):
        raise HoldError(f'pointer is not a {preview.label(region)} pointer with an envelope digest')
    return f'{PREVIEW_PREFIX}{region}-{envelope}'


def _pointer_file(path: Path, pointer_sha256: str, region: str = preview.REGION) -> dict:
    from skippercast.relief import package

    if not _SHA256.fullmatch(pointer_sha256 or ''):
        raise HoldError('pointer digest must be 64 lowercase hex digits')
    if path.is_symlink() or not path.is_file():
        raise HoldError('pointer is not a regular file')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != pointer_sha256:
        raise HoldError('pointer differs from the pinned pointer digest')
    pointer = package.decode_document(data)
    package.validate_schema(pointer, package.pointer_schema())
    preview_tag(pointer, region)
    return pointer


def _write_manifest(out: Path, tag: str, sizes: dict) -> None:
    doc = {'schema': ASSET_SCHEMA, 'tag': tag, 'assets': dict(sorted(sizes.items()))}
    (out / ASSET_MANIFEST).write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')


def _new_dir(out: Path) -> None:
    if out.exists() or out.is_symlink():
        raise HoldError('choose a new assets directory')
    out.mkdir(parents=True)


def prepare_assets(pointer_path: Path, pointer_sha256: str, region_dir: Path, out: Path,
                   region: str = preview.REGION) -> dict:
    """Box only, offline: write exactly the pointer's release objects from a local release directory.

    Every object is located by its SHA-256 among regular files under ``region_dir``, copied under its
    GitHub asset name and checked for size and digest; the survey wires are decoded against their pins
    and the companion against the detail. Grants nothing: the stage copy re-checks everything.
    """
    from skippercast.relief import stage_transport as stage

    pointer = _pointer_file(pointer_path, pointer_sha256, region)
    tag = preview_tag(pointer, region)
    if region_dir.is_symlink() or not region_dir.is_dir():
        raise HoldError('release directory is not a directory')
    by_sha: dict[str, Path] = {}
    for path in sorted(region_dir.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        h = hashlib.sha256()
        with path.open('rb') as stream:
            while block := stream.read(1 << 20):
                h.update(block)
        by_sha.setdefault(h.hexdigest(), path)
    _new_dir(out)
    sizes: dict[str, int] = {}

    def put(obj):
        source = by_sha.get(obj.sha)
        if source is None:
            raise HoldError(f'release directory lacks object {obj.name}')
        size = source.stat().st_size
        dest = out / obj.name
        if obj.name not in sizes:
            with source.open('rb') as stream, dest.open('xb') as target:
                stage._checked(stream, obj, size, phase='preview asset', output=target)
            sizes[obj.name] = size
        return dest

    archive, root = stage._objects(pointer)
    put(archive)
    root_file = put(root)
    chunks = tuple(stage._chunks(pointer, root, root_file))
    for obj in chunks:
        put(obj)
    survey = {obj.sha: put(obj) for obj in stage._survey(pointer)}
    stage._check_survey(pointer, survey)
    _write_manifest(out, tag, sizes)
    return {'tag': tag, 'assets': len(sizes), 'bytes': sum(sizes.values())}


class LocalRelease:
    """The GitHub-release interface of stage_transport.copy_release over a fetched preview-assets directory.

    copy_release asks for the production tag relief-<region>-<envelope>; this answers only when the
    directory was fetched from the matching relief-preview-<region>-<envelope> draft, and lists exactly
    the files on disk. copy_release still requires that list to equal the pointer's digest chain and
    checks every size and SHA-256 before any stage write.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self._names: dict[int, str] = {}

    def assets(self, tag):
        from skippercast.relief import stage_transport as stage

        if not isinstance(tag, str) or not tag.startswith('relief-') or tag.startswith(PREVIEW_PREFIX):
            raise HoldError('unexpected release tag')
        try:
            doc = json.loads((self.directory / ASSET_MANIFEST).read_bytes())
        except (OSError, ValueError):
            raise HoldError('preview assets manifest is missing or not JSON') from None
        if (not isinstance(doc, dict) or doc.get('schema') != ASSET_SCHEMA
                or doc.get('tag') != PREVIEW_PREFIX + tag.removeprefix('relief-')
                or not isinstance(doc.get('assets'), dict)):
            raise HoldError('preview assets were not fetched for this pointer')
        on_disk = {}
        for path in self.directory.iterdir():
            if path.name == ASSET_MANIFEST:
                continue
            if path.is_symlink() or not path.is_file() or not _ASSET_NAME.fullmatch(path.name):
                raise HoldError('preview assets directory holds an unexpected entry')
            on_disk[path.name] = path.stat().st_size
        if on_disk != doc['assets'] or not 1 <= len(on_disk) <= stage.MAX_ASSETS:
            raise HoldError('preview assets differ from their manifest')
        result = {}
        for number, (name, size) in enumerate(sorted(on_disk.items()), start=1):
            self._names[number] = name
            result[name] = stage.Asset(number, size)
        return result

    def download(self, asset):
        name = self._names.get(asset.id)
        if name is None:
            raise HoldError('unknown preview asset')
        return (self.directory / name).open('rb')


class DraftRelease:
    """Fetch-job reader for the one same-repo DRAFT release named relief-preview-<region>-<envelope>.

    Drafts are listed only to a token with push access, which is why only the separate fetch job,
    which runs no candidate code, gets contents: write. Asset downloads reuse the reviewed
    stage_transport.GitHubRelease hop rules (one trusted media redirect, token never forwarded).
    """

    def __init__(self, token: str, opener=None):
        from skippercast.relief import stage_transport as stage

        self._reader = stage.GitHubRelease(token)
        self._open = opener

    def release(self, tag: str) -> dict:
        from skippercast.relief import stage_transport as stage

        if not tag.startswith(PREVIEW_PREFIX):
            raise HoldError('only a preview release can be fetched')
        found = []
        for page in range(1, _MAX_PAGES + 1):
            rows = self._list(page)
            if not isinstance(rows, list):
                raise HoldError('invalid GitHub release listing')
            found += [row for row in rows if isinstance(row, dict) and row.get('tag_name') == tag]
            if len(rows) < 100:
                break
        if len(found) != 1:
            raise HoldError('expected exactly one preview release for this pointer')
        release = found[0]
        rid = release.get('id')
        if (type(rid) is not int or rid <= 0 or release.get('draft') is not True or release.get('prerelease') is not False
                or release.get('url') != f'{stage._REPO_API}/releases/{rid}'
                or release.get('assets_url') != f'{stage._REPO_API}/releases/{rid}/assets'):
            raise HoldError('preview release is not a same-repo draft')
        return release

    def _list(self, page):
        from skippercast.relief import stage_transport as stage

        if self._open is not None:
            return self._open(page)
        # The listing is a JSON array; stage_transport's metadata reader accepts only an object (it
        # held every real dispatch with 'expected a JSON object', run 45727170009). Same bounded read,
        # same canonical-JSON rules, array allowed.
        request = self._reader._request(f'{stage._API}/repos/{stage.REPOSITORY}/releases?per_page=100&page={page}',
                                        'application/vnd.github+json')
        with stage._open(request) as stream:
            data = stream.read(_LISTING_LIMIT + 1)
        return decode_listing(data)

    def assets(self, tag):
        from skippercast.relief import stage_transport as stage

        rows = self.release(tag).get('assets')
        if not isinstance(rows, list) or not 1 <= len(rows) <= stage.MAX_ASSETS:
            raise HoldError('invalid preview release asset inventory')
        assets = {}
        for row in rows:
            aid, name, size = (row.get(k) if isinstance(row, dict) else None for k in ('id', 'name', 'size'))
            if (type(aid) is not int or aid <= 0 or not isinstance(name, str) or not _ASSET_NAME.fullmatch(name)
                    or type(size) is not int or not 0 < size <= stage.ARCHIVE_LIMIT or name in assets
                    or row.get('state') != 'uploaded' or row.get('url') != f'{stage._REPO_API}/releases/assets/{aid}'):
                raise HoldError('invalid preview release asset')
            assets[name] = stage.Asset(aid, size)
        return assets

    def download(self, asset):
        return self._reader.download(asset)


def fetch(pointer_path: Path, pointer_sha256: str, out: Path, *, release=None, env=None,
          region: str = preview.REGION) -> dict:
    """Fetch job: download the pinned pointer's draft preview assets (bounded) into a new directory."""
    from skippercast.relief import stage_transport as stage

    pointer = _pointer_file(pointer_path, pointer_sha256, region)
    tag = preview_tag(pointer, region)
    if release is None:
        release = DraftRelease((env or os.environ).get('PREVIEW_RELEASE_READ_TOKEN', ''))
    assets = release.assets(tag)
    _new_dir(out)
    sizes = {}
    for name, asset in sorted(assets.items()):
        count = 0
        with closing(release.download(asset)) as stream, (out / name).open('xb') as target:
            while block := stream.read(min(stage.BLOCK, asset.size - count + 1)):
                count += len(block)
                if count > asset.size:
                    raise HoldError('preview asset exceeds its listed size')
                target.write(block)
        if count != asset.size:
            raise HoldError('preview asset is shorter than its listed size')
        sizes[name] = count
    _write_manifest(out, tag, sizes)
    return {'tag': tag, 'assets': len(sizes), 'bytes': sum(sizes.values())}


def copy(plan_dir: Path, tree: Path, env, *, github=None, r2=None, assets_dir: Path | None = None) -> int:
    """Copy the pointer's release objects into the planned stage bucket; returns the object count."""
    from skippercast.relief import stage_transport as stage

    receipt, _ = load_plan(plan_dir)
    pointer = candidate_pointer(tree, receipt)
    if 'survey_detail' in pointer:
        from skippercast.relief import survey_delivery
        try:
            survey_delivery.decoder()
        except ValueError as error:
            raise HoldError(str(error)) from None
    if assets_dir is not None:
        github = LocalRelease(assets_dir)
    if github is None:
        raise HoldError('stage copy needs the fetched preview assets directory')
    if r2 is None:
        r2 = StageR2.connect(env.get('STAGE_R2_PUBLISH_TOKEN', ''), env.get('STAGE_CLOUDFLARE_ACCOUNT_ID', ''),
                             bucket=receipt['bucket'])
    if getattr(r2, 'bucket', None) != receipt['bucket']:
        raise HoldError('stage copy is not bound to the planned bucket')
    return stage.copy_release(pointer, github, r2, allow_create=True, recheck=None)


# The Chart draws land, water and coast labels from the statewide basemap named by
# feeds/tiles/basemap/manifest.json. The stage bucket starts empty, so the preview copies the
# exact public production bytes (read over HTTPS from the public site, never with production
# credentials) into the stage bucket: archive first, then the manifest that names it, each
# create-only with a full read-back. A different existing stage copy holds.
PUBLIC_SITE = 'https://skippercast.g4651.workers.dev'
BASEMAP_MANIFEST_KEY = 'tiles/basemap/manifest.json'
_BASEMAP_KEY = re.compile(r'tiles/basemap/ca-coast-[0-9]{8}\.pmtiles')
BASEMAP_LIMIT = 1 << 30
_MANIFEST_LIMIT = 1 << 16


def _public_get(url: str):
    from urllib.request import Request
    from skippercast.relief import stage_transport as stage

    response = stage._open(Request(url, headers={'User-Agent': 'SkipperCast-morro-stage-preview'}))
    if response.status != 200 or response.headers.get('Content-Range') is not None:
        response.close()
        raise HoldError('public basemap did not return a full GET')
    return response


def basemap_manifest(get=_public_get) -> tuple[bytes, dict]:
    with closing(get(f'{PUBLIC_SITE}/feeds/{BASEMAP_MANIFEST_KEY}')) as stream:
        data = stream.read(_MANIFEST_LIMIT + 1)
    if len(data) > _MANIFEST_LIMIT:
        raise HoldError('basemap manifest exceeds its byte limit')
    try:
        doc = json.loads(data)
    except ValueError:
        raise HoldError('basemap manifest is not JSON') from None
    if (not isinstance(doc, dict) or doc.get('schema_version') != 1 or not isinstance(doc.get('key'), str)
            or not _BASEMAP_KEY.fullmatch(doc['key']) or type(doc.get('bytes')) is not int
            or not 0 < doc['bytes'] <= BASEMAP_LIMIT or not isinstance(doc.get('sha256'), str)
            or not _SHA256.fullmatch(doc['sha256'])):
        raise HoldError('basemap manifest does not name one pinned basemap archive')
    return data, doc


def copy_basemap(r2, *, get=_public_get) -> dict:
    """Copy the public basemap archive and its manifest into the stage bucket (create-only, read back)."""
    from skippercast.relief import stage_transport as stage

    manifest, doc = basemap_manifest(get)
    archive = stage.Object(doc['key'], doc['sha256'], BASEMAP_LIMIT, doc['bytes'])
    listed = stage.Object(BASEMAP_MANIFEST_KEY, hashlib.sha256(manifest).hexdigest(), _MANIFEST_LIMIT, len(manifest))
    with tempfile.TemporaryDirectory(prefix='stage-basemap-') as temp:
        path = Path(temp) / 'archive.pmtiles'
        with r2.get(archive.key) as stream:
            present = stream is not None
            if present:
                stage._checked(stream, archive, archive.size, phase='stage basemap read-back')
        if not present:
            with closing(get(f'{PUBLIC_SITE}/feeds/{archive.key}')) as stream, path.open('xb') as out:
                stage._checked(stream, archive, archive.size, phase='public basemap', output=out)
            with path.open('rb') as body:
                r2.create(archive.key, body, archive.size)
            with r2.get(archive.key) as stream:
                if stream is None:
                    raise HoldError('stage basemap read-back missing')
                stage._checked(stream, archive, archive.size, phase='stage basemap read-back')
        with r2.get(listed.key) as stream:
            if stream is not None:
                stage._checked(stream, listed, listed.size, phase='stage basemap manifest (a different copy holds)')
                return {'archive': archive.key, 'sha256': archive.sha, 'created': not present}
        r2.create(listed.key, io.BytesIO(manifest), listed.size)
        with r2.get(listed.key) as stream:
            if stream is None:
                raise HoldError('stage basemap manifest read-back missing')
            stage._checked(stream, listed, listed.size, phase='stage basemap manifest read-back')
    return {'archive': archive.key, 'sha256': archive.sha, 'created': not present}


def basemap(plan_dir: Path, env, *, r2=None, get=_public_get) -> dict:
    receipt, _ = load_plan(plan_dir)
    if r2 is None:
        r2 = StageR2.connect(env.get('STAGE_R2_PUBLISH_TOKEN', ''), env.get('STAGE_CLOUDFLARE_ACCOUNT_ID', ''),
                             bucket=receipt['bucket'])
    if getattr(r2, 'bucket', None) != receipt['bucket']:
        raise HoldError('stage basemap copy is not bound to the planned bucket')
    return copy_basemap(r2, get=get)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Controller steps for the manual Morro stage preview.')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scope', help='require the candidate to differ from the reviewed base only in Morro data')
    s.add_argument('--tree', type=Path, required=True)
    s.add_argument('--base', required=True, help='the reviewed controller commit (github.workflow_sha)')
    s.add_argument('--sha', required=True, help='the candidate commit')
    s.add_argument('--region', default=preview.REGION, choices=preview.REGIONS)
    for name, text in (('place-config', 'write the checked stage config into the candidate tree'),
                       ('copy', 'copy the release objects into the stage bucket')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--plan-dir', type=Path, required=True)
        p.add_argument('--tree', type=Path, required=True)
        if name == 'place-config':
            p.add_argument('--origin', required=True, help='the preview Worker workers.dev origin')
        else:
            p.add_argument('--assets-dir', type=Path, required=True, help='the fetched preview assets directory')
    b = sub.add_parser('basemap', help='copy the public basemap archive and manifest into the stage bucket')
    b.add_argument('--plan-dir', type=Path, required=True)
    for name, text in (('assets', 'box only: write the pointer release objects for the draft preview release'),
                       ('fetch', 'fetch job: download the draft preview release assets')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--pointer', type=Path, required=True, help='the candidate catalog/relief/<region>.json')
        p.add_argument('--pointer-sha256', required=True)
        p.add_argument('--out', type=Path, required=True, help='a new directory')
        p.add_argument('--region', default=preview.REGION, choices=preview.REGIONS)
        if name == 'assets':
            p.add_argument('--release-dir', type=Path, required=True, help='the local region release directory')
    args = parser.parse_args(argv)
    try:
        if args.command == 'scope':
            changed = scope(args.tree, args.base, args.sha, args.region)
            print('SCOPE data-only: ' + (', '.join(changed) or 'no change from the reviewed base'))
        elif args.command == 'place-config':
            print(f'CONFIG {place_config(args.plan_dir, args.tree, args.origin).name}')
        elif args.command == 'assets':
            print(json.dumps(prepare_assets(args.pointer, args.pointer_sha256, args.release_dir, args.out,
                                            args.region), sort_keys=True))
        elif args.command == 'fetch':
            print(json.dumps(fetch(args.pointer, args.pointer_sha256, args.out, region=args.region), sort_keys=True))
        elif args.command == 'basemap':
            print('BASEMAP ' + json.dumps(basemap(args.plan_dir, os.environ), sort_keys=True))
        else:
            count = copy(args.plan_dir, args.tree, os.environ, assets_dir=args.assets_dir)
            print(f'COPIED {count} objects to the stage bucket')
        return 0
    except (HoldError, preview.PreviewError) as error:
        print(f'::error::Morro stage preview held: {error}', file=sys.stderr)
        return 2
    except Exception as error:
        if type(error).__name__ in ('StageError', 'ReleaseError'):
            # stage_transport/package diagnostics are written to be safe to log (no URL, response or path).
            print(f'::error::Morro stage preview held: {error}', file=sys.stderr)
            return 2
        # SDK and transport errors may carry headers or signed URLs; never log their bodies.
        print(f'::error::Morro stage preview held ({type(error).__name__}); nothing promoted.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
