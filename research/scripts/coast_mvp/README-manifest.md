# W11A — local C2 / rights → viewer manifest

`coast_manifest.py` is an offline export adapter, not a terrain engine, source
acquirer, viewer integration or publication gate. It writes **only** a new
`viewer-manifest.json` beside existing C2 assets. Existing output is refused.
W11B owns viewer wiring and any opt-in browser path; the viewer is unchanged.

From the repository root with the test/survey dependencies installed:

```sh
python -m research.scripts.coast_mvp.coast_manifest \
  --c2-dir LOCAL_C2_DIRECTORY --c1-manifest LOCAL_NATIVE_C1.json \
  --rights-manifest LOCAL_C5.json --region 'Local research preview' --synthetic
node research/scripts/coast_mvp/check_manifest.mjs LOCAL_C2_DIRECTORY/viewer-manifest.json
python -m pytest research/tests/test_coast_mvp_manifest.py research/tests/gis/test_coast_manifest_adapter.py research/tests/test_coast_mvp_contours.py research/tests/test_coast_mvp_rights.py tests/contract/test_test_layout.py -q
```

Choose `--synthetic` or `--measured` explicitly. A declared fixture cannot be
relabeled measured. Neither option clears rights, accepts science, reconciles
datums or authorizes serving the assets publicly. Synthetic exports retain the
viewer's synthetic banner; measured exports get its unreviewed-preview banner.

The native C1 contract is the one validated by `coast_c1_preview`: metres,
positive-up elevation, final contributor counts and source metadata. The C5
contract is documented in `README-rights.md`. Every positive C1 contributor,
including a terrain-only contributor with no contour features, must have a
matching C5 ID, hash, count, citation, licence and attribution. Missing rights
fail before output. Unused C5 rows are excluded. Hashes, terms evidence, native
resolution, datum and offset caveat are carried into the export. Source file
paths are not exported. CSUMB detection retains its existing explicit hold.
All sources set `permissionRequired: true`: these contracts contain **no**
independently accepted legal-clearance decision, even for CC0/public-domain text.

C2's original relative terrain/vector templates are the only admitted asset
paths. Numeric XYZ files must stay below that directory without symlink hops;
bounds are derived from its rectangular terrain coverage (maximum 64 tiles).
Vector tiles may be sparse but cannot fall outside the terrain coverage.
Contour coordinates must be finite and within bounds; feet/metres and source
labels/resolutions must agree. Geometry, holes, clip boundaries and tile bytes
are never rewritten. GIS fixtures exercise gradient/hole, closed bowl and
bowl/contributor-boundary outputs, alongside the existing topology tests.

`provenance` records exact input JSON, GeoJSON and tile SHA-256 values. These pin
the **supplied** declarations and assets, not proof of source acquisition,
correct contributor counts or a cryptographic C1→C2 production chain. The C2
producer does not currently record that chain. Original source bytes are not
reread. Fixture hashes/counts are synthetic and are not receipts. The node
checker calls the existing viewer validator and relative-path guard; it does
not run a map or attest visual, semantic, scientific or publication acceptance.
No network request or live-site change is performed by this adapter/checker.
