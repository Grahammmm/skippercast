# Opt-in canonical occupied exclusion for original interpreted bedrock

`canonical-occupied-subtraction-v1` is an explicit audited-vector policy option
in `vector_review.projection_exclusion_method`. Absent the option, the existing
strict any-positive-overlap hold remains unchanged. It does not activate a
source or authorize publication.

The physical kernel first intersects original valid geology with measured
nominal-depth pixels, assembles connected components, and subtracts qualified
occupied geometry in the depth CRS. Reprojection into canonical EPSG:3310 can
reintroduce a narrow numerical overlap at an existing boundary. The opt-in
subtracts the exact authenticated graded baseline and preceding classified
inventory once again in that same
canonical CRS. It never tolerates retained overlap or expands the source shape.

Both input geometries and the original projection must already be valid.
Invalid originals, invalid geographic representations, empty results and
component splits remain held. Discarded area must fit the existing reviewed
`MAX_FEATURE_DIFFERENCE_M2` representation-fidelity bound; this is a removal
budget, not a survey-accuracy statement or a permissible overlap. Larger real
conflicts remain held. The resulting geometry must have exactly zero positive
intersection with preceding canonical inventory and zero area outside its
initial canonical projection. No snapping, buffer, epsilon or repair is used. These exact-zero statements
apply to canonical EPSG:3310 only. WGS84 transport and MVT display are separately
bounded representations and can have small numerical differences; they are not
new source or navigation geometry.

After clipping, nominal-depth support is conservatively recounted by inverse
projection intersected with the original native component. Neither original
depth/source files nor earlier habitat geometry is modified. Audit properties
record the version, initial overlap, removed area, added area and remaining
intersection. These are geometry operations, not new survey measurements.

Tests include unchanged disjoint/boundary-touching geometry, a positive thin
intersection that is removed, material and full overlap holds, invalid source
and occupied polygons, and failed geographic projection. A retained private
real-window replay supplements synthetic tests. Source activation still needs
independent review, complete-stage prior preservation, current source rights and
whole-polygon restrictions, and full public archive readback. Unranked bedrock
interpretations remain nonexportable and receive no new-sonar or terrain-rank
credit.
