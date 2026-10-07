import {hasCoastTerrain} from '../web/coast-context.ts';
// Native coast scores remain separate from the historical atlas and legal rules.
export const COAST_TARGETS=[
 {id:'lingcod',name:'Lingcod',group:'Coastal habitat',kind:'reef'},
 {id:'rockfish-reef',name:'Reef rockfish',group:'Coastal habitat',kind:'coast'},
 {id:'gopher-rockfish',name:'Gopher rockfish',group:'Coastal habitat',kind:'coast'},
 {id:'cabezon-shallow-reef',name:'Cabezon',group:'Coastal habitat',kind:'coast'},
 {id:'surfperch',name:'Barred surfperch',group:'Coastal habitat',kind:'coast'},
];
export function sharedTargetOptions(region){
 const base=region.target_options??[];
 if(!hasCoastTerrain(region.id))return base;
 const ids=new Set(base.map(t=>t.id));
 return [...base,...COAST_TARGETS.filter(t=>!ids.has(t.id))];
}
export const nativeOnlyTarget=id=>COAST_TARGETS.some(t=>t.id===id&&t.kind==='coast');
