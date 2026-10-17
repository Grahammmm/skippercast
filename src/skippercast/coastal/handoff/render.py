"""Deterministic measured terrain/imagery handoff for private previews.

Private preview acceptance never establishes website display acceptance.
"""
from . import mapping_input
from .common import digest, load, ref, resolve, review_holds, confined, write, validate_derived_geotiff
from .. import mapping

SCHEMA = 'render-handoff-v2.1'


def _facts(root, run, imagery, alignment, *, now, rights=None, minimum_valid_until=None):
    import rasterio
    checked = mapping.verify(root, run, now=now,minimum_valid_until=minimum_valid_until)
    facts = dict(mapping_digest=digest(checked['run']), native_facts_digest=checked['run']['facts_digest'],
                 terrain=checked['run']['outputs']['terrain'], mask=checked['run']['outputs']['mask'],
                 vertical=checked['run']['vertical'], imagery=imagery, alignment=alignment,
                 rights=rights,segment=checked['run']['segment'],segment_id=checked['run']['segment_id'])
    holds = list(checked['holds'])
    if rights is None or rights.get('private_use') is not True or not rights.get('evidence'):
        holds.append('imagery_private_rights_missing')
    else:
        for artifact in rights['evidence']:
            resolve(root,artifact)
    if imagery is None:
        holds.append('imagery_missing')
    else:
        path = validate_derived_geotiff(root, imagery)
        with rasterio.open(path) as ds:
            if not ds.crs:
                raise ValueError('imagery CRS required')
            facts['imagery_header'] = dict(crs=ds.crs.to_wkt(), shape=[ds.height,ds.width],
                transform=list(ds.transform)[:6], resolution=list(ds.res), dtypes=list(ds.dtypes),
                count=ds.count, tags=ds.tags())
    if alignment is None:
        holds.append('numeric_alignment_missing')
    elif imagery is not None:
        document = load(root, alignment, contract='alignment-receipt-v1')
        from ..render.align import measure_alignment, correspondence_holds
        recomputed = measure_alignment(resolve(root,facts['terrain']), resolve(root,imagery),
            document['control_points'], minimum_overlap=document.get('minimum_overlap',0.95),
            maximum_residual_cells=document.get('maximum_residual_cells',0.5),
            correspondence=document.get('correspondence'),root=root,now=now)
        if digest(document) != digest(recomputed):
            raise ValueError('numeric alignment changed or forged')
        # Measurements/facts stay immutable. The required dispatch horizon is
        # a separate gate over the independently supplied review bytes.
        if minimum_valid_until is not None:
            holds.extend(correspondence_holds(document.get('correspondence'),
                document['control_points'],document['terrain'],document['imagery'],
                root=root,now=now,minimum_valid_until=minimum_valid_until))
        facts['numeric_alignment'] = document
        if document.get('status') != 'ready':
            holds.extend(document.get('holds', ['alignment_not_accepted']))
    return facts, sorted(set(holds))


def produce(root, run_manifest, *, output_dir, now, imagery=None, alignment=None, review=None, rights=None, minimum_valid_until=None):
    run = load(root,run_manifest,contract=mapping.SCHEMA)
    facts, holds = _facts(root,run,imagery,alignment,now=now,rights=rights,minimum_valid_until=minimum_valid_until)
    review_issues = review_holds(root, review, digest(facts), now=now, minimum_valid_until=minimum_valid_until,schema='coastal-render-review-v1')
    if review is not None:
        reviewed = load(root,review,contract='coastal-render-review-v1')
        rights = reviewed.get('rights',{})
        if rights.get('private_use') is not True or not rights.get('evidence'):
            review_issues.append('imagery_private_rights_missing')
        for artifact in rights.get('evidence',[]):
            resolve(root,artifact)
    holds = sorted(set(holds+review_issues))
    slice_ = dict(id=run['segment_id'], terrain=facts['terrain'], mask=facts['mask'],
                  imagery=imagery, alignment=alignment, vertical=facts['vertical'],
                  private_preview=dict(state='held' if holds else 'accepted',holds=holds),
                  website_display=dict(state='held',holds=['product_loader_support_contract_unavailable']))
    result = dict(schema=SCHEMA, producer='coastal.handoff.render', run=run, facts=facts, segment_id=run['segment_id'],segment=run['segment'],rights=rights,
                  facts_digest=digest(facts), review=review, slices=[slice_],
                  selected_slice_ids=[] if holds else [slice_['id']], website_selected_slice_ids=[],
                  state='PARTIAL' if imagery is None else 'BLOCKED' if holds else 'PRIVATE_PREVIEW_READY',
                  publication_prohibited=True, synthetic=run['synthetic'])
    out = confined(root,output_dir,existing=False)
    out.mkdir(parents=True,exist_ok=True)
    write(out/'render-handoff.json',result)
    return result


def verify(root, manifest, *, now, purpose='private_preview', minimum_valid_until=None):
    if purpose not in ('private_preview','website_display'):
        raise ValueError('explicit known render purpose required')
    doc = load(root,manifest,contract=SCHEMA)
    if doc.get('schema') != SCHEMA:
        raise ValueError('render handoff contract mismatch')
    facts, holds = _facts(root,doc['run'],doc['facts'].get('imagery'),doc['facts'].get('alignment'),now=now,
                          rights=doc.get('rights'),minimum_valid_until=minimum_valid_until)
    if doc.get('segment_id') != doc['run']['segment_id'] or doc.get('segment') != doc['run']['segment']:
        raise ValueError('render segment lineage changed')
    if digest(facts) != doc['facts_digest'] or digest(facts) != digest(doc['facts']):
        raise ValueError('render facts changed or forged')
    holds.extend(review_holds(root,doc.get('review'),digest(facts),now=now,
        minimum_valid_until=minimum_valid_until,schema='coastal-render-review-v1'))
    if doc.get('review'):
        review = load(root,doc['review'],contract='coastal-render-review-v1')
        rights = review.get('rights',{})
        if rights.get('private_use') is not True or not rights.get('evidence'):
            holds.append('imagery_private_rights_missing')
        for artifact in rights.get('evidence',[]):
            resolve(root,artifact)
    holds = sorted(set(holds))
    # A previously accepted immutable packet may cease to cover a requested
    # job horizon. Preserve its scientific facts and return a typed dispatch
    # hold instead of mistaking dynamic validity for forged selection metadata.
    if 'independent_correspondence_review_insufficient_validity' in holds:
        return dict(ready=False,holds=holds,selected_slice_ids=[],document=doc,facts=facts)
    expected_ids = [] if holds else [doc['run']['segment_id']]
    slice_ = doc['slices'][0]
    if (len(doc['slices']) != 1 or slice_['id'] != doc['run']['segment_id']
            or any(slice_.get(k)!=facts.get(k) for k in ('terrain','mask','imagery','alignment','vertical'))
            or slice_['private_preview'] != dict(state='held' if holds else 'accepted',holds=holds)
            or doc['selected_slice_ids'] != expected_ids or doc.get('website_selected_slice_ids') != []
            or slice_['website_display'] != dict(state='held',holds=['product_loader_support_contract_unavailable'])):
        raise ValueError('derived render selection changed')
    if purpose == 'website_display':
        holds.append('product_loader_support_contract_unavailable')
    return dict(ready=not holds, holds=sorted(set(holds)),
                selected_slice_ids=expected_ids if purpose=='private_preview' else [], document=doc, facts=facts)


validate = verify
