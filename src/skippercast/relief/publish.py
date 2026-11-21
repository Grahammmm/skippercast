"""Publish only approved relief objects; no credentials, transport adapter or pointers."""
from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import BinaryIO, Protocol

from skippercast.relief import package, receipts
from skippercast.relief.envelope import verify_chain
from skippercast.relief.package import ReleaseError

_BLOCK_BYTES = 1 << 20
_DIGEST_DIR = package.DIGEST_ROOT.removesuffix('root.json')
_CHUNK_NAME = re.compile(r'(?:[89]|1[0-7])/[0-9]+_[0-9]+\.json')


class Transport(Protocol):
    """Immutable object storage, with a transactional create and a full GET."""

    def exists(self, key: str) -> bool:
        """Check for presence only; this is never evidence of byte identity."""
        ...

    def put(self, key: str, chunks: Iterator[bytes]) -> None:
        """Create if absent. Commit only after chunks is exhausted without error.

        A producer exception must abort the pending write without making it
        visible. Never replace an existing key (including a concurrent create).
        An adapter unable to defer commit must stage the stream before its PUT.
        """
        ...

    def get(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Stream the entire object's stored bytes from a full GET, not a range."""
        ...


@dataclass(frozen=True)
class PublishObject:
    path: str  # relative to the region directory, as recorded in the envelope
    key: str
    sha256: str
    size: int


@dataclass(frozen=True)
class PublishPlan:
    release_dir: Path
    approval: Path
    envelope: Path
    scope_path: Path
    region_dir: Path
    envelope_sha256: str
    objects: tuple[PublishObject, ...]

    @property
    def receipt_path(self) -> Path:
        return self.envelope.with_name('upload.json')


def _digest_members(region_dir: Path, layers: dict[str, dict], root_sha: str) -> list[str]:
    raw = package.artifact_path(region_dir, package.DIGEST_ROOT).read_bytes()
    if (receipts.sha256_bytes(raw) != root_sha
            or len(raw) != layers[package.DIGEST_ROOT]['bytes']):
        raise ReleaseError('digest root changed during planning')
    root = package.decode_document(raw)
    chunks = root.get('chunks')
    if root.keys() != {'chunks'} or not isinstance(chunks, dict) or not chunks:
        raise ReleaseError('invalid relief digest root')
    names = [package.DIGEST_ROOT]
    for path, sha in sorted(chunks.items()):
        member = _DIGEST_DIR + path
        if (not _CHUNK_NAME.fullmatch(path) or member not in layers
                or sha != layers[member]['sha256']):
            raise ReleaseError(f'digest chunk does not match an approved layer: {path!r}')
        names.append(member)
    if set(names) != {name for name in layers if name.startswith(_DIGEST_DIR)}:
        raise ReleaseError('approved digest layers do not match the root inventory')
    return names


def plan(release_dir: Path, approval: Path, envelope: Path, *, scope_path: Path) -> PublishPlan:
    """Verify the current release, registry and operator scope without writing anything.

    The caller supplies the package directory (release/<generation>), trusted
    R8 approval and operator scope file. Only the PMTiles and its digest index
    go to object storage; other release layers are still verified by the chain.
    """
    approval, envelope = Path(approval).absolute(), Path(envelope).absolute()
    # verify_chain also enforces current public-display rights via package metadata.
    verified = verify_chain(approval, envelope)
    release = verified.release
    release_dir = Path(release_dir).absolute()
    if release_dir != verified.region_dir / 'release' / release['generation']:
        raise ReleaseError('release directory does not match the approved envelope')
    scope_path = Path(scope_path).absolute()
    try:
        scope = scope_path.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError) as exc:
        raise ReleaseError('cannot read RELIEF-PUBLISH-SCOPE') from exc
    if scope not in {'ALL', release['region']}:
        raise ReleaseError(f"region {release['region']!r} not in RELIEF-PUBLISH-SCOPE")

    root_sha = release['digest_root_sha256']
    layers = {row['path']: row for row in release['layers']}
    if not root_sha or package.DIGEST_ROOT not in layers:
        raise ReleaseError('relief digest root is required for publish')
    archive_sha = layers[package.ARCHIVE]['sha256']
    stem = f"tiles/relief/{release['region']}/{archive_sha}"
    try:
        members = _digest_members(verified.region_dir, layers, root_sha)
    except (OSError, ValueError) as exc:
        raise ReleaseError(f'cannot plan relief digest index: {exc}') from exc
    paths = [(package.ARCHIVE, f'{stem}.pmtiles')]
    paths.extend((name, f'{stem}.digests/{root_sha}/{name.removeprefix(_DIGEST_DIR)}') for name in members)
    objects = tuple(PublishObject(path, key, layers[path]['sha256'], layers[path]['bytes']) for path, key in paths)
    return PublishPlan(release_dir, approval, envelope, scope_path, verified.region_dir,
                       verified.envelope_sha256, objects)


def _blocks(stream: BinaryIO) -> Iterator[bytes]:
    yield from iter(lambda: stream.read(_BLOCK_BYTES), b'')


def _upload(root: Path, obj: PublishObject, transport: Transport) -> None:
    validated = False

    def checked_blocks(stream: BinaryIO) -> Generator[bytes, None, None]:
        nonlocal validated
        digest, size = hashlib.sha256(), 0
        for block in _blocks(stream):
            digest.update(block)
            size += len(block)
            if size > obj.size:
                raise ReleaseError(f'send-time size mismatch: {obj.key}')
            yield block
        if size != obj.size or digest.hexdigest() != obj.sha256:
            raise ReleaseError(f'send-time hash or size mismatch: {obj.key}')
        validated = True

    with package.artifact_path(root, obj.path).open('rb') as stream:
        body = checked_blocks(stream)
        try:
            transport.put(obj.key, body)
        finally:
            body.close()
    if not validated:
        raise ReleaseError(f'transport did not consume the complete checked body: {obj.key}')


def _read_back(obj: PublishObject, transport: Transport) -> dict:
    digest, size = hashlib.sha256(), 0
    with transport.get(obj.key) as stream:
        for block in _blocks(stream):
            digest.update(block)
            size += len(block)
    sha = digest.hexdigest()
    if size != obj.size or sha != obj.sha256:
        raise ReleaseError(f'full GET read-back hash or size mismatch: {obj.key}')
    return {'key': obj.key, 'sha256': sha, 'bytes': size}


def publish(planned: PublishPlan, transport: Transport) -> dict:
    """Verify or create the planned keys and atomically record successful read-back.

    An unchanged retry performs full GETs, but no PUTs or receipt rewrite.
    A failure writes no new receipt; good objects from partial attempts remain.
    Only a successful return authorizes use of the receipt for this invocation.
    """
    # Recheck because a queued dry-run plan can outlive its approval inputs or scope.
    current = plan(planned.release_dir, planned.approval, planned.envelope, scope_path=planned.scope_path)
    if current != planned:
        raise ReleaseError('approved publish plan changed; make a new plan')
    path = current.receipt_path
    if path.is_symlink() or path.resolve() in {current.approval.resolve(), current.scope_path.resolve()}:
        raise ReleaseError('upload receipt must not be a symlink or overwrite a gate input')

    results = []
    for obj in current.objects:
        if not transport.exists(obj.key):
            _upload(current.region_dir, obj, transport)
        results.append(_read_back(obj, transport))

    receipt = {'schema': 'sc-relief-upload/1', 'envelope_sha256': current.envelope_sha256, 'objects': results}
    if not path.exists() or package.decode_document(path.read_bytes()) != receipt:
        receipts.write_json_atomic(path, receipt)
    return receipt
