// Types of the public embed API (src/embed.ts), in a module that imports no
// renderer: v2 type-checks against them under web/tsconfig.json without
// pulling three or the viewer into its program (FE-71). src/embed.ts
// re-exports every name, so hosts may import either module.
// The exports here are a shared API: announce a change on issue #413 first.
import type {CoastPalette} from './palette.ts';
import type {CurrentLayer} from './state/current-layer.ts';

export type CoastPerspective='2d'|'3d';
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
 /** Host handlers for the scene's own buttons; each replaces the renderer's. */
 onTop?:()=>void;
 onCloseSelection?:()=>void;
 /** Also relabels the button "Reset map view", since the host decides where home is. */
 onReset?:()=>void;
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
 destroy():void;
}
