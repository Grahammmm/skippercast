#!/usr/bin/env python3
"""Raw, gzip-9 and zstd-19 sizes of files: python3 reports/perf/compress_sizes.py <file> ...
(zstd from the shared venv's zstandard module when importable; else only gzip.)"""
import gzip, sys
try:
    import zstandard
except ImportError:
    zstandard = None
for p in sys.argv[1:]:
    b = open(p, 'rb').read()
    z = len(zstandard.ZstdCompressor(level=19).compress(b)) if zstandard else None
    print(f"{p}: raw={len(b):,} gzip9={len(gzip.compress(b, 9)):,} zstd19={z if z is None else f'{z:,}'}")
