> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/MAP-VISUAL-REVIEW.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Coast map visual review

For map rendering and regional rollout changes, include a subagent walkthrough before publishing. Use a separate browser tab and coordinate viewport ownership. Save short findings and representative before/after images with the release evidence. This is a visual review, not a navigation or depth certification.

## Representative views

- Morro harbor: channels, sand spit, Morro Rock; close and wide zoom.
- Monterey / Carmel and Point Sur / Big Sur: canyon slopes, exposed coast and survey gaps.
- Cambria and Avila: shoreline, imagery edges and reef selections.
- Arguello / Conception: southern coverage and imagery gaps.
- Check both2D and3D, desktop and one phone viewport. Zoom through detail changes; pan across tile borders. Inspect water on/off, relief, habitat pins and source coverage when diagnosing a defect.

## Look for

- Cracks, deep curtains, overlapping tiles, mismatched corners and detail loading flashes.
- Repeated coarse elevation blocks, source transitions, jagged water clipping and contour stripes.
- Image rectangles, transparent/black pixels, missing fallback and excessive blur at supported detail.
- Cluttered pins, hidden controls, selection changes between perspectives, report geography drift and console errors.

## Repair rules

Keep measurements, masks, dates and source identity intact. Display blending does not create finer measurements, current fish positions or navigation soundings. Correct the renderer before changing original datasets. Preserve original source readouts and habitat/ranking inputs. Verify important joins with actual numeric assets as well as screenshots.

Where the source is absent or coarse, keep the gap or context label visible and record the specific future data need. Do not cover a genuine gap with invented depths or photography. Record what improved and what remains; do not claim every part of the coast was inspected from a representative walkthrough.
