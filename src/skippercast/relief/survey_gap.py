"""M32: the survey gap companion stage, the reviewed survey detail's tier-none subset.

    region.py survey_gap --region <id> --out <OUT> --scope public

Reads the exact detail pair that the current ``survey_detail.public`` receipt attests and re-hashes it before use.
It then writes ``layers/public/survey-gap/gap.geojson`` and its Brotli wire, derived with
``survey_delivery.gap_document``, under this stage's own receipt. ``package`` can then list both files with
``--upstream survey_gap:public`` like any other receipted layer.

The stage holds (no outputs) in four cases: a changed or unattested detail, a wire that does not decode to the
attested detail, a detail with no tier-none area or with nothing else, and a companion over its size bound.
"""
from skippercast.relief import receipts, survey_delivery

SCOPES = ('public',)
UPSTREAM = ('survey_detail:{scope}',)
TARGET = survey_delivery.GAP_PREFIX.rstrip('/')
CODE_FILES = ('skippercast.relief.survey_delivery',)
DETAIL = 'survey_detail.public'


def _attested(ctx, relative):
    """The bytes of a survey-detail output, only if they still match the upstream receipt."""
    rows = [row for row in ctx.upstream[DETAIL]['outputs'] if row['path'] == relative]
    if len(rows) != 1:
        raise receipts.ReceiptError(f'survey_detail does not attest {relative}')
    try:
        data = (ctx.region.dir / relative).read_bytes()
    except OSError as exc:
        raise receipts.ReceiptError(f'cannot read {relative}') from exc
    if receipts.sha256_bytes(data) != rows[0]['sha256'] or len(data) != rows[0]['bytes']:
        raise receipts.ReceiptError(f'survey_detail output changed since its receipt: {relative}')
    return data


def plan(ctx):
    if ctx.scope != 'public':
        raise receipts.ReceiptError('the survey gap companion is public only')
    paths = {row['path'] for row in ctx.upstream[DETAIL]['outputs']}
    if paths != {survey_delivery.DECODED_PATH, survey_delivery.WIRE_PATH}:
        raise receipts.ReceiptError('survey_detail must attest exactly the survey-detail pair')
    return receipts.Plan([receipts.Input(ctx.region.dir / survey_delivery.DECODED_PATH, 'detail'),
                          receipts.Input(ctx.region.dir / survey_delivery.WIRE_PATH, 'detail-wire')],
                         {'codec': 'br:text:q11'})


def build(ctx, out):
    detail = _attested(ctx, survey_delivery.DECODED_PATH)
    _attested(ctx, survey_delivery.WIRE_PATH)
    pins = {'decoded': {'bytes': len(detail), 'sha256': receipts.sha256_bytes(detail)}}
    survey_delivery.check_decoded(ctx.region.dir / survey_delivery.WIRE_PATH, pins)  # the wire is this detail
    gap = survey_delivery.gap_document(detail)
    wire = survey_delivery.encode(gap)
    if len(gap) > survey_delivery.GAP_DECODED_LIMIT or len(wire) > survey_delivery.GAP_WIRE_LIMIT:
        raise receipts.ReceiptError('survey gap companion exceeds its size bound')
    (out / 'gap.geojson').write_bytes(gap)
    (out / 'gap.geojson.br').write_bytes(wire)
    return {'features': gap.count(b'"type":"Feature"'), 'decoded_bytes': len(gap), 'wire_bytes': len(wire)}
