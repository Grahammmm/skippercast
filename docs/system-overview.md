# How SkipperCast will work

SkipperCast brings together **where to investigate, when a trip is workable, and the evidence behind each recommendation**. The first web map, target notes, GPX downloads, forecast comparisons, Python tools, and dated atlas are built. The complete trip planner, shared evidence store, and public-app delivery integration remain planned.

In these diagrams, **dashed boxes are planned application components**. Solid boxes identify available inputs, existing tools, or the current person/agent review step. Arrows describe the intended data flow, not a claim that every connection is already automated.

## From data to a fishing plan

```mermaid
flowchart TB
    subgraph inputs["1. Collect evidence"]
        terrain["Seafloor surveys<br/>Depth, bottom type, relief<br/>USGS and cleared survey sources"]
        conditions["Ocean conditions<br/>Wind, swell, chop, buoys, tides<br/>ECMWF / NOAA via Open-Meteo; NWS / NDBC"]
        context["Rules and fishing evidence<br/>MPAs, seasons, security zones<br/>Dated reports; AIS when verified"]
    end

    evidence["2. Evidence library — planned<br/>Location, source date, model run, units<br/>Reuse rights, missing data, confidence"]
    terrain --> evidence
    conditions --> evidence
    context --> evidence

    habitat["Reviewed-atlas tools — built<br/>Rescore and export included habitat<br/>Points, reef areas, drift alignments"]
    screen["Forecast tools — built<br/>Compare model ranges<br/>Flag gaps and inconsistent inputs"]
    evidence --> habitat
    evidence --> screen

    preferences["Your boat and trip<br/>20 kt cruise, 200 ft limit<br/>4 fishing hours, return by 12:30 target"]
    review{{"3. Review the whole trip<br/>Person or agent checks rules, route,<br/>entrance, conditions and fishing time"}}
    habitat --> review
    screen --> review
    preferences --> review

    app["4. SkipperCast map — built<br/>Habitat layers, target notes, GPX<br/>On-demand wind and wave comparisons"]
    planner["Trip planner — planned<br/>Charted transit, fishing hours,<br/>daylight and reviewed assessments"]
    review --> planner
    planner --> app
    habitat --> app
    screen --> app
    evidence --> app

    export["Chartplotter export — built<br/>GPX points, tracks and alignments<br/>Import into iNavX"]
    alerts["Alert decisions — built<br/>Initial, update, retract, day-before final"]
    delivery["App delivery service — planned<br/>Telegram messages with receipts<br/>Deduplication and failure reporting"]
    log["Private trip log — planned<br/>Catches, measured drift, sonar notes<br/>Permission before sharing"]

    app --> export
    review --> alerts
    alerts --> delivery
    app --> log
    log -.->|"New observations; review before reuse"| evidence

    classDef planned stroke-dasharray: 5 5
    class evidence,planner,delivery,log planned
```

The example boat settings are editable planning inputs, not a promise that the boat can always cruise at 20 knots. A trip needs four actual fishing hours after transit and harbor time, a 12:30 return target, and a 13:00 deadline. A plotted fishing alignment does not establish a navigable route to it.

The current habitat tool re-exports a reviewed dataset and recomputes its terrain score; **automatically turning new surveys into new fishing areas is future GIS work**. Likewise, the collector preserves evidence and numerical screens, while whole-trip scoring and legal/local review remain person- or agent-assisted.

## What the chart layers mean

These are layers on the map, with their shipped and planned status shown separately.

| Chart layer | Data behind it | What the angler sees | Current status |
| --- | --- | --- | --- |
| Base chart and depth | OpenStreetMap for web geographic context; current nautical chart in iNavX | Shoreline context in the web map; navigation and charted contours in the chartplotter | Web base map built with Leaflet / OSM; it is not a nautical chart |
| Restrictions | Current official MPA boundaries/rules, security zones, seasons and species constraints | Clearly labeled restricted areas and date-sensitive rule notes | Dated research screen exists; current in-app overlays/checks are planned |
| Fishing habitat | Reviewed survey depth, bottom character, relief and terrain metrics | Ranked points, partial reef outlines, optional structure alignments | Web layers and public exports built: 132 points, 107 outlines, 31 alignments |
| Ocean conditions | Forecast wind/gusts, significant seas, available swell height/period/direction, observations, reference tides and supported current data | Time-selected conditions with model disagreement, age and missing-data indicators | Browser wind/wave comparisons and three sample labels built; observation/tide/current overlays remain planned |
| Fishing activity evidence | Identity-verified AIS, properly sourced dated catches, and permitted user observations | Evidence labels and dates; an activity layer only where support exists | Research only; no AIS-confirmed charter hotspots in the current edition |
| Your trip | Private boat profile, charted transit, selected grounds, fishing window and return deadline | Proposed trip timeline and route, kept distinct from fishing alignments | Public app planner and private journal planned |

All layers need a source/date/evidence view. A habitat grade, forecast confidence, and verified fishing activity are **different attributes**; the app must not collapse them into one unexplained “good spot” score. Port San Luis tides remain a nearby reference, not Morro Bay bar-current predictions.

## Software stack

```mermaid
flowchart TB
    ui["User interface — built<br/>Static HTML / CSS / JavaScript + Leaflet<br/>Map, evidence details, GPX, forecast viewer"]
    api["Application API — planned<br/>Profiles, map queries, saved trips<br/>Private access to personal records"]
    core["Python 3.11+ core — built<br/>Forecast collection and screens<br/>Habitat scoring, exports, alert decisions"]
    jobs["Job runner — planned for the app<br/>Scheduled refreshes and assessments<br/>Delivery retries, receipts, missed-run reporting"]
    current["Storage today<br/>Dated JSON and raw response files<br/>GPX, GeoJSON and offline HTML"]
    future[("Application storage — planned<br/>Spatial and time-indexed records<br/>Original-source archive and delivery state")]
    providers["External providers<br/>Survey, weather, observation,<br/>regulation and activity sources"]

    ui <-->|"Map features and trip evidence"| api
    api --> core
    jobs --> core
    core <--> current
    core <--> future
    providers --> core
    providers -->|"Browser forecast requests"| ui
    current -->|"Public atlas and GPX"| ui

    classDef planned stroke-dasharray: 5 5
    class api,jobs,future planned
```

The web app uses static HTML, CSS, JavaScript, Leaflet, and OpenStreetMap, with Sites configured for static hosting. It requests forecasts directly from providers. The Python core uses the standard library and runs independently. An application API, database, nautical chart provider, and durable public-app jobs remain unimplemented.

The existing personal forecast monitor and private Telegram integration operate separately from the public app. They can inform a later integration, but cloning this repository does not start a schedule or connect a messaging account. See [the web app guide](web-app.md) for current hosting and local-use instructions.

## Recommendation and notification flow

```mermaid
flowchart LR
    assess["Review a future trip date"] --> gate{"Both scores at least 9?<br/>Confidence Moderate or High?<br/>Numeric and trip requirements met?<br/>Complete evidence, no disqualifying hazard?"}
    gate -->|"Yes"| qualify["Qualifying opportunity"]
    gate -->|"No or unknown"| fail["Does not qualify"]
    qualify --> lifecycle["Compare with delivered alert state"]
    fail --> lifecycle
    lifecycle --> next["Initial alert, material update,<br/>explicit retraction, or silence"]
    next --> final["Evening before the trip:<br/>final for every previously alerted date;<br/>combined initial/final if first qualifying now"]
```

Comfort and fishing conditions are separate scores; overall is the lower score. The gate depends on a reviewed assessment, not simply on wind/wave numbers. Trip requirements include four actual fishing hours, legal grounds, the depth limit, and the complete departure-to-return window. Previously alerted dates require a final even if unchanged or retracted. A missed final assessment is reported honestly. Delivery state changes only after a confirmed receipt. See the [fixed rubric](assessment-rubric.md) and [forecast workflow](forecast-workflow.md).

For exact source rights and the public atlas's smaller geographic coverage, see [data sources](data-sources.md). For the current modules and their boundaries, see [architecture](architecture.md).
