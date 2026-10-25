"""Additive S-019 segment receipt validation; read-only and offline.

This does not replace the shared workflow/graph validator. Open receipts are
hash-bound metadata, always REVIEW REQUIRED, not scientific or legal acceptance.
Actual COG, datum, rights and QA qualification stay with their stage owners.

``determinism_digest`` hashes content_identity() as sorted compact UTF-8 JSON,
without a newline (the existing producer object_digest convention). Volatile
run-envelope references, wall-clock/author/card bookkeeping and closure evidence
are excluded. Exact source bytes, recipe, code/tool versions, parameters, output
paths/hashes and evidence bindings remain included. Logical root IDs, not physical
root locations, are hashed. A signoff reviews these exact canonical identity bytes;
this avoids a receipt/verdict/archive hash cycle without unbinding the artifacts.

Closure needs an independently supplied trusted verdict Ref, a matching reviewed
identity in its open-report evidence snapshots, authenticated different-family
routing and existing archive-only verify_closed(). No file is created or copied.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

# Explicit checkout helper closure; never import an installed engine or rely on
# cwd/PYTHONPATH. Use a distinct module name to avoid the shared validator's name.
ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'skills/coast-campaign-shared/scripts'
sys.path[:0] = [str(SHARED), str(ROOT / 'src')]
from coast_refs import Resolver, SHA, canonical, loads, object_digest, relative_parts  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('missing checkout helper: ' + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow = _load('segment_workflow_validator', SHARED / 'validate_coast_receipt.py')
LIMIT = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def content_identity(receipt):
    """Frozen v1 projection; includes all content, not lifecycle bookkeeping."""
    fields = ('schema', 'schema_version', 'campaign_segment_id', 'coordinator_segment_id',
              'segment_slug', 'recipe_sha256', 'recipe', 'code_commit', 'skill_commit',
              'inputs', 'outputs', 'qa', 'tier1')
    return {key: receipt[key] for key in fields}


def determinism_digest(receipt):
    return object_digest(content_identity(receipt))


def document(resolver, ref):
    require(ref['bytes'] <= LIMIT, 'structured input exceeds 32 MiB')
    return loads(resolver.read(ref))


def _refs(value):
    if isinstance(value, dict):
        if set(value) == {'root_id', 'path', 'sha256', 'bytes'}:
            yield value
        else:
            for child in value.values():
                yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _closed(receipt, resolver, *, trusted_signoff, archive_resolver,
            original_queue_roots, original_raw_roots):
    require(trusted_signoff is not None and receipt['signoff']['verdict'] == trusted_signoff,
            'closed requires independently bound approved verdict')
    signoff = receipt['signoff']
    require(signoff['reviewed_digest'] == receipt['determinism_digest'], 'reviewed digest mismatch')
    reviewed = document(resolver, signoff['artifact'])
    require(reviewed == content_identity(receipt), 'reviewed artifact identity mismatch')
    require(resolver.read(signoff['artifact']) == canonical(reviewed), 'reviewed identity must be canonical')
    verdict = document(resolver, trusted_signoff)
    workflow.validate_schema(verdict)
    require(verdict['schema'] == 'coast-review-verdict-v1' and verdict['verdict'] == 'accept'
            and verdict['evidence_status'] == 'valid' and verdict['validation_scope'] == 'full_graph'
            and not verdict['must_fix'], 'closed requires valid full-graph accept verdict')
    # Existing review APIs bind runtime provenance and explicit owner-admitted
    # pairings. The caller's trusted verdict pins the complete evidence graph.
    review = _load('segment_review_common', ROOT / 'skills/coast-sign-off/scripts/review_common.py')
    context = review.trusted_context(resolver, verdict['context'])
    review.reviewer(resolver, context, verdict['reviewer_model'], verdict['reviewer_provenance'])
    policy = document(resolver, context['routing'])
    qualifications = [q for q in policy['qualified_reviewers'] if q['actual_model'] == verdict['reviewer_model']]
    require(len(qualifications) == 1 and qualifications[0]['provenance'] == verdict['reviewer_provenance'],
            'reviewer qualification provenance mismatch')
    report = document(resolver, verdict['open_report'])
    require(signoff['artifact'] in report['evidence_snapshots'], 'verdict does not review exact artifact identity')
    require(context['run'] == receipt['run'] and context['run_author_model'] == receipt['author_model'],
            'signoff does not bind receipt run/author')
    for key in ('campaign_segment_id', 'coordinator_segment_id'):
        require(verdict[key] == receipt[key], 'signoff segment identity mismatch')
    require(archive_resolver is not None and original_queue_roots,
            'closed requires existing archive-only verification')
    archive_id = receipt['archive']['manifest']['root_id']
    require(archive_id.startswith('archive:'), 'archive manifest requires archive namespace')
    close = _load('segment_close_common', ROOT / 'skills/coast-segment-close/scripts/close_common.py')
    result = close.verify_closed(archive_resolver, archive_id=archive_id,
                                 original_queue_roots=original_queue_roots,
                                 original_raw_roots=original_raw_roots or {})
    require(result['manifest_ref'] == receipt['archive']['manifest'], 'verified archive manifest mismatch')
    manifest = result['manifest']
    require(manifest['campaign_segment_id'] == receipt['campaign_segment_id']
            and trusted_signoff in manifest['selected_verdicts'], 'archive/verdict segment mismatch')
    retained = {canonical(item['source_ref']) for item in manifest['files']}
    for ref in _refs(content_identity(receipt)):
        require(canonical(ref) in retained, 'content evidence missing from verified archive')
    require(canonical(receipt['run']) in retained and canonical(signoff['artifact']) in retained,
            'reviewed identity/run missing from verified archive')


def validate_receipt(receipt, resolver, *, root_id, trusted_signoff=None,
                     archive_resolver=None, original_queue_roots=None, original_raw_roots=None):
    """Validate exact metadata bindings. External trust is never receipt-derived.

    ``resolver`` is the existing no-follow Resolver with independently admitted,
    disjoint roots. A closed receipt additionally requires caller-owned trust and
    an archive/raw-only Resolver for the existing archive verification barrier.
    """
    workflow.validate_schema(receipt)
    require(receipt['schema'] == 'coast-segment-receipt-v1', 'expected segment receipt')
    for ref in _refs(receipt):
        relative_parts(ref['path'])
        require(bool(SHA.fullmatch(ref['sha256'])), 'invalid reference SHA256')
        require(ref['root_id'] in resolver.bindings, 'unbound reference root')
    require(receipt['run']['root_id'] == root_id, 'run outside receipt root')
    require(root_id in resolver.bindings and root_id == 'queue:' + receipt['campaign_segment_id'],
            'receipt namespace differs from campaign segment')
    recipe = receipt['recipe']
    require(recipe['sha256'] == receipt['recipe_sha256'], 'recipe hash mismatch')
    run = document(resolver, receipt['run'])
    workflow.validate_schema(run)
    require(run['schema'] == 'coast-run-summary-v2', 'expected existing run-summary-v2')
    workflow._consistency(run)
    for key in ('campaign_segment_id', 'coordinator_segment_id', 'author_model', 'code_commit', 'skill_commit'):
        require(run[key] == receipt[key], 'run identity mismatch: ' + key)
    admission = document(resolver, run['admission'])
    workflow.validate_schema(admission)
    require(admission['schema'] == 'coast-admission-v1', 'expected existing admission')
    for key in ('campaign_segment_id', 'coordinator_segment_id', 'plan_id', 'plan_sha256'):
        require(run[key] == admission[key], 'admission/run identity mismatch: ' + key)
    admitted = {row['source_id']: row for row in admission['sources']}
    require(len(admitted) == len(admission['sources']), 'duplicate admitted source')
    inputs = {row['source_id']: row for row in receipt['inputs']}
    require(len(inputs) == len(receipt['inputs']), 'duplicate input source')
    for source_id, row in inputs.items():
        require(row['source_sha256'] == row['cache']['sha256'], 'source/cache hash mismatch')
        require(source_id in admitted and row['cache'] in admitted[source_id]['hot_cache'],
                'source is not bound to run admission')
    output_keys = []
    for row in receipt['outputs']:
        artifact = row['artifact']
        require(artifact['root_id'] == root_id, 'output outside receipt root')
        output_keys.append(artifact['path'])
        for source in row['contributing_sources']:
            bound = inputs.get(source['source_id'])
            require(bound is not None and bound['source_sha256'] == source['source_sha256'],
                    'unbound contributing source')
    require(len(set(output_keys)) == len(output_keys), 'duplicate output path')
    qa = receipt['qa']
    require(qa['hole_numerator'] <= qa['coverage_denominator'], 'QA numerator exceeds denominator')
    tier = receipt['tier1']
    if tier['mode'] == 'unavailable':
        require(tier['text_result'] == 'unavailable', 'unavailable text cannot pass')
    if tier['mode'] in ('unavailable', 'text_only'):
        require(tier['vision_result'] == 'unavailable', 'unavailable vision cannot pass')
    if tier['mode'] == 'text_and_vision':
        require('unavailable' not in (tier['text_result'], tier['vision_result']),
                'text_and_vision requires both actual results')
    require(receipt['determinism_digest'] == determinism_digest(receipt), 'determinism digest mismatch')
    # Schema validates every typed Ref before any read. Exact bytes only: JSON
    # payloads are not auto-dispatched as arbitrary contracts by their extension.
    for ref in _refs(receipt):
        resolver.read(ref, retain=False)
    if receipt['closed']:
        _closed(receipt, resolver, trusted_signoff=trusted_signoff,
                archive_resolver=archive_resolver, original_queue_roots=original_queue_roots,
                original_raw_roots=original_raw_roots)
    return dict(status='REVIEW REQUIRED', structurally_valid=True, closed_verified=receipt['closed'],
                semantic_approval=False, publication_allowed=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt_ref', type=Path, help='Operator-supplied typed receipt Ref JSON')
    parser.add_argument('--roots', required=True, type=Path)
    parser.add_argument('--allowed-root-id', action='append', required=True)
    parser.add_argument('--root-id', required=True)
    # CLI deliberately validates OPEN receipts only; closed integration needs
    # separately admitted trust and archive root mappings via validate_receipt().
    args = parser.parse_args(argv)
    try:
        # CLI control files use the same bounded no-follow reader as receipt data.
        review = _load('segment_cli_io', ROOT / 'skills/coast-sign-off/scripts/review_common.py')
        def control(path):
            path = path.absolute()
            reader = Resolver({'queue:control': str(path.parent)}, allowed_root_ids={'queue:control'})
            return loads(review.observed_read(reader, path))
        resolver = Resolver(control(args.roots), allowed_root_ids=args.allowed_root_id)
        receipt = document(resolver, control(args.receipt_ref))
        result = validate_receipt(receipt, resolver, root_id=args.root_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
