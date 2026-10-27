"""Non-relaxable fixed-patch policy, separate from ordinary scientific facts."""
from skippercast.coastal.handoff.common import digest
POLICY=dict(schema='coastal-fixed-patch-policy-v1',paired_cells=256,window_shape=[16,16],halo=0,
            mask_raw_source_normalized_finite_pairs=256,depth_minimum_m=0,depth_maximum_m=91.44,
            depth_minimum_inclusive=True,depth_maximum_inclusive=True,product_uncertainty_type='productUncert',
            product_uncertainty_units='m',uncertainty_minimum_m=0,uncertainty_minimum_inclusive=False,
            uncertainty_maximum_m=1,uncertainty_maximum_inclusive=True,uncertainty_scale=1,uncertainty_offset=0,
            quality_pairs=256,independent_quality_review_required=True,no_relocation=True,legacy_25ft_floor=False)
POLICY_SHA=digest(POLICY)
# Per-window quality outcomes; a hold with only these names is local to its window.
WINDOW_QUALITY_HOLDS=frozenset({'native_support_empty','bounded_patch_nominal_support_incomplete',
    'bounded_patch_nominal_depth_out_of_range','bounded_patch_uncertainty_quality_failed',
    'bounded_patch_partial_support_not_mask_only','bounded_patch_partial_support_below_floor',
    'bounded_patch_partial_support_without_unsupported_cells'})
def policy_for_profile(name=None, configuration=None):
    from .profiles import profile,support_policy,PARTIAL_SUPPORT
    selected=profile(name,configuration)
    if name is None:return POLICY
    result=dict(POLICY,schema='coastal-fixed-patch-policy-v3' if name=='coastal-contained-windows-v3' else 'coastal-fixed-patch-policy-v2',execution_profile=name,
                paired_cells=selected['pairs'],window_shape=[selected['side']]*2,
                mask_raw_source_normalized_finite_pairs=selected['pairs'],quality_pairs=selected['pairs'])
    if name=='coastal-contained-windows-v3':result.update(window_side=selected['side'],window_count=selected['window_count'])
    if support_policy(name,configuration)==PARTIAL_SUPPORT:
        # Pinned, distinct policy (own schema and SHA). Only mask-invalid cells may be
        # unsupported; every mask-valid cell must be a finite, source-valid, eligible pair.
        result.update(schema='coastal-fixed-patch-policy-partial-v1',support_policy=PARTIAL_SUPPORT,
                      mask_raw_source_normalized_finite_pairs='all_mask_valid',quality_pairs='all_mask_valid',
                      unsupported_cells='mask_invalid_only_as_nodata',
                      minimum_supported_pairs=(selected['pairs']+1)//2,minimum_unsupported_pairs=1)
    return result
def policy_sha(name=None,configuration=None):return digest(policy_for_profile(name,configuration))
def _support_holds(selected,counts,pairs):
    holds=[]
    if selected.get('support_policy') is None:
        for key in ('returned_paired_cells','paired_mask_valid','paired_raw_finite','source_pair_valid','normalized_finite'):
            if type(counts.get(key)) is not int or counts[key]!=pairs:holds.append('bounded_patch_nominal_support_incomplete')
        if type(counts.get('eligible')) is not int or counts['eligible']!=pairs:
            holds.append('bounded_patch_nominal_depth_out_of_range')
        return holds,pairs
    keys=('returned_paired_cells','paired_mask_valid','paired_raw_finite','source_pair_valid','normalized_finite','eligible')
    if any(type(counts.get(key)) is not int for key in keys) or counts['returned_paired_cells']!=pairs:
        return ['bounded_patch_nominal_support_incomplete'],pairs
    supported=counts['source_pair_valid']
    if not counts['paired_mask_valid']==counts['paired_raw_finite']==supported==counts['normalized_finite']:
        holds.append('bounded_patch_partial_support_not_mask_only')
    if counts['eligible']!=supported:holds.append('bounded_patch_nominal_depth_out_of_range')
    if supported<selected['minimum_supported_pairs']:holds.append('bounded_patch_partial_support_below_floor')
    if pairs-supported<selected['minimum_unsupported_pairs']:holds.append('bounded_patch_partial_support_without_unsupported_cells')
    return holds,supported
def evaluate(diagnostics,facts,*,execution_profile=None,configuration=None):
    selected=policy_for_profile(execution_profile,configuration);pairs=selected['paired_cells']
    counts=diagnostics['counts'];uncertainty=diagnostics['uncertainty']
    holds,quality_pairs=_support_holds(selected,counts,pairs)
    header=facts['header'];scales=header.get('scales');offsets=header.get('offsets');units=header.get('units')
    units_confirmed=(header.get('driver')=='BAG' and isinstance(scales,list) and len(scales)==2 and scales[1]==1
       and isinstance(offsets,list) and len(offsets)==2 and offsets[1]==0
       and isinstance(units,list) and len(units)==2 and units[1] in (None,'','m','metre','meter','metres','meters')
       and uncertainty.get('units')=='m')
    # The guarded adapter independently requires embedded productUncert XML and BAG raw FLOAT32 representation.
    if not units_confirmed:holds.append('bounded_patch_uncertainty_units_unresolved')
    if (type(uncertainty.get('count')) is not int or uncertainty['count']!=quality_pairs
        or uncertainty.get('minimum') is None or uncertainty.get('maximum') is None
        or not 0<uncertainty['minimum']<=uncertainty['maximum']<=1
        or uncertainty.get('nonpositive')!=0 or uncertainty.get('above_1m')!=0):
        holds.append('bounded_patch_uncertainty_quality_failed')
    return dict(schema='coastal-fixed-patch-policy-evaluation-v1',policy_sha256=policy_sha(execution_profile,configuration),
                facts_digest=diagnostics['facts_digest'],diagnostics_digest=diagnostics['diagnostics_digest'],
                holds=sorted(set(holds)),paired_eligibility_quality_pass=not holds,accepted=False,
                units_confirmation=dict(confirmed=units_confirmed,raw_scale=scales[1] if isinstance(scales,list) and len(scales)==2 else None,
                  raw_offset=offsets[1] if isinstance(offsets,list) and len(offsets)==2 else None,header_units=units[1] if isinstance(units,list) and len(units)==2 else None,
                  basis='strict guarded BAG FSD2.0 productUncert XML/raw metre representation plus actual band packing'))
def require_quality_review(review,*,facts_digest,diagnostics_digest,plan_sha256,trial_policy_sha256,execution_profile=None,configuration=None):
    if (review.get('quality_accepted') is not True or review.get('policy_sha256')!=policy_sha(execution_profile,configuration)
        or review.get('trial_policy_sha256')!=trial_policy_sha256
        or review.get('facts_digest')!=facts_digest or review.get('diagnostics_digest')!=diagnostics_digest
        or review.get('plan_sha256')!=plan_sha256):
        raise ValueError('independent complete fixed-patch quality review binding required')
