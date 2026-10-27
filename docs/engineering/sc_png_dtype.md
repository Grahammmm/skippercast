# Coastal preview PNG: uint8-only input (SC-PNG-DTYPE)

`skippercast.coastal.render.mesh.write_png(path, rgb)` writes the fixed-format
coastal preview: one 640x480 image, 8-bit RGB (IHDR bit depth 8, colour type 2),
one zlib level-6 IDAT of filter-0 scanlines, then IEND. The header always declares
8-bit samples, so the scanline bytes are only meaningful when every array element is
exactly one unsigned byte.

## Contract

- `rgb` must have shape `(480, 640, 3)`; anything else is refused with
  `ValueError` as before (`fixed_preview_size_required`, or the unpacking error for a
  different number of dimensions).
- `rgb.dtype` must be unsigned 8-bit (`kind == "u"`, `itemsize == 1`). Every other
  dtype of the right shape (wider unsigned in either byte order, signed integer,
  float, complex, bool, byte-string, object) raises
  `ValueError("fixed_preview_uint8_required")`.
- The refusal happens before any row is encoded and before the target path is
  opened: no file is created and an existing file keeps its bytes, inode and mtime.
- There is no implicit conversion. In-range `uint16` values are refused too, rather
  than narrowed; callers that compute colours in a wider type clip and cast to
  `uint8` themselves (both in-repo renderers already do).
- Valid input is encoded exactly as before. Contiguous arrays give byte-identical
  output to the base implementation; strided, reversed, Fortran-order and read-only
  views are written in logical pixel order, because each row is serialized with
  `ndarray.tobytes()` (C order of the logical row).

Dimensions, compression level and chunk layout are unchanged. This is an encoding
precondition for an already-derived array; it does not change camera, mesh,
colour normalization, masks or terrain admission.

## Tests and acceptance

`tests/gis/test_sc_png_dtype.py` (collected with the GIS stack, like the rest of
`tests/gis`) decodes every written PNG with an independent stdlib reader (chunk
lengths, `binascii` CRCs, IHDR fields, one complete zlib stream, filter bytes, exact
row length) and compares the pixels with RGB bytes computed in pure Python. Baseline
identities for an all-zero and a bounded patterned image are frozen in
`tests/fixtures/sc_png_dtype/baseline.json`, produced by the unpatched base
`write_png`. The raw-scanline hashes and the exact stdlib re-encoding are always
asserted; the full-file hash is asserted when the zlib runtime matches the one
recorded in the fixture.

The negative control replaces `write_png` with a test-local copy of the base
function (shape check only). Given in-range `uint16` input it writes 16-bit sample
bytes under an 8-bit header, and the independent contract check fails with
`SC-PNG-DTYPE-CONTRACT: scanline bytes ...`, while the `uint8` control stays green.

`research/scripts/accept_sc_png_dtype.py --suite focused|contract|negative --output DIR`
runs these through the installed pytest API and writes a new receipt directory per
run. A missing NumPy, pytest or GIS package is reported as `INPUT_UNAVAILABLE`
(exit 3), never as a skip or a pass. A local pass is scoped evidence that still needs
review; the full suite and exact-head CI remain required.
