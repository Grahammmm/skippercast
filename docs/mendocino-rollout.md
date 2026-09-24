# Fort Bragg–Point Arena rollout ledger

This is a **draft**, not a fishing-spot release. The proposed local package covers the outer coast from 39°27′ N to the CDFW Point Arena management line at 38°57.5′ N. Its bounds are a discovery envelope, not a legal boundary or a recommendation to fish every included position.

## Verified source bindings

| Need | Official source and verified use | Limit before publication |
| --- | --- | --- |
| Recreational jurisdiction | [CDFW Mendocino region](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Mendocino), updated August 10, 2026; [CDFW groundfish summary](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary) | This is a different groundfish area from both Northern and San Francisco. The page is a summary; active species, gear, in-season changes and source fingerprints need a separate hash-bound review. |
| MPAs | [CDFW Russian Gulch](https://wildlife.ca.gov/Conservation/Marine/MPAs/Russian-Gulch) and [Point Arena / Sea Lion Cove](https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Arena-Sea-Lion-Cove); current statewide CDFW complete polygons | Some SMCAs permit limited take, but the app's target and export screen conservatively excludes the complete MPA polygons. Check all other local MPAs, plus exact boundary and date, before target publication. |
| Harbor | [Noyo Harbor District](https://noyoharbordistrict.org/) | A general harbor page is not live entrance clearance. Obtain current bar and entrance information separately. |
| Tide | [NOAA Noyo Harbor station 9417426](https://tidesandcurrents.noaa.gov/stationhome.html?id=9417426) | NOAA continues to list tide predictions, but the observing station was removed in 2011. It cannot supply a current water-level observation, entrance current or bottom drift. |
| Wind and wave observation | [NDBC 46014 Point Arena](https://www.ndbc.noaa.gov/station_page.php?station=46014), at 39.225° N, 123.980° W | Offshore reference, not a Noyo Harbor entrance sensor. Match each forecast to its own location and hour. |
| Marine forecast | [NWS PZZ455](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ455) nearshore and [PZZ475](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ475) offshore | Zone text is a regional warning/context layer; retain individual-model and local-grid forecasts separately. |
| Seabed | NOAA H11967 original variable-resolution BAG, its [descriptive report](https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11967/DR/H11967.pdf), NOAA NBS test tile BH42R5DS and original USGS C210NC camera observations | The [original-grid reconciliation](../dist/data/h11967-nbs-original-camera-reconciliation.json) found only 18 historical rocky-camera windows passing both local NBS and original BAG cell screens in the sampled tile. They are correlated research windows, not 18 reefs. H11967 remains held because the report describes charted hazards and uncertain least-depth areas. Reconcile current ENC, substrate footprint, route and legal exclusions before a fishing point. |

CDFW's current Mendocino page says the Fort Bragg ocean salmon fishery is closed for the remainder of 2026 and Dungeness crab closed July 31 with a scheduled November 7 reopening. These are dated source observations, **not approved live rule cards**; the in-season change, whale-safe gear and health notices still require trip-date checks. Pacific halibut north of Point Arena has a distinct quota and gear rule. Do not inherit a nearby region's card or treat a predicted opening as confirmed.

## Publication gate

1. Add a Mendocino jurisdiction manifest and collect the exact CDFW/eCFR sources. Read the legal text and apply a hash-bound decision for every offered species and local access dependency.
2. Qualify exact original bathymetry and substrate footprints, inspect original descriptive-report hazards, reconcile current ENC, and screen full current MPA and other closure geometry. The H11967 hold is enforced by the target compiler.
3. Confirm actual local forecast grids, buoy age, tide-prediction product and harbor access. Only then change the draft to preview, run region validation and the shared build, and verify mobile, exports and missing-data states.
4. Promote individual surveyed areas only after their full footprint passes the depth, uncertainty, habitat, rights, legal and route gates. A source count or a nearby camera observation is insufficient.
