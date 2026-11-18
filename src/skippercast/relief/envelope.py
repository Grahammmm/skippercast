"""Bind public relief layers and QA to the exact bytes approved in review (R7–R9)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from skippercast.paths import repo_root
from skippercast.relief import package, receipts
from skippercast.relief.package import ReleaseError

ENVELOPE_SCHEMA = 'sc-relief-envelope/1'
_RELEASE_KEYS = {*package.METADATA, 'schema', 'generation', 'code_sha', 'private', 'disclaimer',
                 'layers', 'digest_root_sha256'}


@dataclass(frozen=True)
class VerifiedRelease:
    """Verified snapshot. A sender must still hash the bytes it actually sends."""
    region_dir: Path
    envelope_sha256: str
    release_sha256: str
    release: dict


def _paths(gen: str) -> tuple[str, str]:
    return f'release/{gen}/release.json', f'qa/{gen}/qa.json'


def _record(root: Path, relative: str) -> tuple[dict, bytes]:
    raw = package.artifact_path(root, relative).read_bytes()
    return {'path': relative, 'sha256': receipts.sha256_bytes(raw)}, raw


def _release_and_qa(root: Path, region: str, gen: str, *, expected: dict | None = None):
    release_path, qa_path = _paths(gen)
    release_ref, raw = _record(root, release_path)
    if expected is not None and release_ref != expected.get('release'):
        raise ReleaseError('release.json does not match envelope')
    release = package.decode_document(raw)
    if (release.keys() != _RELEASE_KEYS or release['schema'] != package.RELEASE_SCHEMA
            or release['region'] != region or release['generation'] != gen or release['private'] is not False
            or release['disclaimer'] != package.DISCLAIMER or not isinstance(release['code_sha'], str)
            or not re.fullmatch(r'[a-f0-9]{40}', release['code_sha'])):
        raise ReleaseError('invalid public release identity or metadata')
    package.validate_metadata(release, package.pointer_schema(), package.decode_document(
        (repo_root() / 'catalog/sources.json').read_bytes()))
    layers = package.release_layers(release)
    if expected is not None and receipts.canonical(layers) != receipts.canonical(expected.get('layers')):
        raise ReleaseError('envelope layer list does not match release')
    qa_ref, raw = _record(root, qa_path)
    if expected is not None and qa_ref != expected.get('qa'):
        raise ReleaseError('qa.json does not match envelope')
    qa = package.decode_document(raw)
    if qa.get('status') != 'PASS' or qa.get('release_sha256') != release_ref['sha256']:
        raise ReleaseError('QA must PASS and quote the current release sha256')
    return release, release_ref, qa_ref, layers


def _check_layers(root: Path, layers: list[dict]) -> None:
    for row in layers:
        if package.layer_record(root, row['path']) != row:
            raise ReleaseError(f'layer hash or size changed: {row["path"]}')


def verify_chain(approval: Path, envelope: Path) -> VerifiedRelease:
    """Verify local approval and every pinned artifact; raise ReleaseError on refusal.

    Approval must be supplied by the caller from the trusted review gate. This
    verifies the exact recorded verdict, not the reviewer's identity or upload scope.
    """
    try:
        approval_doc = package.decode_document(Path(approval).read_bytes())
        path = Path(envelope)
        if len(path.parents) < 3 or path.name != 'envelope.json' or path.parent.parent.name != 'review':
            raise ReleaseError('expected review/<generation>/envelope.json')
        root, gen = path.parents[2], path.parent.name
        receipts.check_names('envelope', region=root.name)
        if not package.is_sha256(gen):
            raise ReleaseError('invalid release generation')
        envelope_ref, raw = _record(root, f'review/{gen}/envelope.json')
        digest = envelope_ref['sha256']
        if digest != approval_doc.get('envelope_sha256'):
            raise ReleaseError('envelope sha256 does not match approval')
        if approval_doc.get('verdict') != f'APPROVED release {root.name} envelope={digest}':
            raise ReleaseError('approval lacks the exact release verdict')
        doc = package.decode_document(raw)
        if (doc.keys() != {'schema', 'region', 'generation', 'release', 'qa', 'layers'}
                or doc['schema'] != ENVELOPE_SCHEMA or doc['region'] != root.name or doc['generation'] != gen):
            raise ReleaseError('envelope identity does not match its region and generation')
        release, release_ref, _, layers = _release_and_qa(root, root.name, gen, expected=doc)
        _check_layers(root, layers)
        return VerifiedRelease(root, digest, release_ref['sha256'], release)
    except ReleaseError:
        raise
    except (OSError, ValueError) as exc:
        raise ReleaseError(str(exc)) from exc


def build_pointer(approval: Path, envelope: Path, *, previous: dict | None = None) -> dict:
    """Build a repo-pointer candidate, without writing it or authorizing upload."""
    verified = verify_chain(approval, envelope)
    release = verified.release
    if not release['digest_root_sha256']:
        raise ReleaseError('the relief digest root is required for a repo pointer')
    schema = package.pointer_schema()
    prior = None
    if previous is not None:
        package.validate_schema(previous, schema)
        if previous['region'] != release['region']:
            raise ReleaseError('previous pointer belongs to another region')
        prior = {key: previous[key] for key in ('generation', 'release_sha256', 'envelope_sha256', 'sha256')}
    archive = next(row for row in release['layers'] if row['path'] == package.ARCHIVE)
    pointer = {key: release[key] for key in (*package.METADATA, 'generation', 'digest_root_sha256')}
    pointer.update(schema='sc-relief-pointer/1', status='reviewed', private=False,
                   release_sha256=verified.release_sha256, envelope_sha256=verified.envelope_sha256,
                   sha256=archive['sha256'], bytes=archive['bytes'], previous=prior)
    package.validate_schema(pointer, schema)
    return pointer


def main(argv=None) -> int:
    parser = package.stage_parser('envelope')
    parser.add_argument('--generation', required=True, help='generation from the current package receipt')
    args = parser.parse_args(argv)
    gen = args.generation
    if not package.is_sha256(gen):
        parser.error('invalid release generation')
    try:
        region = package.stage_region(args.out, args.region, 'review')
    except ValueError as exc:
        parser.error(str(exc))
    upstream = {}

    def plan(docs):
        upstream.update(docs)
        return receipts.Plan(params={'release_generation': gen})

    def build(out_dir):
        if upstream['package']['generation'] != gen:
            raise ReleaseError('requested release is not the current package generation')
        _, release_ref, qa_ref, layers = _release_and_qa(region.dir, region.id, gen)
        for stage, ref in (('package', release_ref), ('qa', qa_ref)):
            if not any(all(row.get(k) == v for k, v in ref.items()) for row in upstream[stage]['outputs']):
                raise ReleaseError(f'{stage} bytes do not match the current stage receipt')
        _check_layers(region.dir, layers)
        doc = dict(schema=ENVELOPE_SCHEMA, region=region.id, generation=gen, release=release_ref, qa=qa_ref, layers=layers)
        (out_dir / 'envelope.json').write_bytes(receipts.canonical(doc))

    code = receipts.stage_digest([('envelope.py', Path(__file__)), ('package.py', Path(package.__file__))])
    result = receipts.run_stage(receipts.StageRun(region, 'envelope', build, code,
                                upstream=[receipts.Ref('package'), receipts.Ref('qa')], plan=plan, target=f'review/{gen}'))
    print(result.line())
    return result.exit_code
