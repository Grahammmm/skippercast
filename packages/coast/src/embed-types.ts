// Types of the public embed API (src/embed.ts), in a module that imports no
// renderer: v2 type-checks against them under web/tsconfig.json without
// pulling three or the viewer into its program (FE-71). src/embed.ts
// re-exports every name, so hosts may import either module.
// The exports here are a shared API: announce a change on issue #413 first.
import type {CoastOverlayColor,CoastOverlayPalette,CoastPalette} from './palette.ts';
import type {CurrentLayer} from './state/current-layer.ts';

export type {CoastOverlayColor,CoastOverlayPalette} from './palette.ts';
export type CoastPerspective='2d'|'3d';
/**
 * `native` (default): the scene's own layers panel, view controls, reading, habitat
 * detail and sources button, as v1 shows them. `host`: the host draws those
 * functions from the handle's setters and the reading, target-detail and
 * source-coverage events; the root holds only the scene, its labels, pins and
 * footer, and the closed sources sheet that `openSources()` shows.
 */
export type CoastChrome='native'|'host';
/** One terrain source from the reviewed manifest (the shape of `coast3d/regional.ts` `TerrainSource`, kept here so this module imports no renderer code). */
export type CoastTerrainSource={id:number;label:string;kind:string;resolutionM:number|null;datum:string;sourceDate:string;url:string};
/**
 * A terrain inspection at the sample's WGS84 point. `heightM` is the original
 * sample value in the source's own vertical reference (`source.datum`), `source.kind`
 * is the manifest's source class (for example lidar, estimate or model) and
 * `source.sourceDate` is its clock. The strings are the native reading panel's,
 * verbatim: `label` is its measured or modelled eyebrow ("MEASURED LIDAR · NAVD88",
 * "REGIONAL MODEL"), and `detail` gains the chart band when it arrives later.
 */
export type CoastReading={latitude:number;longitude:number;heightM:number;spacingM:number;source:Readonly<CoastTerrainSource>;label:string;value:string;location:string;detail:string};
/** The selected habitat's evidence; the strings are the native detail panel's, verbatim. */
export type CoastTargetDetail={id:string;kind:'reef'|'shore';title:string;facts:string;evidence:string};
/** The terrain sources behind the source-coverage colours, with the native key verbatim. */
export type CoastSourceCoverage={sources:readonly Readonly<CoastTerrainSource>[];key:string};
/** An admitted habitat selection in WGS84 degrees, with its public id. */
export type CoastSelection={latitude:number;longitude:number;region?:string;id?:string};
/** The renderer camera: centre in WGS84 degrees and visible span in metres. */
export type CoastView={latitude:number;longitude:number;span:number};
/** A host camera request; without `span` the renderer keeps its scale. */
export type CoastLocation={latitude:number;longitude:number;span?:number};

/** State applied once at mount, before `load()`, in the order v1 applies it. */
export type CoastInitialState={
 currentLayer?:CurrentLayer;
 /** A `packages/coast` species id (map SkipperCast targets with `coastTarget`). */
 species?:string;
 /** Feet: 60 for Spear, 300 otherwise. */
 depthLimit?:number;
 location?:CoastLocation;
 hour?:Date|null;
 perspective?:CoastPerspective;
 /** An exact public habitat id to restore (`?habitat=`). */
 habitat?:string|null;
 visible?:boolean;
};

export type CoastMountOptions={
 /**
  * The shadow root to mount into; by default `host`'s open shadow root, attached
  * if absent. A root that still holds a mounted coast (`#scene`) throws: destroy
  * that handle first. Other content in the root is left alone.
  */
 root?:ShadowRoot;
 /** Who draws the terrain controls; `native` unless the host opts in. */
 chrome?:CoastChrome;
 /** Stylesheet URLs linked at the top of the root, before the scene. */
 styles?:readonly string[];
 /** Renderer colours over DEFAULT_COAST_PALETTE (v2 reads them through web/map/palette.ts; v1 passes none). */
 palette?:Partial<CoastPalette>;
 initial?:CoastInitialState;
 /** The host shows its own surface-current choice, so the scene's checkbox is hidden. */
 hostCurrents?:boolean;
 /** Replaces the scene's links to the standalone page's report (`index.html#forecast`). */
 forecastHref?:string;
 onSelection?:(selection:CoastSelection)=>void;
 onRestoredSelection?:(selection:CoastSelection)=>void;
 onSelectionInvalidated?:()=>void;
 onCurrentStatus?:(text:string)=>void;
 onView?:(view:CoastView)=>void;
 onPerspective?:(mode:CoastPerspective)=>void;
 /** A terrain inspection with its measured or modelled label and source date; `null` when it clears. */
 onReading?:(reading:CoastReading|null)=>void;
 /** The selected or restored habitat's evidence; `null` when the detail closes. */
 onTargetDetail?:(detail:CoastTargetDetail|null)=>void;
 /** The terrain source inventory, once the reviewed release loads. */
 onSourceCoverage?:(coverage:CoastSourceCoverage)=>void;
 /** Host handlers for the scene's own buttons; each replaces the renderer's. */
 onTop?:()=>void;
 onCloseSelection?:()=>void;
 /** Also relabels the button "Reset map view", since the host decides where home is. */
 onReset?:()=>void;
 /** Colours for `setOverlay` styles, by role (v2 passes its web/map/palette.ts Palette); without it `setOverlay` throws. */
 overlayPalette?:CoastOverlayPalette;
 /** A click on a host overlay; the renderer then shows no terrain reading for that click. */
 onOverlayPick?:(pick:CoastOverlayPick)=>void;
};

/**
 * The handle v2's MapStage and v1's workspace drive. Every method may be
 * called before `load()` resolves; after `destroy()` the handle is inert.
 */
export interface CoastHandle{
 /** Streams the reviewed terrain; resolves false when graphics or assets are unavailable. */
 load():Promise<boolean>;
 /** Moves the camera only; both perspectives share one scene. */
 setPerspective(mode:CoastPerspective):void;
 setLocation(point:CoastLocation):void;
 /** Returns false, and clears habitat, when the species is unsupported. */
 setSpecies(id:string):boolean;
 /** The selected UTC hour for surface currents; `null` means none chosen. */
 setHour(at:Date|null):void;
 /** Maximum habitat depth in feet. */
 setDepthLimit(ft:number):void;
 setCurrentLayer(id:CurrentLayer):void;
 /** Restores an exact public habitat id without selection callbacks; `null` clears. */
 selectHabitat(id:string|null):void;
 /** A hidden embed stops drawing and withdraws its overlays until shown again. */
 setVisible(visible:boolean):void;
 /** Drapes GeoJSON features on the terrain under `id`, replacing an overlay with that id; kept while hidden; invalid input throws. */
 setOverlay(id:string,overlay:CoastOverlay):void;
 /** Removes an overlay and frees its geometry; false when the id is unknown. */
 removeOverlay(id:string):boolean;
 /** Seabed relief exaggeration, 1 (true scale) to 12 in whole steps; land stays true scale. */
 setRelief(factor:number):void;
 /** Opacity of the illustrative +0.8 m water surface, 0 (clear) to 0.8, in 0.05 steps; the native slider calls it transparency. */
 setWaterOpacity(opacity:number):void;
 setWaterVisible(visible:boolean):void;
 setContours(visible:boolean):void;
 /** Colours the terrain by the source behind each sample (lidar, survey, chart estimate, model). */
 setSourceCoverage(visible:boolean):void;
 /** Reef areas, outlines and species pins. */
 setHabitatVisible(visible:boolean):void;
 zoom(direction:'in'|'out'):void;
 /** The renderer's home view; the new camera arrives through `onView`. */
 resetView():void;
 /** The top-down camera, as `setPerspective('2d')`. */
 topView():void;
 /** Shows the renderer's sources and assumptions sheet. */
 openSources():void;
 destroy():void;
}

// Host overlays draped on the terrain (FE-81, src/coast3d/overlays.ts).
export type CoastOverlayKind='fill'|'line'|'point';
type Position=readonly number[];
type Ring=readonly Position[];
/** GeoJSON geometries in WGS84 longitude, latitude. */
export type CoastOverlayGeometry=
 |{readonly type:'Point';readonly coordinates:Position}
 |{readonly type:'MultiPoint';readonly coordinates:readonly Position[]}
 |{readonly type:'LineString';readonly coordinates:readonly Position[]}
 |{readonly type:'MultiLineString';readonly coordinates:readonly Ring[]}
 |{readonly type:'Polygon';readonly coordinates:readonly Ring[]}
 |{readonly type:'MultiPolygon';readonly coordinates:readonly (readonly Ring[])[]};
/** A GeoJSON feature; `id` is what a pick reports. */
export type CoastOverlayFeature={readonly id:string|number;readonly geometry:CoastOverlayGeometry;readonly properties?:Readonly<Record<string,unknown>>|null};
export type CoastOverlayStyle={
 /** Fill, line or point colour. */
 readonly color:CoastOverlayColor;
 /** 0–1; fills default to 0.25, lines and points to 1. */
 readonly opacity?:number;
 /** A fill's boundary line or a point's ring. */
 readonly outline?:CoastOverlayColor;
 readonly outlineOpacity?:number;
 /** Point diameter in CSS pixels (8 by default). */
 readonly size?:number;
};
export type CoastOverlay={
 readonly kind:CoastOverlayKind;
 /** fill: Polygon or MultiPolygon; line: LineString or MultiLineString; point: Point or MultiPoint. */
 readonly features:readonly CoastOverlayFeature[];
 readonly style:CoastOverlayStyle;
 /** Draw order, bottom to top; equal orders stack in the order first set. Default 0. */
 readonly order?:number;
};
/** A selected overlay feature and the picked place in WGS84 degrees. */
export type CoastOverlayPick={overlay:string;feature:string|number;kind:CoastOverlayKind;latitude:number;longitude:number};
