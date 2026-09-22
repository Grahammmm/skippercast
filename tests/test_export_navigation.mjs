import test from 'node:test';
import assert from 'node:assert/strict';
import {initNavigation,viewFromHash} from '../dist/navigation.js';

test('export is a navigable panel and same-view map actions dismiss the options sheet',()=>{
  assert.equal(viewFromHash('#export'),'export');
  const saved=Object.fromEntries(['document','location','history','window','requestAnimationFrame'].map(k=>[k,globalThis[k]]));
  const element=()=>({open:false,hidden:false,addEventListener(){},setAttribute(){},removeAttribute(){},close(){this.open=false;this.closedInView=globalThis.document.body.dataset.view;},showModal(){this.open=true;}});
  const ids=Object.fromEntries(['spot-dialog','close-spot-dialog','show-selected-map','spot-dialog-body'].map(id=>[id,element()]));
  const options=element(), panels=['map','forecast','export','guide'].map(view=>({...element(),dataset:{panel:view}}));
  globalThis.document={body:{dataset:{view:'map'}},getElementById:id=>ids[id],querySelectorAll:selector=>selector==='dialog[open]'?[ids['spot-dialog'],options].filter(d=>d.open):selector==='[data-panel]'?panels:[]};
  globalThis.location={hash:'#map'};globalThis.history={replaceState(){}};globalThis.window={addEventListener(){}};globalThis.requestAnimationFrame=fn=>fn();
  try{
    const nav=initNavigation({onMapVisible(){}});
    options.open=true;nav.showView('map');assert.equal(options.open,false);
    ids['spot-dialog'].open=true;nav.showView('export');
    assert.equal(ids['spot-dialog'].open,false);
    assert.equal(ids['spot-dialog'].closedInView,'export','dialog close must not clear selected map context before moving to a new view');
    assert.equal(panels.find(p=>p.dataset.panel==='export').hidden,false);
    assert.equal(panels.find(p=>p.dataset.panel==='map').hidden,true);
  }finally{for(const [k,value]of Object.entries(saved)){if(value===undefined)delete globalThis[k];else globalThis[k]=value;}}
});
