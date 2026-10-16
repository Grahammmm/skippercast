"""Same-return facts supplement. No source read or second normalization."""
import hashlib
from pathlib import Path
import numpy as np
from skippercast.coastal.handoff.common import digest
def summarize(arrays,facts_digest):
    a,u=arrays['raw_elevation_data'],arrays['raw_uncertainty_data']
    am,um=arrays['elevation_mask'],arrays['uncertainty_mask']
    valid=arrays['source_pair_valid'];depth=arrays['depth']
    if a.shape!=u.shape or any(x.shape!=a.shape or x.dtype!=np.dtype('bool') for x in (am,um,valid)):
        raise ValueError('same-return paired shape/masks required')
    mask_valid=~am & ~um;rawfinite=np.isfinite(a)&np.isfinite(u)
    if np.any(valid & ~(mask_valid&rawfinite)):raise ValueError('source validity exceeds native pairs')
    count=lambda x:int(np.count_nonzero(x))
    counts=dict(returned_paired_cells=int(a.size),mask_invalid=count(~mask_valid),
        mask_valid_raw_nonfinite=count(mask_valid&~rawfinite),
        mask_valid_raw_finite_source_invalid=count(mask_valid&rawfinite&~valid),
        paired_mask_valid=count(mask_valid),paired_raw_finite=count(mask_valid&rawfinite),
        source_pair_valid=count(valid),elevation_mask_invalid=count(am),uncertainty_mask_invalid=count(um))
    if depth is None:
        counts.update(normalized_nonfinite=None,finite_below_0=None,finite_above_91_44=None,eligible=None,
            invalid=None,valid_but_out_of_range=None,normalized_finite=None)
    else:
        if depth.shape!=a.shape or depth.dtype!=np.dtype('float64'):raise ValueError('unchanged FLOAT64 depth required')
        finite=np.isfinite(depth)
        counts.update(normalized_nonfinite=count(valid&~finite),
            finite_below_0=count(valid&finite&(depth<0)),finite_above_91_44=count(valid&finite&(depth>91.44)),
            eligible=count(valid&finite&(depth>=0)&(depth<=91.44)),normalized_finite=count(valid&finite))
        counts['invalid']=counts['mask_invalid']+counts['mask_valid_raw_nonfinite']+counts['mask_valid_raw_finite_source_invalid']+counts['normalized_nonfinite']
        counts['valid_but_out_of_range']=counts['finite_below_0']+counts['finite_above_91_44']
        if counts['invalid']+counts['valid_but_out_of_range']+counts['eligible']!=a.size:raise ValueError('partition inconsistent')
    uq=u[valid]
    hashes={key:hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
            for key,value in arrays.items() if value is not None}
    result=dict(schema='coastal-same-return-pair-diagnostics-v1',facts_digest=facts_digest,
        counts=counts,array_hashes=hashes,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),depth_status='unavailable' if depth is None else 'resolved',
        uncertainty=dict(units='m',scope='original paired-valid product uncertainty',count=int(uq.size),
            minimum=None if not uq.size else float(uq.min()),maximum=None if not uq.size else float(uq.max()),
            nonpositive=count(uq<=0),above_1m=count(uq>1),
            legacy_25_300ft_uncertainty_0_1m_count=count(arrays['legacy_25_300ft_uncertainty_0_1m'])),
        semantics='Mask-first, then raw finite, then actual frozen source validity/sentinel gate, then returned normalized depth finite and inclusive0..91.44; nominal eligibility is not terrain/product-quality qualification.',
        raw_data_kind='underlying same-read GDAL FLOAT32 data plus native masks; invalid cells never soundings',
        accepted=False,qualification=False)
    result['diagnostics_digest']=digest(result)
    return result
