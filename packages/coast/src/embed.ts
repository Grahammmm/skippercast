// Public embed API for hosts that own region, target, location and hour: v1's
// dist/coast-workspace.js and the v2 MapStage (FE-71) use this one mount, so
// neither copies the scene markup nor reaches into the renderer (design § 3A.2).
// The exports here are a shared API: announce a change on issue #413 first.
// Importing this module loads three; hosts import it dynamically.
import {CoastViewer,type CoastViewerOptions} from './coast3d/viewer.ts';
import {DEFAULT_COAST_PALETTE,type CoastPalette} from './palette.ts';
import type {CurrentLayer} from './state/current-layer.ts';
import {coastPath} from './transport.ts';
import {coastEmbedTemplate} from './embed-template.ts';

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
 /** An open shadow root on `host` to reuse; by default the embed attaches one. */
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

type Viewer=Pick<CoastViewer,keyof CoastHandle>;
/** Test seam: constructs the renderer. Hosts never pass it. */
export type CoastViewerFactory=(scene:HTMLElement,options:CoastViewerOptions)=>Viewer;
const createViewer:CoastViewerFactory=(scene,options)=>new CoastViewer(scene,options);

/** DEFAULT_COAST_PALETTE with the host's string values for known roles. */
export function embedPalette(overrides:Partial<CoastPalette>={}):Readonly<CoastPalette>{
 const palette={...DEFAULT_COAST_PALETTE};
 for(const key of Object.keys(palette) as (keyof CoastPalette)[]){const value=overrides[key];if(typeof value==='string'&&value)palette[key]=value;}
 return Object.freeze(palette);
}

/** Mounts the managed terrain renderer and its scene markup in `host`'s shadow root. */
export function mountCoast(host:HTMLElement,options:CoastMountOptions={},factory:CoastViewerFactory=createViewer):CoastHandle{
 const root=options.root??host.attachShadow({mode:'open'});
 for(const href of options.styles??[]){const style=document.createElement('link');style.rel='stylesheet';style.href=href;root.append(style);}
 const parsed=new DOMParser().parseFromString(coastEmbedTemplate,'text/html');
 root.append(document.importNode(parsed.getElementById('scene')!,true),document.importNode(parsed.getElementById('sources')!,true));
 const $=<E extends HTMLElement=HTMLElement>(id:string)=>root.getElementById(id) as E;
 // The host owns place, target and perspective, so their in-scene controls go.
 root.querySelector<HTMLElement>('.intro')!.hidden=true;
 root.querySelector('.layers h2')!.remove();root.querySelector('.layers>.eyebrow')!.remove();
 root.querySelector<HTMLElement>('[for="species"]')!.hidden=true;$('species').hidden=true;
 if(options.hostCurrents)$('currents').closest('label')!.hidden=true;
 $('layers-toggle').textContent='Terrain layers & evidence';
 const controls=root.querySelector('.view-controls')!;
 // CoastViewer binds these ids; hidden stand-ins keep it off the host's chrome.
 for(const id of ['perspective-2d','perspective-3d']){const button=document.createElement('button');button.id=id;button.hidden=true;controls.append(button);}
 const sources=document.createElement('button');sources.id='sources-open';sources.textContent='ⓘ';sources.setAttribute('aria-label','Terrain sources and assumptions');controls.append(sources);
 for(const link of root.querySelectorAll<HTMLAnchorElement>('[data-coast-receipt]'))link.href=coastPath(link.dataset.coastReceipt!);
 if(options.forecastHref!==undefined)for(const link of root.querySelectorAll<HTMLAnchorElement>('a[href="index.html#forecast"]'))link.href=options.forecastHref;
 const {onSelection,onRestoredSelection,onSelectionInvalidated,onCurrentStatus,onView,onPerspective}=options;
 const viewer=factory($('scene'),{root,managed:true,...(options.palette?{palette:embedPalette(options.palette)}:{}),onCurrentStatus,onView,onSelectionInvalidated,onRestoredSelection,onSelection,onPerspective});
 if(options.onTop)$('top').onclick=options.onTop;
 if(options.onCloseSelection)$('target-close').onclick=options.onCloseSelection;
 if(options.onReset){$('reset').setAttribute('aria-label','Reset map view');$('reset').onclick=options.onReset;}
 let alive=true;
 const live=<A extends unknown[],R>(run:(...args:A)=>R,fallback:R)=>(...args:A):R=>alive?run(...args):fallback;
 const handle:CoastHandle={
  load:live(()=>viewer.load(),Promise.resolve(false)),
  setPerspective:live(mode=>viewer.setPerspective(mode),undefined),
  setLocation:live(point=>viewer.setLocation(point),undefined),
  setSpecies:live(id=>viewer.setSpecies(id),false),
  setHour:live(at=>viewer.setHour(at),undefined),
  setDepthLimit:live(ft=>viewer.setDepthLimit(ft),undefined),
  setCurrentLayer:live(id=>viewer.setCurrentLayer(id),undefined),
  selectHabitat:live(id=>viewer.selectHabitat(id),undefined),
  setVisible:live(visible=>viewer.setVisible(visible),undefined),
  destroy:live(()=>{alive=false;viewer.destroy();},undefined),
 };
 const initial=options.initial??{};
 if(initial.currentLayer!==undefined)handle.setCurrentLayer(initial.currentLayer);
 if(initial.species!==undefined)handle.setSpecies(initial.species);
 if(initial.depthLimit!==undefined)handle.setDepthLimit(initial.depthLimit);
 if(initial.location)handle.setLocation(initial.location);
 if(initial.hour!==undefined)handle.setHour(initial.hour);
 if(initial.perspective)handle.setPerspective(initial.perspective);
 if(initial.habitat!==undefined)handle.selectHabitat(initial.habitat);
 if(initial.visible!==undefined)handle.setVisible(initial.visible);
 return handle;
}
