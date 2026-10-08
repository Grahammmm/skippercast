// Public embed API for hosts that own region, target, location and hour: v1's
// dist/coast-workspace.js and the v2 MapStage (FE-71) use this one mount, so
// neither copies the scene markup nor reaches into the renderer (design § 3A.2).
// The exports here are a shared API: announce a change on issue #413 first.
// Importing this module loads three; hosts import it dynamically.
import {CoastViewer,type CoastViewerOptions} from './coast3d/viewer.ts';
import {DEFAULT_COAST_PALETTE,type CoastPalette} from './palette.ts';
import type {CoastHandle,CoastMountOptions} from './embed-types.ts';
import {coastPath} from './transport.ts';
import {coastEmbedTemplate} from './embed-template.ts';
export type {CoastHandle,CoastInitialState,CoastLocation,CoastMountOptions,CoastPerspective,CoastSelection,CoastView} from './embed-types.ts';
export type {CoastOverlay,CoastOverlayColor,CoastOverlayFeature,CoastOverlayGeometry,CoastOverlayKind,CoastOverlayPalette,CoastOverlayPick,CoastOverlayStyle} from './embed-types.ts';

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

/**
 * Mounts the managed terrain renderer and its scene markup in `host`'s shadow
 * root. `destroy()` removes every node the embed inserted and releases the
 * renderer, so the same host can be mounted again.
 */
export function mountCoast(host:HTMLElement,options:CoastMountOptions={},factory:CoastViewerFactory=createViewer):CoastHandle{
 const existing=options.root??host.shadowRoot,root=existing??host.attachShadow({mode:'open'});
 if(existing?.getElementById('scene'))throw Error('mountCoast: this root already holds a mounted coast; destroy its handle first');
 const inserted:Element[]=[];
 for(const href of options.styles??[]){const style=document.createElement('link');style.rel='stylesheet';style.href=href;root.append(style);inserted.push(style);}
 const parsed=new DOMParser().parseFromString(coastEmbedTemplate,'text/html');
 const scene=document.importNode(parsed.getElementById('scene')!,true),sourcesDialog=document.importNode(parsed.getElementById('sources')!,true);
 root.append(scene,sourcesDialog);inserted.push(scene,sourcesDialog);
 const $=<E extends HTMLElement=HTMLElement>(id:string)=>root.getElementById(id) as E;
 // The host owns place, target and perspective, so their in-scene controls go.
 root.querySelector<HTMLElement>('.intro')!.hidden=true;
 root.querySelector('.layers h2')!.remove();root.querySelector('.layers>.eyebrow')!.remove();
 root.querySelector<HTMLElement>('[for="species"]')!.hidden=true;$('species').hidden=true;
 if(options.hostCurrents)$('currents').closest('label')!.hidden=true;
 $('layers-toggle').textContent='Terrain layers & evidence';
 // A named group of pin buttons: aria-label alone is prohibited on a role-less div (axe, FE-71).
 $('pins').setAttribute('role','group');
 const controls=root.querySelector('.view-controls')!;
 // CoastViewer binds these ids; hidden stand-ins keep it off the host's chrome.
 for(const id of ['perspective-2d','perspective-3d']){const button=document.createElement('button');button.id=id;button.hidden=true;controls.append(button);}
 const sources=document.createElement('button');sources.id='sources-open';sources.textContent='ⓘ';sources.setAttribute('aria-label','Terrain sources and assumptions');controls.append(sources);
 for(const link of root.querySelectorAll<HTMLAnchorElement>('[data-coast-receipt]'))link.href=coastPath(link.dataset.coastReceipt!);
 if(options.forecastHref!==undefined)for(const link of root.querySelectorAll<HTMLAnchorElement>('a[href="index.html#forecast"]'))link.href=options.forecastHref;
 const {onSelection,onRestoredSelection,onSelectionInvalidated,onCurrentStatus,onView,onPerspective,overlayPalette,onOverlayPick}=options;
 const viewer=factory(scene,{root,managed:true,...(options.palette?{palette:embedPalette(options.palette)}:{}),onCurrentStatus,onView,onSelectionInvalidated,onRestoredSelection,onSelection,onPerspective,overlayPalette,onOverlayPick});
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
  setOverlay:live((id,overlay)=>viewer.setOverlay(id,overlay),undefined),
  removeOverlay:live(id=>viewer.removeOverlay(id),false),
  destroy:live(()=>{alive=false;try{viewer.destroy();}finally{for(const node of inserted)node.remove();}},undefined),
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
