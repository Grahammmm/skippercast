# SkipperCast map inspiration (X research, 2026-11-19)

Page: https://cursor.com/canvas/store-0c376c2f-e405-4dea-a9cb-a3cbd0b9a208/7eef1e20-0348-4d90-aa88-24beb1bcb358

## SkipperCast (public)

- Repo: https://github.com/Grahammmm/skippercast · Site: https://skippercast.com
- Phone-first fishing map and ocean forecast for boat anglers on California's Central Coast (v0.8; Morro Bay & Avila active, 15 preview regions). MapLibre GL + PMTiles over a self-hosted Protomaps basemap (Night/Day), ENC chart, 2D/3D terrain via Three.
- Note: The phrases 'subsea weather' and 'raw general base layer map' do not appear in the public repo; mapped here to the closest layers (currents/water temp; basemap + ENC + seafloor). Source: README.md, docs/web-app.md, docs/plans/front-end/design.md §9, web/tokens.css.

## Replicate first (top 5)

1. **Open Waters Seascape: global seafloor chart tiles** (@berttemme) → Raw base map + depth contours: Adopt or mimic the Open Waters Seascape stack: Terrarium raster-dem relief + hillshade + MVT contours/soundings in MapLibre (same stack SkipperCast already uses). Try ?shading=bands for an ENC look and ?unit=ft. [post](https://x.com/berttemme/status/2122834956829458858)
2. **earth.nullschool ocean currents** (@cambecc) → Currents (subsea weather): Upgrade the existing canvas streamlines to fading particle trails over a speed-coloured field (cmocean speed), keeping --flow #dffcf6 for the trails. [post](https://x.com/cambecc/status/428915614501986304)
3. **NOAA S-102 gridded bathymetry, web-rendered** (@chris_dalke) → Seafloor / base: Strong hillshade on the highest-res grid (S-102/BlueTopo) with a 7-stop cyan-to-navy ramp on sqrt(depth) (rsimmon tip); flat land. [post](https://x.com/chris_dalke/status/2121710455756296521)
4. **earth.nullschool ocean waves** (@cambecc) → Sea conditions (swell): Animate swell direction strokes at a speed tied to period; keep the 0–15 ft field; add a glow for the top band on Night. [post](https://x.com/cambecc/status/552117215483289600)
5. **Monterey Bay drained (rayshader + rayrender)** (@tylermorganwall) → 3D terrain view: Rayshader-style 'drained' Monterey/Morro Bay preset: soft shadows, ambient occlusion, translucent water plane at 0 m in the Three scene. [post](https://x.com/tylermorganwall/status/1329428971843366914)

## Per-layer references

| Layer | SkipperCast today | Top reference(s) | Copy | Colormap |
|---|---|---|---|---|
| Raw base map / nautical chart base | Protomaps basemap (Night/Day), ENC chart raster z>=10, coastline glow | @berttemme https://x.com/berttemme/status/2122834956829458858, @chris_dalke https://x.com/chris_dalke/status/2112187736354615745, @chris_dalke https://x.com/chris_dalke/status/2121710455756296521 | Seascape-style depth relief + contours + soundings under the ENC; land relief under chart colours; keep land flat when the water is the subject | deep (reversed) or ColorBrewer Blues on sqrt(depth) |
| Bathymetry / seafloor 3D | Terrain relief 2D/3D (Three), seafloor candidates, depth contours every 30 ft | @tylermorganwall https://x.com/tylermorganwall/status/1329428971843366914, @researchremora https://x.com/researchremora/status/1722674175922307456, @John_M_Nelson https://x.com/John_M_Nelson/status/1977768379080483230 | Raytraced soft shadows, translucent water plane, shadowed contour bands, sqrt depth scaling | deep, topo |
| Currents / flow (subsea weather) | Canvas streamlines (WCOFS, HF radar), --flow #dffcf6 | @cambecc https://x.com/cambecc/status/428915614501986304 | Fading particle trails over a speed-coloured field; dark land; trails clipped by land mask | speed or tempo |
| Sea surface temperature | Water temp field, 0.5 °F contours, contrast cells | @CopernicusEU https://x.com/CopernicusEU/status/1778755407864803561, @NASAEarth https://x.com/NASAEarth/status/1839719154074386743 | Make fronts and eddies the subject; perceptual ramp; storm track overlay | thermal; balance for anomaly |
| Waves / swell (sea conditions) | Swell field 0–15 ft, dashed period isolines, direction strokes | @cambecc https://x.com/cambecc/status/552117215483289600, @robhawkes https://x.com/robhawkes/status/1429454366688350209 | Animate direction strokes at period speed; glow for high seas on Night | dense or amp |
| Wind / weather over ocean | Wind arrows, clouds raster, marine alerts | @hansakwast https://x.com/hansakwast/status/1812934083019960771, @NASAEarth https://x.com/NASAEarth/status/1839719154074386743 | White streak traces on dark base instead of arrows; storm track + time labels | speed for magnitude |
| Chlorophyll / ocean colour | Chlorophyll layer in draw order (daily feed) | @VittorioBrando https://x.com/VittorioBrando/status/1515320217689333766, @maptheclouds https://x.com/maptheclouds/status/1688459964166139904 | Log-scale green ramp over black/dark base; monthly loop | algae |
| Tides | Tide curve/sparkline (Port San Luis), tide tiles | @bryancsk https://x.com/bryancsk/status/1486633527298834435 | Amplitude fill + white co-phase lines; Windy-style tidal current particles | tempo or haline for amplitude |
| Salinity | Not in repo | @NASAEarthData https://x.com/NASAEarthData/status/1838320659593650177 | Haline ramp + running date stamp | haline |
| Sea ice | Not relevant to Central Coast | @CMEMS_EU https://x.com/CMEMS_EU/status/1829436415735730368 | Ice ramp on near-black | ice |
| Subsurface temperature / thermocline | Not in repo (Graham's 'subsea weather' may cover it) | — | No strong X example found; Copernicus Marine and PO.DAAC publish the data. Gap. | thermal + depth slider |

## Ranked examples

### 1. Open Waters Seascape: global seafloor chart tiles — @berttemme
- Post: https://x.com/berttemme/status/2122834956829458858
- Links: https://openwaters.io/charts/seascape/, https://github.com/openwatersio/seascape, https://tiles.openwaters.io/seascape/style.json
- Image: [berttemme_2122834956829458858_0.jpg](images/berttemme_2122834956829458858_0.jpg)
- Layers: bathymetry, nautical chart base, raw base map
- Why: Ocean-first map: continuous depth shading, hillshade, contours and spot soundings from a 34-source mosaic (GEBCO, EMODnet, NOAA S-102, CUDEM). Islands read as sculpted relief rising from smooth blue gradients. Served as MapLibre tiles.
- Palette: #1d4a7d #1f5187 #2b5d91 #386593 #527ba3 #9ab0b3 (Monochrome blue depth ramp (light shallow to dark deep); README offers ?shading=relief|bands (ENC depth-area bands))
- Layering: OSM raster base (optional) > raster-dem colour relief > hillshade > depare depth areas > contour lines > soundings and labels
- Typography: Contour and sounding labels from vector tiles; units switch via ?unit=m|ft|fm
- Density: Medium: dense contours at zoom, soundings only at high zoom
- Motion: Static
- Lighting: Raster-DEM hillshade on Terrarium-encoded depth; optional 3D via map.setTerrain
- Tools: MapLibre GL raster-dem (encoding: terrarium) + MVT vectors (depare, contours, soundings); build pipeline BSD-3; tiles CC BY 4.0
- SkipperCast: Raw base layer: drop-in or reference for SkipperCast's seafloor/depth contours; the ?safety= hazard shading and fathom/feet ladders match boat use

### 2. NOAA S-102 gridded bathymetry, web-rendered — @chris_dalke
- Post: https://x.com/chris_dalke/status/2121710455756296521
- Links: https://zydromarine.com
- Image: [chris_dalke_2121710455756296521_0.jpg](images/chris_dalke_2121710455756296521_0.jpg)
- Layers: bathymetry, nautical chart base
- Why: High-resolution S-102 grid shaded with a soft cyan-to-navy ramp; channels, sand waves and shoals read like a photograph of the seabed. Land is flat green so the water carries the detail.
- Palette: #7cc0e0 #66b2d6 #3d8fc5 #287ab8 #1f6bac #16589c #0b3a79 (Cyan to navy sequential (close to a Blues ramp), shallow = light)
- Layering: Flat land fill > depth colour > hillshade multiply
- Typography: Minimal; no labels in shot
- Density: High detail, low clutter
- Motion: Static
- Lighting: Strong seafloor hillshade on high-res grid
- Tools: Author's own map stack (renderer not named in this post; he builds ocean map infra at Zydro); data NOAA S-102
- SkipperCast: Raw base layer and seafloor: the same look for Central Coast where S-102/BlueTopo grids exist

### 3. Nautical charts × elevation — @chris_dalke
- Post: https://x.com/chris_dalke/status/2112187736354615745
- Links: https://zydromarine.com
- Image: [chris_dalke_2112187736354615745_0.jpg](images/chris_dalke_2112187736354615745_0.jpg)
- Layers: nautical chart base, bathymetry, land relief
- Why: ENC-style chart (pale water, blue shallow bands, depth contours) merged with land relief, so the chart reads as terrain, not paper.
- Palette: #ecf5f7 #d4e9ee #c8dde4 #9bbca6 #75a167 #75a871 (ENC-like: pale water, blue shoal band, green land)
- Layering: Land relief > water fill > shoal band > contour lines
- Typography: Chart-style sans labels
- Density: Medium
- Motion: Video demo (pan/zoom)
- Lighting: Land hillshade under ENC colours
- Tools: Custom WebGL renderer; ENC + elevation
- SkipperCast: Base map day variant: put relief under the ENC chart layer instead of a flat raster

### 4. Monterey Bay drained (rayshader + rayrender) — @tylermorganwall
- Post: https://x.com/tylermorganwall/status/1329428971843366914
- Links: https://github.com/tylermorganwall/rayshader, https://github.com/tylermorganwall/rayrender, https://www.rayshader.com
- Image: [tylermorganwall_1329428971843366914_0.jpg](images/tylermorganwall_1329428971843366914_0.jpg)
- Layers: bathymetry, 3D seafloor
- Why: Path-traced 3D of Monterey Canyon (SkipperCast's coast) with the water removed: soft sand tones and raytraced shadows make the canyon walls read instantly.
- Palette: #ecdcc5 #d9c8b4 #c1b3a5 #af9b88 #937f72 (Monochrome sand/beige)
- Layering: DEM mesh > raytraced shading; no overlays
- Typography: None
- Density: Low clutter, one subject
- Motion: Video fly-through
- Lighting: Path-traced soft shadows
- Tools: R: rayshader (sphere_shade, ray_shade, plot_3d) + rayrender
- SkipperCast: 3D terrain view: 'drained ocean' preset for the Seafloor 3D presentation; hero image for landing

### 5. Black Sea bathymetry in 3D — @tylermorganwall
- Post: https://x.com/tylermorganwall/status/1515122509775048715
- Links: https://github.com/tylermorganwall/rayshader
- Image: [tylermorganwall_1515122509775048715_0.jpg](images/tylermorganwall_1515122509775048715_0.jpg)
- Layers: bathymetry, 3D seafloor
- Why: Block-diagram map with translucent blue water over a deep basin; land is green-shaded relief. Reads as a physical object.
- Palette: #396c86 #606c51 #6f7b58 #4d5f52 #869a97 (Blue water over green/olive relief)
- Layering: Relief mesh > transparent water plane > base slab
- Typography: Small title strip
- Density: Low
- Motion: Companion video (1515158357879013382) with realtime fly-through
- Lighting: Raytraced shadows, translucent water
- Tools: rayshader render_water + render_highquality
- SkipperCast: 3D view: translucent water plane at 0 m over the bathymetry mesh

### 6. Beneath the Atlantic: hexagon bathymetry — @researchremora
- Post: https://x.com/researchremora/status/1722674175922307456
- Links: https://github.com/tylermorganwall/rayshader
- Image: [researchremora_1722674175922307456_0.jpg](images/researchremora_1722674175922307456_0.jpg)
- Layers: bathymetry
- Why: Most-liked bathymetry render found (627 likes). Lavender-blue depth with cream shelves, extruded hexagons and soft shadows; poster typography.
- Palette: #fff9c2 #fbf2c2 #efe7c1 #dad4c1 #bebdbf #99a2c0 #8192bf (Cream (shallow) to lavender-blue (deep))
- Layering: Hex-binned depth > extrusion > raytraced shadow > title
- Typography: Spaced serif caps title (BENEATH THE / ATLANTIC OCEAN)
- Density: Medium (hex grid)
- Motion: Static
- Lighting: rayshader high-quality render, low sun
- Tools: R: rayshader (data source not stated in post)
- SkipperCast: Landing/hero art and a 'poster' export style; the cream-to-lavender ramp suits the Night theme

### 7. earth.nullschool ocean currents — @cambecc
- Post: https://x.com/cambecc/status/428915614501986304
- Links: https://earth.nullschool.net/#current/ocean/surface/currents/orthographic, https://github.com/cambecc/earth
- Image: [cambecc_428915614501986304_0.png](images/cambecc_428915614501986304_0.png)
- Layers: currents
- Why: The reference for animated flow: thousands of fading particle trails over a speed-coloured field on a dark globe. The Gulf Stream pops in green/yellow.
- Palette: #282d51 #2b3162 #303884 #3d5075 #648e75 #303030 (Speed ramp dark navy > teal > green > yellow over #303030 land)
- Layering: Dark land > speed colour overlay > animated particle trails > coastlines
- Typography: Tiny monospace HUD ('earth' menu)
- Density: High particle density, no labels
- Motion: Particle advection with fading trails
- Lighting: None (flat)
- Tools: D3 + canvas particles (open-source 'earth' repo); OSCAR currents
- SkipperCast: Currents: SkipperCast already draws canvas streamlines; add fading trails and a speed colour field under them

### 8. earth.nullschool ocean waves — @cambecc
- Post: https://x.com/cambecc/status/552117215483289600
- Links: https://earth.nullschool.net/#current/ocean/primary/waves/overlay=significant_wave_height/orthographic, https://github.com/cambecc/earth
- Image: [cambecc_552117215483289600_0.png](images/cambecc_552117215483289600_0.png)
- Layers: waves/swell
- Why: Significant wave height as colour with a separate wave-period animation type, so height and direction read together.
- Palette: #272829 #303235 #33576e #506d76 #74877e #4f5869 (Muted blue-grey low > red/yellow high (storm core))
- Layering: Land > SWH overlay > animated wave-direction particles
- Typography: Minimal HUD
- Density: High
- Motion: Animated particles keyed to peak wave period
- Lighting: None
- Tools: earth (open-source, canvas animation)
- SkipperCast: Swell: animate the direction strokes at period speed over the 0–15 ft field

### 9. Trippy contour maps of the ocean floor — @John_M_Nelson
- Post: https://x.com/John_M_Nelson/status/1977768379080483230
- Links: https://www.youtube.com/watch?v=FVwIba9Ko-k, https://www.esri.com/arcgis-blog/products/arcgis-pro/mapping/how-to-make-this-seafloor-map/
- Image: [John_M_Nelson_1977768379080483230_0.jpg](images/John_M_Nelson_1977768379080483230_0.jpg)
- Layers: bathymetry
- Why: Stacked, shadowed contour bands in teal-to-lime make the seafloor look terraced and tactile.
- Palette: #051844 #0a4160 #047488 #149b93 #23b19b #5ac37e #b6e78c (Navy > teal > lime (close to cmocean deep reversed))
- Layering: Banded depth fill > per-band drop shadow > highlight edge
- Typography: None
- Density: Medium
- Motion: Static (how-to video)
- Lighting: Drop shadows per contour band (illuminated contours)
- Tools: ArcGIS Pro; Esri how-to blog for his seafloor map (blog returns 403 to automated checks)
- SkipperCast: Depth contours: shadowed 'terraced' contours as an optional style for the 30 ft contour layer

### 10. Chlorophyll globe (Three.js) — @maptheclouds
- Post: https://x.com/maptheclouds/status/1688459964166139904
- Links: https://maptheclouds.com/playground/threejs/chlorophyll/, https://neo.gsfc.nasa.gov/view.php?datasetId=MY1DMM_CHLORA
- Image: [maptheclouds_1688459964166139904_0.jpg](images/maptheclouds_1688459964166139904_0.jpg)
- Layers: chlorophyll/ocean colour
- Why: 12 months of MODIS chlorophyll on an interactive globe; clean light page, black land so the bloom colours carry.
- Palette: #4b85a7 #dcd8d8 #e1dedf #eae8e9 (Blue-green chlorophyll ramp on white page (exact stops on the live page))
- Layering: Black land > chlorophyll texture > title/legend
- Typography: Centered sans title, month strip
- Density: Low clutter
- Motion: 12-month animation
- Lighting: None
- Tools: Three.js shaders; NASA NEO Aqua MODIS
- SkipperCast: Chlorophyll layer: log-scale ramp and monthly loop

### 11. Wet/shiny bathymetry on a historic map — @geo_spatialist
- Post: https://x.com/geo_spatialist/status/1293225065983680512
- Links: none beyond the post
- Image: [geo_spatialist_1293225065983680512_0.jpg](images/geo_spatialist_1293225065983680512_0.jpg)
- Layers: bathymetry
- Why: Bathymetry rendered with specular gloss so the water looks wet, under a historic topo map. Shows how lighting alone sells 'water'.
- Palette: #d4e2de #bbd1d0 #acc8ca #88aea2 #829872 #627351 (Muted sage/aqua)
- Layering: Scanned map texture draped on DEM > glossy water material
- Typography: Original map typography
- Density: Medium
- Motion: Static
- Lighting: Specular highlights on water surface
- Tools: Blender (b3d) + ArcGIS Pro (per author's other posts)
- SkipperCast: 3D terrain: low-roughness water material in the Three scene

### 12. SST off Japan (Copernicus Marine) — @CopernicusEU
- Post: https://x.com/CopernicusEU/status/1778755407864803561
- Links: https://marine.copernicus.eu/access-data
- Image: [CopernicusEU_1778755407864803561_0.jpg](images/CopernicusEU_1778755407864803561_0.jpg)
- Layers: sea surface temperature
- Why: Kuroshio eddies and fronts in a full-spectrum SST ramp over dark land; the fronts are what anglers look for.
- Palette: #2f213a #3b3c5a #496cc3 #ebc93b #e3742c #d13307 #99200f (Rainbow-like (purple > blue > yellow > red); swap for cmocean thermal)
- Layering: Dark land > SST field > coast > legend
- Typography: Legend top-left
- Density: High
- Motion: Static
- Lighting: None
- Tools: Copernicus Marine products
- SkipperCast: Water temp: show fronts (like SkipperCast's contrast cells); use a perceptual ramp

### 13. Hurricane Beryl wind mesh (QGIS) — @hansakwast
- Post: https://x.com/hansakwast/status/1812934083019960771
- Links: https://youtu.be/p4lRqgFUyx0, https://github.com/GispoCoding/GlobeBuilder
- Image: [hansakwast_1812934083019960771_0.jpg](images/hansakwast_1812934083019960771_0.jpg)
- Layers: wind/weather
- Why: White streamline 'brush' traces over a dark basemap; the hurricane eye pops. Time and height controllers animate it.
- Palette: #080c13 #0b111a #0d1826 #161f2b #193130 #eeeeee (White traces on near-black)
- Layering: Dark basemap > white wind traces
- Typography: None
- Density: High trace density
- Motion: Temporal + vertical controllers (time and level)
- Lighting: None
- Tools: QGIS 3.38 mesh layer (NetCDF from Copernicus ECMWF); video tutorial linked
- SkipperCast: Wind arrows: replace arrows with white streak traces on Night base

### 14. World tidal amplitude (GOT99.2 co-tidal chart) — @bryancsk
- Post: https://x.com/bryancsk/status/1486633527298834435
- Links: https://www.windy.com/articles/major-sea-currents-update-high-resolution-and-new-tidal-currents-15650
- Image: [bryancsk_1486633527298834435_0.png](images/bryancsk_1486633527298834435_0.png)
- Layers: tides
- Why: Classic NASA/GSFC GOT99.2 co-tidal chart: amplitude colours with white phase lines radiating from amphidromic points.
- Palette: #53557f #53a0ba #43b3b4 #81db74 #09ce75 #b0afac (Blue > green > yellow > red amplitude (cm))
- Layering: Grey land > amplitude fill > white co-phase lines
- Typography: Small axis labels, horizontal legend bar
- Density: Medium
- Motion: Static
- Lighting: None
- Tools: NASA/GSFC GOT99.2 tide model
- SkipperCast: Tides: a regional co-phase/amplitude overlay explains why tide timing differs along the coast

### 15. SMAP sea surface salinity animation — @NASAEarthData
- Post: https://x.com/NASAEarthData/status/1838320659593650177
- Links: https://podaac.jpl.nasa.gov/animations/Sea-Surface-Salinity-8-Day-Running-Mean-from-SMAP-RSS-V6.0-2015-2024
- Image: [NASAEarthData_1838320659593650177_0.jpg](images/NASAEarthData_1838320659593650177_0.jpg)
- Layers: salinity
- Why: Globe with a vivid salinity ramp, a vertical legend and running date stamp.
- Palette: #19183a #272b4b #333f68 #9ce469 #9f9671 (Blue > green > yellow > red (PSU); cmocean haline is the perceptual fix)
- Layering: Space background > globe > SSS texture > date + legend
- Typography: Rotated title, vertical colour bar
- Density: Medium
- Motion: 8-day running mean animation
- Lighting: Globe shading
- Tools: NASA PO.DAAC (RSS SMAP L3 V6)
- SkipperCast: Future salinity layer: haline ramp + date stamp

### 16. Arctic sea ice thickness (MyOcean viewer) — @CMEMS_EU
- Post: https://x.com/CMEMS_EU/status/1829436415735730368
- Links: https://myocean.marine.copernicus.eu, https://marine.copernicus.eu
- Image: [CMEMS_EU_1829436415735730368_0.jpg](images/CMEMS_EU_1829436415735730368_0.jpg)
- Layers: sea ice
- Why: Navy-to-ice-white ramp on a black ocean, thin coastlines; the ice reads cold and clean.
- Palette: #020411 #040613 #212121 #333946 #97c1cf (Matches cmocean ice (#040613 > #eafdfd))
- Layering: Dark base > ice thickness raster > coastlines > legend
- Typography: Small legend bar top-left, UTC time stamp
- Density: Low
- Motion: Month comparison
- Lighting: None
- Tools: Copernicus MyOcean Viewer
- SkipperCast: Not a Central Coast layer; shows the ice ramp to reuse for any 'cold' layer

### 17. Sentinel-3 OLCI chlorophyll at 300 m — @VittorioBrando
- Post: https://x.com/VittorioBrando/status/1515320217689333766
- Links: https://marine.copernicus.eu
- Image: [VittorioBrando_1515320217689333766_0.jpg](images/VittorioBrando_1515320217689333766_0.jpg)
- Layers: chlorophyll/ocean colour
- Why: Bloom filaments at 300 m with a green ramp on black; shows the fine structure SkipperCast's chlorophyll layer could show offshore.
- Palette: #020102 #151a19 #1e473d #247263 #208c6f #539f65 (Black > teal-green > yellow (like cmocean algae))
- Layering: Black background > chl raster > coast
- Typography: Viewer UI
- Density: High
- Motion: Static
- Lighting: None
- Tools: Copernicus Marine (Sentinel-3 OLCI)
- SkipperCast: Chlorophyll: 300 m OLCI over a Night base

### 18. Significant wave height shader (WeatherLayers) — @robhawkes
- Post: https://x.com/robhawkes/status/1429454366688350209
- Links: https://weatherlayers.com, https://github.com/weatherlayers/weatherlayers-gl
- Image: [robhawkes_1429454366688350209_0.jpg](images/robhawkes_1429454366688350209_0.jpg)
- Layers: waves/swell
- Why: Magenta wave heights glow on deep navy, a neon look that suits a dark UI.
- Palette: #000000 #000e3a #011a39 #021d39 #37007e (Navy > purple > magenta)
- Layering: Black base > SWH shader
- Typography: None
- Density: Low
- Motion: Animation planned (custom shader)
- Lighting: Glow
- Tools: Three.js shader via react-three-fiber; data via WeatherLayers
- SkipperCast: Swell: glow-style high-sea emphasis on Night theme

### 19. Square-root depth scaling tip — @rsimmon
- Post: https://x.com/rsimmon/status/423826706462289922
- Links: none beyond the post
- Image: [rsimmon_423826706462289922_0.png](images/rsimmon_423826706462289922_0.png)
- Layers: bathymetry
- Why: Shows the ex-NASA designer's trick: colour by sqrt(depth) with a ColorBrewer Blues ramp so shelves and slopes both get colour range.
- Palette: #d5e6f2 #98c4dd #7ab0d1 #5ba3d0 #477fa5 #343434 (ColorBrewer Blues on sqrt(depth))
- Layering: Dark land > sqrt-scaled depth fill
- Typography: None
- Density: Low
- Motion: Static
- Lighting: None
- Tools: Value transform before colour mapping
- SkipperCast: Depth colour: apply sqrt scaling to --depth-0..3 stops

### 20. Warm water fuelling Hurricane Helene — @NASAEarth
- Post: https://x.com/NASAEarth/status/1839719154074386743
- Links: none beyond the post
- Image: [NASAEarth_1839719154074386743_0.jpg](images/NASAEarth_1839719154074386743_0.jpg)
- Layers: weather over ocean, sea surface temperature
- Why: Storm track (dotted, time-labelled) over a deep-red SST field with grey land; storm and ocean on one map.
- Palette: #380e14 #520e1b #640b1f #930425 #e5e5e5 (Dark reds (like cmocean amp) for warm water)
- Layering: Grey land > SST field > track points > labels > legend
- Typography: Clean sans annotations, bottom legend
- Density: Low
- Motion: Static
- Lighting: None
- Tools: NASA Earth Observatory style
- SkipperCast: Weather: storm/alert track over the SST field

## More examples

- @giswqs: MapLibre tutorial: ocean bathymetry in 3D (notebook + demo) — https://x.com/giswqs/status/1813927403322020041 https://leafmap.org/maplibre/ocean_bathymetry/ https://maps.gishub.org/maplibre/ocean_bathymetry.html https://youtu.be/SLHwMbZox9o https://github.com/opengeos/leafmap
- @protomaps: MapLibre raster-DEM terrain + bathymetry from one 30 GB PMTiles file on R2 (SkipperCast's stack) — https://x.com/protomaps/status/1588061193130119168 https://pmtiles.io/examples/maplibre_raster_dem.html https://github.com/protomaps/PMTiles https://github.com/protomaps/basemaps
- @maptheclouds: GFS wind with GPU particles (mourner's WebGL Wind) — https://x.com/maptheclouds/status/2037952865113923667 https://maptheclouds.com/playground/30-day-map-challenge-2022/windy-sky/ https://github.com/mapbox/webgl-wind
- @maptheclouds: North-pole Arctic bathymetry (IBCAO) — https://x.com/maptheclouds/status/2042648807385505849 https://maptheclouds.com/playground/30-day-map-challenge-2023/arctic-ocean/
- @John_M_Nelson: Ocean currents in Spilhaus one-world-ocean projection (video) — https://x.com/John_M_Nelson/status/1886795687745994955 
- @John_M_Nelson: Tharp/Berann-style oblique seafloor — https://x.com/John_M_Nelson/status/1608466398547972097 
- @Windycom: Windy tidal currents layer launch — https://x.com/Windycom/status/1367063392612192259 https://www.windy.com/articles/major-sea-currents-update-high-resolution-and-new-tidal-currents-15650
- @Windycom: Typhoon Ragasa wind visual — https://x.com/Windycom/status/1970742543101943984 https://www.windy.com
- @CMEMS_EU: Hurricane Milton wind vectors (arrows over speed) — https://x.com/CMEMS_EU/status/1884881741619302744 https://marine.copernicus.eu
- @CopernicusEU: Significant wave height animation, California storm — https://x.com/CopernicusEU/status/1075714196153737216 
- @cambecc: SST palette tweak reveals sea ice — https://x.com/cambecc/status/1367052864867028994 https://earth.nullschool.net
- @jscarto: Hawaii with subtle bathymetry — https://x.com/jscarto/status/1238197191031828482 
- @jscarto: Baltic phytoplankton vortices (Landsat) — https://x.com/jscarto/status/1296258822894428160 https://earthobservatory.nasa.gov/images/147135/beguiling-bloom-in-the-baltic-sea
- @mnturkistani: Red Sea as a Victorian sounding chart (fathoms, hachures, compass rose) — https://x.com/mnturkistani/status/2118630303056990316 
- @marineregions: Inverted GEBCO colours with maritime boundaries — https://x.com/marineregions/status/2121917878660403314 https://www.marineregions.org
- @joewdavies: Europe topography + bathymetry in Blender — https://x.com/joewdavies/status/1423721771568619524 
- @chris_dalke: Custom WebGL 3D globe renderer (ECEF, LOD separate from XYZ tiles) — https://x.com/chris_dalke/status/2112649348467355860 
- @chris_dalke: Heavy hillshade + contour island — https://x.com/chris_dalke/status/2111566995842023743 
- @rsimmon: Berann/Heezen/Tharp Ocean Floor map (LoC hi-res) — https://x.com/rsimmon/status/1046533815487758336 https://www.loc.gov/item/2010586277/

## Who to follow

- @chris_dalke: Builds ocean map infra (Zydro); S-102, ENC + elevation, custom WebGL
- @tylermorganwall: rayshader/rayrender author; 3D bathymetry
- @researchremora: Most-liked rayshader bathymetry posters
- @cambecc: earth.nullschool: currents, waves, SST
- @John_M_Nelson: Seafloor styling how-tos, Spilhaus ocean maps
- @maptheclouds: Open WebGL/Three.js ocean and wind demos with live links
- @geo_spatialist: Blender 3D renders with bathymetry
- @hansakwast: QGIS mesh/temporal wind and ocean tutorials
- @giswqs: MapLibre/leafmap tutorials incl. 3D bathymetry
- @protomaps: PMTiles/MapLibre terrain (SkipperCast's stack)
- @rsimmon: Colour/palette craft for Earth data
- @jscarto: Ex-NASA Earth Observatory cartography
- @Windycom: Benchmark consumer marine layers
- @CMEMS_EU: Copernicus Marine data visuals

## cmocean stops (7 per map, from the cmocean package)

- deep: #fdfecc #a5dfa7 #5dbaa4 #488e9e #3e6495 #3f396c #281a2c
- thermal: #042333 #2c3395 #744992 #b15f82 #eb7958 #fbb43d #e8fa5b
- haline: #2a186c #14439c #206e8b #3c9387 #5ab978 #aad85c #fdef9a
- algae: #d7f9d0 #a2d595 #64b463 #129450 #126e45 #1a482f #122414
- speed: #fffdcd #e1cd73 #aaac20 #5f920c #187328 #144b2a #172313
- amp: #f1edec #dfbcb0 #d08b73 #c0583b #a62225 #730e27 #3c0912
- balance: #181c43 #0c5ebe #75aabe #f1eceb #d08b73 #a52125 #3c0912
- ice: #040613 #292851 #3f4b96 #427bb7 #61a8c7 #9cd4da #eafdfd
- tempo: #fff6f4 #c3d1ba #7db390 #2a937f #156d73 #1c455b #151d44
- topo: #281a2c #3e6394 #5dbaa4 #0d2514 #566635 #c69f50 #f9fde4
- dense: #e6f1f1 #a2cee2 #76a4e5 #7871d5 #7642a5 #621d62 #360e24

## Gaps

- No strong X example found for subsurface temperature/thermocline maps
- X search has no engagement filter and keyword results were noisy; examples came mainly from targeted account searches
- Some accounts not found or suspended: pinakographos (Daniel Huffman), milos_agathon (suspended), fusedio, NASA_PACE; Sean Conway's handle not confirmed
- esri.com and blog.mapbox.com links return 403 to automated checks (bot blocking, not 404)
- Palettes are sampled from the posted images (median-cut), so they approximate the source colours