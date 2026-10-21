"""Stage admitted cached bytes only; a missing input is a prefetch HOLD."""
import hashlib
import os
from pathlib import Path
import stat
import time

from admit_common import (absolute, bridge, canonical, check_stage, cli, context,
                          directory_fd, ensure_dir, file_ref, freeze, header, loads, read_json,
                          resolver_for, sha256, verify_provenance)
from skippercast.coastal.handoff.common import validate_derived_geotiff


def stage_cache(*, roots, campaign, selection, raw_receipt, out):
    """Hash/cap/provenance preflight before any bounded cache copy."""
    started = time.perf_counter()
    camp, sel, root, queue_id = context(campaign, selection)
    resolver = resolver_for(roots, sel, root, queue_id)
    raw = read_json(raw_receipt)
    fields = ('source_id', 'input', 'raw_provenance', 'retained_inputs')
    expected = [{k: w[k] for k in fields} for w in sel['windows']]
    if (set(raw) != {'schema','sources','campaign_sha256'}
            or raw.get('schema') != 'coast-raw-selection-v1' or raw.get('sources') != expected
            or raw.get('campaign_sha256') != sha256(canonical(camp))):
        raise ValueError('raw selection receipt differs from admitted provenance')
    out = absolute(out)
    out.relative_to(root)
    if out.exists() or out.is_symlink():
        raise ValueError('output already exists; new attempt required')
    if sel['catalog']['bytes'] > bridge.MAX_DOCUMENT_BYTES:
        raise ValueError('catalog metadata read bound exceeded')
    catalog = loads(resolver.read(sel['catalog']))
    rows = bridge.check_catalog(catalog)
    total = sum(w['input']['bytes'] for w in sel['windows'])
    if total > sel['max_total_bytes']:
        raise ValueError('selected bytes exceed plan byte cap')
    for w in sel['windows']:
        if not 0 < w['input']['bytes'] <= sel['budget']['bytes']:
            raise ValueError('source exceeds per-job byte cap')

        declared = rows[w['source_id']]['metadata'].get('source_hash')
        # Unlike the metadata-only bridge, staging requires an actual catalog SHA.
        if not declared or bridge._hash_binding(declared, w['input']['sha256']) != 'matched':
            raise ValueError('catalog SHA256 missing or differs from selected input')
        if rows[w['source_id']]['metadata'].get('size_bytes') != w['input']['bytes']:
            raise ValueError('catalog byte count differs from selected input')
        verify_provenance(w, resolver)
        original = resolver.bindings[w['input']['root_id']]/w['input']['path']
        if file_ref(original, w['input']['root_id'], resolver.bindings[w['input']['root_id']]) != w['input']:
            raise ValueError('source SHA256 mismatch')
        if original.suffix.lower() in ('.tif', '.tiff'):
            # Do not lose unbound source metadata/masks by copying only the TIFF.
            # Auxiliary-dependent sources need a separately admitted adapter.
            validate_derived_geotiff(resolver.bindings[w['input']['root_id']],
                                    {k:w['input'][k] for k in ('path','sha256','bytes')})
    sources = []
    # Every destination is content/identity addressed and write-once. Partial
    # attempts are retained on error; never overwrite or auto-clean them.
    for w in sel['windows']:
        suffix = Path(w['input']['path']).suffix.lower()
        if suffix not in bridge.NATIVE_SUFFIXES:
            raise ValueError('native BAG or GeoTIFF required')
        name = sha256(w['source_id'].encode())
        dest = root/'cache'/name/(w['input']['sha256']+suffix)
        ensure_dir(dest.parent)
        src = resolver.bindings[w['input']['root_id']]/w['input']['path']
        with directory_fd(src.parent) as parent:
            fd = os.open(src.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != w['input']['bytes']:
                    raise ValueError('source identity/type changed before copy')
                h, size = hashlib.sha256(), 0
                with directory_fd(dest.parent) as target:
                    output = os.open(dest.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target)
                    with os.fdopen(output, 'wb') as stream:
                        while True:
                            chunk = os.read(fd, min(1024*1024, w['input']['bytes']-size+1))
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > w['input']['bytes']:
                                raise ValueError('source grew while copying')
                            h.update(chunk)
                            stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                if size != w['input']['bytes'] or h.hexdigest() != w['input']['sha256']:
                    raise ValueError('source SHA256 changed while copying')
            finally:
                os.close(fd)
        hot = file_ref(dest, queue_id, root)
        sources.append(dict(source_id=w['source_id'], hot_cache=hot))
    result = dict(schema='coast-cache-stage-v1', **header(sel), campaign_segment_id=camp['campaign_segment_id'],
                  campaign_sha256=sha256(canonical(camp)),
                  selection_sha256=sha256(canonical(sel)), sources=sources, holds=[],
                  staging_bytes=total, staging_wall_s=time.perf_counter()-started, network_requests=0)
    check_stage(result, camp, sel)
    freeze(out, result)
    return result


if __name__ == '__main__':
    cli(stage_cache, ('roots', 'campaign', 'selection', 'raw-receipt', 'out'))
