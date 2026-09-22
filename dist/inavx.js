import {tripGPX} from './gpx.js?v=8.10';
import {atlasExportAllowed} from './export-screen.js?v=8.10';
import {getRegion} from './region.js?v=8.10';
import {esc} from './marine-charts.js?v=8.10';

export function exportSelection(atlas,screen,ids){
  const unique=[...new Set(ids)];
  if(!unique.length||unique.some(id=>!atlasExportAllowed(atlas,screen,id)))throw Error('Every selected point and its full outline must pass the current protected-area screen. Refresh the map before exporting.');
  return tripGPX(atlas,unique,getRegion().name+' fishing set');
}

export function initINavX(atlas,screen){
  const selection=new Set();let objectURL=null;
  const dialog=document.createElement('dialog');dialog.className='inavx-dialog';dialog.setAttribute('aria-labelledby','inavx-title');document.body.append(dialog);
  const opener=document.createElement('button');opener.type='button';opener.className='secondary';opener.textContent='iNavX trip set · 0';
  document.querySelector('#map-options .map-options-body')?.append(opener);
  if(!opener.isConnected)document.getElementById('map-options').append(opener);
  const guide=opener.cloneNode(true);document.querySelector('#guide-panel')?.append(guide);
  function render(){
    const targets=[...selection].map(id=>atlas.targets.find(t=>t.id===id));
    dialog.innerHTML=`<div class="detail-top"><h2 id="inavx-title">Send a fishing set to iNavX</h2><button data-action="close" aria-label="Close iNavX export">✕</button></div><p>${targets.length} selected spots · ${esc(getRegion().name)}</p>
    <p class="small">Add spots from their map cards. The set includes their notes, reef outlines and structure alignments. Shared outlines are included once.</p>
    <ul class="export-selection">${targets.map(t=>`<li><span>${esc(t.id)} · ${esc(t.label)}</span><button data-remove="${esc(t.id)}" aria-label="Remove ${esc(t.id)}">Remove</button></li>`).join('')}</ul>
    <div class="button-row"><button class="primary" data-action="share" ${targets.length?'':'disabled'}>Share GPX file</button><button data-action="download" ${targets.length?'':'disabled'}>Download GPX</button></div><p data-export-status role="status"></p>
    <details open><summary>Import on your iPad</summary><ol><li>Use Share GPX file, then choose iNavX. If iNavX is absent, save the file to Files first.</li><li>In Files, open the GPX and use Share → iNavX. Follow iNavX’s import prompt. Its waypoints and tracks are separate displays.</li><li>Show the imported waypoints and tracks on the chart. Spot outlines and alignment lines are tracks, not routes to navigate.</li><li>Compare a waypoint’s name and latitude/longitude with its SkipperCast card. Check that the outline stays offshore and outside MPAs.</li></ol><p class="small">A download does not confirm import. Check the result in iNavX. Reimporting an existing set can create duplicates; review or remove the older set in iNavX first. These stable spot IDs help identify it.</p><a href="https://www.inavx.com/faq" target="_blank" rel="noopener">iNavX official import FAQ ↗</a></details>`;
  }
  function sync(){opener.textContent=guide.textContent=`iNavX trip set · ${selection.size}`;}
  function open(){render();dialog.showModal();}
  opener.onclick=()=>{document.getElementById('map-options').close();open();};guide.onclick=open;
  dialog.addEventListener('click',async event=>{
    const remove=event.target.closest('[data-remove]');if(remove){selection.delete(remove.dataset.remove);sync();render();return;}
    const action=event.target.closest('[data-action]')?.dataset.action;if(action==='close'){dialog.close();return;}
    if(!['share','download'].includes(action))return;
    const status=dialog.querySelector('[data-export-status]');
    try{
      const content=exportSelection(atlas,screen,[...selection]);
      const filename=`SkipperCast-${getRegion().id}-${new Date().toISOString().slice(0,10)}-${selection.size}-spots.gpx`;
      const file=new File([content],filename,{type:'application/gpx+xml'});
      if(action==='share'&&navigator.canShare?.({files:[file]})){
        await navigator.share({files:[file],title:'SkipperCast fishing set'});status.textContent='File handed to the share sheet. Confirm its waypoints and tracks inside iNavX.';
      }else{
        if(objectURL)URL.revokeObjectURL(objectURL);objectURL=URL.createObjectURL(file);
        const a=document.createElement('a');a.href=objectURL;a.download=filename;a.click();status.textContent=`Downloaded ${filename}. Open it from Files → Downloads and share it to iNavX.`;
      }
    }catch(e){status.textContent=e.name==='AbortError'?'Share cancelled; your selection is retained.':e.message;}
  });
  return {mount(container,target){
    if(!atlas.targets.some(t=>t.id===target.id))return;
    const row=document.createElement('div');row.className='button-row';
    const add=document.createElement('button');add.type='button';add.textContent=selection.has(target.id)?'Added to iNavX set':'Add to iNavX set';
    add.onclick=()=>{selection.add(target.id);sync();add.textContent='Added to iNavX set';};
    const review=document.createElement('button');review.textContent='Review & export';review.onclick=()=>{document.getElementById('spot-dialog')?.close();open();};
    row.append(add,review);container.append(row);
  }};
}
