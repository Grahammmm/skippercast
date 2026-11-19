"""Prepare reviewed public release assets and copy a protected pointer's exact bytes.

The box uses DL-10 and an authenticated R8 queue lookup. CI has no private
chain files: its authority is the reviewed pointer in the selected main tree,
not the GitHub release, an upload receipt, or any user-supplied inventory.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from skippercast.relief import package

REPOSITORY = 'Grahammmm/skippercast'
BUCKET = 'skippercast-feeds'
MAX_ASSETS = 1000  # GitHub's per-release limit
ARCHIVE_LIMIT = (2 << 30) - 1  # GitHub requires each asset to be smaller than 2 GiB
ROOT_LIMIT = 1 << 20
CHUNK_LIMIT = 1 << 20
BLOCK = 1 << 20
REGION = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
_CHUNK = re.compile(r'([89]|1[0-7])/(0|[1-9][0-9]{0,3})_(0|[1-9][0-9]{0,3})\.json')
_ASSET = re.compile(r'[0-9a-f]{64}\.(?:pmtiles|json)')
_API = 'https://api.github.com'
_REPO_API = f'{_API}/repos/{REPOSITORY}'


class StageError(ValueError):
    """Safe diagnostic: never include a provider URL, response, or local path."""


@dataclass(frozen=True)
class Object:
    key: str
    sha: str
    limit: int
    size: int | None = None

    @property
    def name(self):
        return self.sha + ('.pmtiles' if self.key.endswith('.pmtiles') else '.json')


def release_tag(pointer):
    return f"relief-{pointer['region']}-{pointer['envelope_sha256']}"


def _objects(pointer):
    stem = f"tiles/relief/{pointer['region']}/{pointer['sha256']}"
    sha = pointer['digest_root_sha256']
    return (Object(f'{stem}.pmtiles', pointer['sha256'], ARCHIVE_LIMIT, pointer['bytes']),
            Object(f'{stem}.digests/{sha}/root.json', sha, ROOT_LIMIT))


def _chunks(pointer, root_obj, path):
    try:
        doc = package.decode_document(path.read_bytes())
    except ValueError:
        raise StageError('invalid digest root JSON') from None
    chunks = doc.get('chunks')
    if doc.keys() != {'chunks'} or not isinstance(chunks, dict) or not 1 <= len(chunks) <= MAX_ASSETS - 2:
        raise StageError('invalid digest root inventory')
    for name, sha in sorted(chunks.items()):
        match = _CHUNK.fullmatch(name)
        if not match or not package.is_sha256(sha):
            raise StageError('invalid digest root reference')
        z, x, y = map(int, match.groups())
        if not pointer['minzoom'] <= z <= pointer['maxzoom'] or max(x, y) >= 1 << (z - 6):
            raise StageError('digest root reference outside the pointer zoom or tile grid')
        yield Object(root_obj.key.removesuffix('root.json') + name, sha, CHUNK_LIMIT)


def _checked(stream, obj, size, *, phase, output=None):
    """On success reach EOF and match both digest and size; cap disk and reads on failure."""
    if type(size) is not int or not 0 < size <= obj.limit or obj.size not in (None, size):
        raise StageError(f'{phase}: invalid object size')
    count, digest = 0, hashlib.sha256()
    while block := stream.read(min(BLOCK, size - count + 1)):
        count += len(block)
        if count > size:
            raise StageError(f'{phase}: object exceeds expected size')
        digest.update(block)
        if output is not None:
            output.write(block)
    if count != size or digest.hexdigest() != obj.sha:
        raise StageError(f'{phase}: SHA-256 or size mismatch')


def prepare_release(release_dir, envelope, *, scope_path, pointer,
                    approval_from_queue: Callable[[str, str], Path], output):
    """Local only: emit checked assets into a *new* directory; no release API writes.

    The attended R8 handoff owner (astra-orchestrator) supplies
    ``approval_from_queue(region, envelope_sha256) -> Path``. The callable must
    authenticate the region's designated R8 verifier card (assigned to
    codex-reviewer, status done, with the exact verdict line
    ``APPROVED release <region> envelope=<envelope_sha256>``), then return that
    generation's ``review/<generation>/approval.json`` or raise. Chain checks
    verify the recorded verdict and bytes, not the reviewer's identity. A CLI
    path, release label, copied verdict or upload receipt cannot confer authority.
    ``scope_path`` must be the installed, operator-owned RELIEF-PUBLISH-SCOPE.
    The stage directory enters view only after every staged file checks.
    """
    from skippercast.relief import envelope as review, publish

    package.validate_schema(pointer, package.pointer_schema())
    approval = approval_from_queue(pointer['region'], pointer['envelope_sha256'])
    plan = publish.plan(release_dir, approval, envelope, scope_path=scope_path)
    # This delegates to verify_chain, and compares all current pointer metadata;
    # previous is repository rollback lineage, not part of the approved release.
    expected = review.build_pointer(approval, envelope)
    if expected != {**pointer, 'previous': None} or plan.envelope_sha256 != pointer['envelope_sha256']:
        raise StageError('pointer differs from approved release')
    archive, root = _objects(pointer)
    with TemporaryDirectory(prefix='.relief-', dir=output.parent) as temp:
        stage = Path(temp) / 'assets'
        stage.mkdir()

        def stage_one(obj, row):
            if obj.sha != row.sha256:
                raise StageError('pointer digest differs from approved inventory')
            dest = stage / obj.name
            if not dest.exists():
                with package.artifact_path(plan.region_dir, row.path).open('rb') as stream, dest.open('xb') as out:
                    _checked(stream, obj, row.size, phase='local stage', output=out)
            else:
                with dest.open('rb') as stream:
                    _checked(stream, obj, row.size, phase='local stage')
            return dest

        rows = {row.key: row for row in plan.objects}
        if archive.key not in rows or root.key not in rows:
            raise StageError('approved inventory lacks the archive or digest root')
        stage_one(archive, rows[archive.key])
        root_file = stage_one(root, rows[root.key])
        chunks = tuple(_chunks(pointer, root, root_file))
        if rows.keys() != {obj.key for obj in (archive, root, *chunks)}:
            raise StageError('approved inventory differs from pointer digest chain')
        for obj in chunks:
            stage_one(obj, rows[obj.key])
        if output.exists() or output.is_symlink():
            raise StageError('choose a new stage directory')
        stage.rename(output)
    return release_tag(pointer)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request):
    return build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=60)


def _json(request, limit):
    with _open(request) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise StageError('provider metadata exceeds the byte limit')
    return package.decode_document(data)


@dataclass(frozen=True)
class Asset:
    id: int
    size: int


class GitHubRelease:
    """Read only from the canonical same-repo API; never execute release content."""

    def __init__(self, read_token):
        self._token = read_token

    def _request(self, url, accept):
        headers = {'Accept': accept, 'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'SkipperCast-relief-stage'}
        if self._token:
            headers['Authorization'] = 'Bearer ' + self._token
        return Request(url, headers=headers)

    def metadata(self, path):
        return _json(self._request(_API + path, 'application/vnd.github+json'), 8 << 20)

    def assets(self, tag):
        release = self.metadata(f'/repos/{REPOSITORY}/releases/tags/{tag}')
        rid = release.get('id')
        if (type(rid) is not int or rid <= 0 or release.get('tag_name') != tag
                or release.get('url') != f'{_REPO_API}/releases/{rid}'
                or release.get('assets_url') != f'{_REPO_API}/releases/{rid}/assets'
                or release.get('draft') is not False or release.get('prerelease') is not False):
            raise StageError('GitHub release is not the expected same-repo published tag')
        # The release response includes its release assets. Do not follow asset
        # URLs from the response or accept evidence from a release body/label.
        rows = release.get('assets')
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ASSETS:
            raise StageError('invalid GitHub release asset inventory')
        assets, ids = {}, set()
        for row in rows:
            if not isinstance(row, dict):
                raise StageError('invalid GitHub asset metadata')
            aid, name, size = (row.get(k) for k in ('id', 'name', 'size'))
            if (type(aid) is not int or aid <= 0 or aid in ids or not isinstance(name, str) or not _ASSET.fullmatch(name)
                    or name in assets or type(size) is not int or size <= 0 or row.get('state') != 'uploaded'
                    or row.get('url') != f'{_REPO_API}/releases/assets/{aid}'
                    or row.get('digest') not in (None, 'sha256:' + name.split('.')[0])):
                raise StageError('invalid GitHub asset identity, state or size')
            assets[name] = Asset(aid, size)
            ids.add(aid)
        return assets

    def download(self, asset):
        try:
            response = _open(self._request(f'{_REPO_API}/releases/assets/{asset.id}', 'application/octet-stream'))
        except HTTPError as error:
            with error:
                location = urlsplit(error.headers.get('Location', ''))
                if (error.code != 302 or location.scheme != 'https' or location.netloc not in
                        {'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
                        or location.fragment or not location.path.startswith('/')):
                    raise StageError('GitHub asset download refused') from None
                # One trusted media hop, fresh request, never forward github.token.
                response = _open(Request(location.geturl()))
        if response.status != 200 or response.headers.get('Content-Range') is not None:
            response.close()
            raise StageError('GitHub asset did not return a full GET')
        return response


class R2:
    """Only full GET and atomic S3 PutObject(If-None-Match: *), never HEAD."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def connect(cls, token, account):
        import boto3
        from botocore.config import Config

        if not token or not re.fullmatch(r'[a-f0-9]{32}', account):
            raise StageError('relief requires R2_PUBLISH_TOKEN and CLOUDFLARE_ACCOUNT_ID')
        for path in (f'accounts/{account}/tokens/verify', 'user/tokens/verify'):
            try:
                doc = _json(Request('https://api.cloudflare.com/client/v4/' + path,
                                    headers={'Authorization': 'Bearer ' + token}), 1 << 16)
            except HTTPError as error:
                with error:
                    if error.code not in (400, 401, 403, 404):
                        raise
                continue
            result = doc.get('result')
            if (doc.get('success') is True and isinstance(result, dict) and result.get('status') == 'active'
                    and isinstance(result.get('id'), str) and re.fullmatch(r'[a-f0-9]{32}', result['id'])):
                break
        else:
            raise StageError('R2 publish token could not be verified')
        return cls(boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com', region_name='auto',
                                aws_access_key_id=result['id'], aws_secret_access_key=hashlib.sha256(token.encode()).hexdigest(),
                                config=Config(proxies={}, connect_timeout=15, read_timeout=60,
                                              request_checksum_calculation='when_required',
                                              response_checksum_validation='when_required')))

    @contextmanager
    def get(self, key):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'NoSuchKey'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404):
                raise
            yield None
            return
        with closing(response['Body']) as stream:
            if response['ResponseMetadata']['HTTPStatusCode'] != 200 or response.get('ContentRange') is not None:
                raise StageError('R2 did not return a full GET')
            yield stream

    def create(self, key, body, size):
        from botocore.exceptions import ClientError

        try:
            self.client.put_object(Bucket=BUCKET, Key=key, Body=body, ContentLength=size, IfNoneMatch='*',
                                   ContentType='application/json' if key.endswith('.json') else 'application/octet-stream',
                                   CacheControl='public, max-age=31536000, immutable')
        except ClientError as error:
            if (error.response.get('Error', {}).get('Code') != 'PreconditionFailed'
                    or error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 412):
                raise
            # A racing writer won. It still must pass the same full read-back.


def copy_release(pointer, github, r2, *, allow_create, recheck):
    """Verify the full per-release inventory before any PUT; leave good partial R2 copies on failure."""
    package.validate_schema(pointer, package.pointer_schema())
    archive, root = _objects(pointer)
    with TemporaryDirectory(prefix='relief-copy-') as temp:
        files = Path(temp)
        assets = github.assets(release_tag(pointer))

        def download(obj):
            asset = assets.get(obj.name)
            if asset is None:
                raise StageError('missing GitHub release asset')
            if asset.size > obj.limit or obj.size not in (None, asset.size):
                raise StageError('GitHub release asset size is outside its expected bound')
            path = files / obj.name
            if not path.exists():
                with github.download(asset) as stream, path.open('xb') as out:
                    _checked(stream, obj, asset.size, phase='GitHub asset', output=out)
            return path

        root_file = download(root)
        objects = (*_chunks(pointer, root, root_file), root, archive)
        if assets.keys() != {obj.name for obj in objects}:
            raise StageError('GitHub release asset list differs from the pointer digest chain')
        for obj in objects:
            download(obj)

        for obj in objects:
            size = assets[obj.name].size
            with r2.get(obj.key) as stream:
                if stream is not None:
                    _checked(stream, obj, size, phase='R2 read-back')
                    continue
            if not allow_create:
                raise StageError('manual deploy requires relief objects already copied to R2')
            if recheck is not None:
                recheck()
                recheck = None  # immediately before this release's first write
            with (files / obj.name).open('rb') as checked:
                r2.create(obj.key, checked, size)
            with r2.get(obj.key) as stream:
                if stream is None:
                    raise StageError('R2 read-back object missing')
                _checked(stream, obj, size, phase='R2 read-back')
    return len(objects)
