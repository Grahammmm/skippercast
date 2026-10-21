"""Bounded retained native contracts, not execution or scientific acceptance.

Schema-less Store jobs require an explicit trusted edge contract. No shape or
filename alone selects that contract; bytes remain producer-native and unchanged.
"""
import math
import re
from pathlib import PurePosixPath

from coast_refs import canonical, object_digest, relative_parts

STORE_JOB = 'coastal-store-job-v1'
BINARY = {'native-raster-v1', 'native-raster-auxiliary-v1',
          'coastal-normalized-terrain-v1', 'coastal-native-support-v2'}
FIELDS = {
    STORE_JOB: 'job_id stage segment_id code_sha deps_sha params_sha input_manifest_sha input_manifest params budget lease_token region root segment deadline_utc',
    'coastal-native-job-v1': 'schema source window vertical rights synthetic segment_id review source_row metadata_sha256 catalog_lineage',
    'coastal-cached-observation-v1': 'schema synthetic source facts_digest facts holds acquisition requests transferred_bytes',
    'coastal-stage-result-v1': 'schema stage job_id segment_id lease_token code_sha deps_sha input_manifest_sha params_sha artifacts usage provenance state holds next_job',
    'private-mapping-input-v2': 'schema producer segment_id source source_row metadata_sha256 segment window declared_vertical rights synthetic native_facts valid_support facts_digest machine_holds review publication_prohibited',
    'coastal-mapping-run-v1': 'schema state holds segment_id mapping_input facts_digest source segment vertical outputs publication_prohibited synthetic provenance',
    'coastal-terrain-summary-v1': 'schema segment_id segment native_valid_count depth_m derivatives support native_resolution_m interpolated habitat publication_prohibited',
    'coastal-private-input-review-v2': 'schema independent reviewer_id facts_digest checked_at valid_until decision holds_added',
}
# Only these embedded schemas are metadata, never an arbitrary nested schema.
INLINE = {'vertical-v1', 'vertical-observation-v1'}


def closed(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise ValueError('unknown or missing native producer field')


def check(doc, contract):
    canonical(doc)
    if contract in FIELDS:
        closed(doc, FIELDS[contract].split())
        if contract == 'coastal-native-job-v1':
            closed(doc, FIELDS[contract].split(), 'schema source window vertical rights synthetic segment_id'.split())
        elif contract not in (STORE_JOB, 'coastal-stage-result-v1'):
            closed(doc, FIELDS[contract].split(), FIELDS[contract].split())
    if contract in ('coastal-native-job-v1', 'coastal-cached-observation-v1', 'private-mapping-input-v2', 'coastal-mapping-run-v1'):
        source = doc.get('source')
        if not isinstance(source, dict) or not {'path', 'sha256', 'bytes'} <= source.keys():
            raise ValueError('native producer requires complete source reference')
    if doc.get('source_row') is not None:
        raise ValueError('held: retained source-row adapter not yet admitted')
    facts = doc.get('facts', doc.get('native_facts', {}))
    if not isinstance(facts, dict) or not isinstance(facts.get('source_lineage', {}), dict):
        raise ValueError('malformed native facts/source lineage')
    if facts.get('source_lineage', {}).get('source_row') is not None:
        raise ValueError('held: retained source-row adapter not yet admitted')
    if contract == STORE_JOB:
        closed(doc, FIELDS[contract].split(), FIELDS[contract].split())
        if 'schema' in doc or doc['stage'] not in ('acquire', 'qualify', 'map'):
            raise ValueError('unsupported Store job lane (discover/render/dedicated lanes held)')
        if not re.fullmatch(r'job:[0-9a-f]{24}', doc['job_id']) or not re.fullmatch(r'[0-9a-f]{32}', doc['lease_token']):
            raise ValueError('invalid Store job/lease identity')
        for key in ('code_sha', 'deps_sha', 'params_sha', 'input_manifest_sha'):
            if not isinstance(doc[key], str) or not re.fullmatch(r'[0-9a-f]{64}', doc[key]):
                raise ValueError('invalid Store digest')
        closed(doc['budget'], ('wall_s', 'memory_bytes', 'bytes', 'requests'), ('wall_s', 'memory_bytes', 'bytes', 'requests'))
        for key, number in doc['budget'].items():
            if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                raise ValueError('invalid Store budget')
        if doc['budget']['wall_s'] <= 0 or doc['budget']['memory_bytes'] <= 0 or doc['budget']['requests'] != 0:
            raise ValueError('unsupported Store budget')
        if type(doc['deadline_utc']) not in (int, float) or not math.isfinite(doc['deadline_utc']):
            raise ValueError('invalid Store deadline')
        # This adapter admits the ordinary acquire/qualify/map producer only.
        # Nonempty parameters need their own explicit adapter, not recursive trust.
        if doc['params'] != {} or doc['params_sha'] != object_digest(doc['params']):
            raise ValueError('unsupported Store parameters')
        source = doc['input_manifest']
        if not isinstance(source, dict) or source.get('sha256') != doc['input_manifest_sha']:
            raise ValueError('Store input digest mismatch')
        relative_parts(source['path'])
        owned = dict(schema='coastal-owned-input-v1', **{k: source[k] for k in ('path', 'sha256', 'bytes')})
        key = object_digest([doc['stage'], doc['segment_id'], owned, doc['code_sha'], doc['deps_sha'], doc['params_sha'], object_digest(doc['budget'])])
        if doc['job_id'] != 'job:' + key[:24]:
            raise ValueError('Store job identity mismatch')
        if doc['segment']['segment_id'] != doc['segment_id'] or doc['segment']['region'] != doc['region']:
            raise ValueError('Store segment identity mismatch')
    if contract == 'coastal-stage-result-v1':
        required = {'stage', 'job_id', 'segment_id', 'lease_token', 'code_sha', 'deps_sha', 'input_manifest_sha', 'params_sha', 'artifacts', 'state', 'holds', 'usage', 'provenance'}
        closed(doc, FIELDS[contract].split(), required)
        if doc['state'] not in ('done', 'held', 'failed_retryable', 'failed_terminal', 'cancelled'):
            raise ValueError('unknown native result state')
        if not isinstance(doc['artifacts'], list):
            raise ValueError('native artifacts must be a list')
        if 'next_job' in doc:
            closed(doc['next_job'], ('stage', 'input_manifest', 'params', 'budget'), ('stage', 'input_manifest', 'params', 'budget'))
            if doc['next_job']['params'] != {}:
                raise ValueError('unsupported successor parameters')
            if doc['next_job']['input_manifest'] not in doc['artifacts']:
                raise ValueError('successor input absent from native result artifacts')
            if doc['next_job']['stage'] != {'acquire': 'qualify', 'qualify': 'map', 'map': 'render'}.get(doc['stage']):
                raise ValueError('native successor stage mismatch')
    if contract == 'coastal-mapping-run-v1':
        closed(doc['outputs'], ('terrain', 'mask', 'cells'), ('terrain', 'mask', 'cells'))
        if doc['source'] != doc['mapping_input']['source'] or doc['facts_digest'] != doc['mapping_input']['facts_digest']:
            raise ValueError('mapping source/facts identity mismatch')
    if contract in ('coastal-cached-observation-v1', 'private-mapping-input-v2'):
        facts = doc['facts' if contract == 'coastal-cached-observation-v1' else 'native_facts']
        if object_digest(facts) != doc['facts_digest'] or facts['source'] != doc['source']:
            raise ValueError('observation facts identity mismatch')


def job_location(doc, ref, queue_origin):
    expected = f"var/coastal/jobs/{doc['job_id'].replace(':', '-')}/{doc['lease_token']}/job.json"
    if ref['path'] != expected or doc['root'] != str(queue_origin) or not PurePosixPath(doc['root']).is_absolute():
        raise ValueError('Store original queue/job location mismatch')
