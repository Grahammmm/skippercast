"""The survey detail stage: a region's reviewed survey-confidence map, in the form the Chart loads.

    region.py survey_detail --region <id> --out <OUT> --scope public

Reads the public zone detail that the current ``zone.public`` receipt attests and the public selection the zone was
built from, each re-hashed against its upstream receipt before use. It then writes
``layers/public/survey-detail/detail.geojson``, derived with ``survey_delivery.detail_document``, and its Brotli wire
under this stage's own receipt. ``package`` lists both with ``--upstream survey_detail:public`` (and refuses a detail
naming a source the release does not credit), and ``survey_gap`` derives the no-survey companion from them.

The stage holds (no outputs) when the zone detail or selection changed since its receipt, when either is not this
region's, when a surveyed area does not name exactly one public catalog source, or when the pair exceeds its size
bound.
"""
import json

from skippercast.relief import receipts, survey_delivery

SCOPES = ('public',)
UPSTREAM = ('select', 'zone:{scope}')
TARGET = survey_delivery.PREFIX.rstrip('/')
CODE_FILES = ('skippercast.relief.survey_delivery',)
ZONE = 'zone.public'
ZONE_DETAIL = 'layers/public/zone/detail.geojson'
SELECTION = 'select/selection.json'


def _attested(ctx, key, relative):
    """The bytes of an upstream output, only if they still match that upstream's receipt."""
    rows = [row for row in ctx.upstream[key]['outputs'] if row['path'] == relative]
    if len(rows) != 1:
        raise receipts.ReceiptError(f'{key} does not attest {relative}')
    try:
        data = (ctx.region.dir / relative).read_bytes()
    except OSError as exc:
        raise receipts.ReceiptError(f'cannot read {relative}') from exc
    if receipts.sha256_bytes(data) != rows[0]['sha256'] or len(data) != rows[0]['bytes']:
        raise receipts.ReceiptError(f'{key} output changed since its receipt: {relative}')
    return data


def _source_ids(ctx):
    """Included public selection file id -> catalog source id, from the selection bytes select attests."""
    selection = json.loads(_attested(ctx, 'select', SELECTION).decode('utf-8'))
    if selection['scope'] != 'public' or selection['region'] != ctx.region.id:
        raise receipts.ReceiptError('expected the public selection of this region')
    return {row['id']: row['source_id'] for row in selection['files']
            if row['decision'] == 'included' and row['rights_class'] == 'public'}


def plan(ctx):
    if ctx.scope != 'public':
        raise receipts.ReceiptError('the survey detail is public only')
    return receipts.Plan([receipts.Input(ctx.region.dir / ZONE_DETAIL, 'zone-detail'),
                          receipts.Input(ctx.region.dir / SELECTION, 'selection')],
                         {'codec': 'br:text:q11'})


def build(ctx, out):
    zone = _attested(ctx, ZONE, ZONE_DETAIL)
    sources = _source_ids(ctx)
    try:
        detail = survey_delivery.detail_document(zone, ctx.region.id, sources)
    except ValueError as exc:
        raise receipts.ReceiptError(str(exc)) from None
    wire = survey_delivery.encode(detail)
    if len(detail) > survey_delivery.DECODED_LIMIT or len(wire) > survey_delivery.WIRE_LIMIT:
        raise receipts.ReceiptError('survey detail exceeds its size bound')
    (out / 'detail.geojson').write_bytes(detail)
    (out / 'detail.geojson.br').write_bytes(wire)
    tiers = {}
    for feature in json.loads(detail)['features']:
        tier = feature['properties']['tier']
        tiers[tier] = tiers.get(tier, 0) + 1
    return {'features_by_tier': tiers, 'decoded_bytes': len(detail), 'wire_bytes': len(wire)}
