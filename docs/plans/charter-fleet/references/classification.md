# Activity classification: rules, thresholds and sources

Charter-fleet N5 (issue #570, graph node N5, design § 11). This page records
the modes the classifier assigns (`src/skippercast/fleet/ais/classify.py`), the
thresholds they read (`regions/<id>/fleet.json` `thresholds.activity`) and the
public sources behind each number. Every output is inferred from movement
(D10), never a confirmed catch. The values are starting points that the
labelled validation set (N7) tunes. Any change to them changes
`classifier_version`, and that forces a reprocess.

## Measures

For each fix, over a centred 20-minute window (`window_min`) that never
crosses a silence over `gap_unknown_min`:

- **mean SOG**: the reported speed over ground, else the speed derived from
  the previous usable fix;
- **straightness**: net displacement divided by path length;
- **heading variance**: 1 − the mean resultant length of COG;
- **offshore distance**: the great-circle distance to the nearest port
  geofence in `fleet.json` (`segment.offshore_nm`).

*Offshore distance choice.* The port geofences are the only coastline that
every fleet region carries in the repository and that works offline in tests.
The committed NOAA CUSP shoreline covers Morro Bay only. Distance to a geofence
overstates distance to shore along a coast far from any port, so a slow coastal
run 5 nm or more from every harbor can read as offshore. N7's labels measure
this effect. A committed shoreline per region would replace the geofences
without any change to a threshold.

## Modes

The modes are listed in precedence order. Kinds are written exactly as stored.

| Mode | Rule (CA values) | Fishing |
| --- | --- | --- |
| `in-port` | inside a port geofence | no |
| `drift-anchor` | mean SOG ≤ `drift.max_sog_kn` (2.0) | yes |
| `troll-slow` | `troll_slow` band 2.2–3.5 kn and (straightness ≤ 0.9 or heading variance ≥ 0.05) | yes |
| `troll-pelagic` | `troll_pelagic` band 5–9 kn at ≥ `offshore_min_nm` (5 nm), straight or not | yes |
| `transit` | SOG > 9 kn, or > 3.5 kn with straightness ≥ `transit.min_straightness` (0.8) | no |
| `uncertain` | anything else | no |
| `gap` | a silence over `gap_unknown_min` (30 min) | not scored |

A fix becomes `uncertain` when its speed falls between bands (2.0–2.2 kn, or
3.5–5 kn while turning), when it is in the slow band without a troll's shape,
when it turns at pelagic speed inshore, or when it has no speed. A fishing run
shorter than its minimum also becomes `uncertain` (too short to decide). An
`uncertain` run is not fishing and never feeds an aggregate. It keeps its
geometry so that the owner's labelling view (N7) can show it.

No rule reads the time of day. A night drift offshore meets the drift rule,
so it is `drift-anchor`.

## Run rules

1. Consecutive fixes with equal labels form runs. A run shorter than
   `min_segment_minutes` (5) merges into its longer neighbour.
2. **Paddy stops.** Some runs lie between two `troll-pelagic` runs that each
   last at least `window_min`. If those in-between runs last
   `troll_pelagic.stop_max_minutes` (30) or less in total, and every fix in
   them is offshore, they join the pelagic run. Only `drift-anchor`, `uncertain` and
   `troll-slow` runs bridge; a `transit` sprint of a full window or more between two pelagic runs
   stays transit (a shorter transit run is only the window blending a fast
   run into the stop). A stop to fish a kelp paddy
   therefore does not split a pelagic search. The bound is 30 minutes because
   the centred window spreads a 15-minute stop across about 23 minutes of
   labels. The pelagic runs on each side must last a full window, so a fast
   run that blends into a drift cannot pull the drift in.
3. **Sustain.** A run shorter than its minimum becomes `uncertain`:
   `drift.min_minutes` (15), `troll_slow.min_minutes` (15) and
   `troll_pelagic.min_minutes` (30). Short runs then merge again.
4. Gaps never merge.

## Transit as statistics only

Owner decision #469 D20 drops transit from every view. A `transit` segment
keeps its minutes, point count, mean and p90 SOG, and distance
(`fleet_segments.p90_sog`, `distance_nm`), and its geometry is null. Trip
totals are unchanged.

## Why these numbers

- **Drift ≤ 2 kn.** A drifting or anchored boat moves only with wind and
  current. AIS studies of fishing effort find that speed alone separates
  fishing from steaming: active fishing forms a low-speed mode, distinct from
  a transit mode near cruising speed (Natale et al. 2015; de Souza et al.
  2016). The 2 kn bound is unchanged from CF-43.
- **Slow troll 2.2–3.5 kn.** Salmon trollers generally run at 1 to 4 knots,
  depending on the species (California Legislature, Joint Committee on
  Fisheries and Aquaculture, CACSST appendices, 2008). The band starts above
  the drift bound and sits around 2.5 kn. The band is meant to need a troll's
  turning shape, because a straight 3 kn run could be a slow passage. The
  `troll_slow.min_heading_variance` of 0.05 is only a starting threshold,
  and with the straightness test alongside it is permissive: real COG noise
  at 3 kn may exceed 0.05, so a straight slow passage could still read
  `troll-slow`. The synthetic test uses noise-free COG. N7 must check this
  against real tracks.
- **Pelagic troll 5–9 kn offshore.** NOAA describes the WA/OR/CA albacore
  troll fishery as pulling lines through surface water at 4–8 kn. UCSB's
  Discover West Coast Seafood describes the same troll at 3–6 mph. The band
  covers the faster part of that range (its 9 kn top is above both sources'
  tops, NOAA's 8 kn and UCSB's about 5.2 kn, and is a starting point for N7), where a charter boat searches for
  tuna, yellowtail or dorado, and tops out below a charter boat's usual
  cruise. Offshore, these searches run straight, so straightness is not
  required. Inshore, a straight run at the same speed is `transit`, and a
  turning one is `uncertain`. Owner decision #469 D22 counts offshore pelagic
  trolling as fishing.
- **Known gap, 3.5–5 kn offshore.** A straight albacore troll at 4 kn
  offshore sits inside NOAA's 4–8 kn range but below the pelagic band, and
  above the slow band, so it is currently `transit` and not fishing. N7
  should tune this.
- **`offshore_min_nm` 5.** Albacore and the warm-water pelagics on the
  California coast are targeted offshore. 5 nm from the nearest harbor keeps
  routine coastal runs between neighbouring ports inshore. N7 tunes it.
- **Window and run minimums.** The 20-minute window and the 15-minute
  sustain rule come from CF-43. Pelagic needs 30 minutes because a passing
  boat at trolling speed is the main false positive.

## Sources (public)

- NOAA Fisheries, *WA/OR/CA Albacore Surface Hook and Line/Troll Fishery: MMPA
  List of Fisheries*.
  <https://www.fisheries.noaa.gov/marine-mammal-protection/wa-or-ca-albacore-surface-hook-and-line-troll-fishery-mmpa-list-fisheries>
- NOAA Fisheries, *High Seas South Pacific Albacore Troll Fisheries: MMPA List
  of Fisheries* (trolling at about 5–6 kn).
  <https://www.fisheries.noaa.gov/national/marine-mammal-protection/high-seas-south-pacific-albacore-troll-fisheries-mmpa-list>
- UC Santa Barbara, Discover West Coast Seafood, *Troll*.
  <https://discoverwcseafood.msi.ucsb.edu/how-its-harvested/wild-caught/troll>
- California Legislature, Joint Committee on Fisheries and Aquaculture,
  *CACSST Appendices to An Epic of Good Intentions* (2008), salmon troll
  speeds.
  <https://fisheries.legislature.ca.gov/sites/fisheries.legislature.ca.gov/files/u8/CACSST-Appendices_to_An_Epic_Of_Good_Intentions_2008.pdf>
- Natale, F., Gibin, M., Alessandrini, A., Vespe, M. and Paulrud, A. (2015).
  Mapping fishing effort through AIS data. *PLOS ONE* 10(6): e0130746.
- de Souza, E. N., Boerder, K., Matwin, S. and Worm, B. (2016). Improving
  fishing pattern detection from satellite AIS using data mining and machine
  learning. *PLOS ONE* 11(7): e0158248.
