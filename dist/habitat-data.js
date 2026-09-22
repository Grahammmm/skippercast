// Shared clock, integrity and display rules for the regional ocean layers.
export const LAYER_IDS=['sst-analysis','chlorophyll-observation','wcofs-surface-forecast'];
const numeric=Number.isFinite;
export function validHabitatManifest(data,regionId) {
  if(data?.schema_version!==1||data.region_id!==regionId||!data.layers||Array.isArray(data.layers))return false;
  const bounds=b=>Array.isArray(b)&&b.length===4&&b.every(numeric)&&b[0]<b[2]&&b[1]<b[3]&&b[0]>=-180&&b[2]<=180&&b[1]>=-90&&b[3]<=90;
  return Object.entries(data.layers).every(([id,l])=>LAYER_IDS.includes(id)&&l.id===id&&['forecast','analysis','observation'].includes(l.kind)&&Array.isArray(l.fields)&&l.fields[0]==='latitude'&&l.fields[1]==='longitude'&&Array.isArray(l.resolution_degrees)&&l.resolution_degrees.length===2&&l.resolution_degrees.every(n=>numeric(n)&&n>0&&n<=.25)&&Array.isArray(l.frames)&&l.frames.length<=169&&l.frames.every(f=>numeric(f.time)&&Number.isInteger(f.valid_cells)&&f.valid_cells>=0)&&Array.isArray(l.tiles)&&l.tiles.length<=1000&&l.tiles.every(t=>bounds(t.bounds)&&numeric(t.bytes)&&t.bytes>0&&t.bytes<=5_000_000&&/^[a-f0-9]{64}$/.test(t.sha256)));
}
export function habitatFrame(layer,selectedTime,now=Date.now()) {
  const empty=reason=>({frame:null,mode:null,reason});
  const age=(now-Date.parse(layer?.issued_at||layer?.sample_at))/3600000;
  const frames=layer?.frames?.filter(f=>numeric(f.time)&&f.valid_cells>0)||[];
  if(!['ok','retained'].includes(layer?.status)||!frames.length)return empty('Source unavailable or no populated cells');
  if(!numeric(age)||age< -1||!numeric(layer.max_age_hours)||age>layer.max_age_hours)return empty('Source is outside its freshness window');
  if(!numeric(selectedTime))return empty('Select a forecast time');
  if(layer.kind==='forecast') {
    const times=frames.map(f=>f.time);
    if(selectedTime<Math.min(...times)||selectedTime>Math.max(...times))return empty('No ocean forecast at the selected time');
    const frame=frames.reduce((best,f)=>Math.abs(f.time-selectedTime)<Math.abs(best.time-selectedTime)?f:best);
    return Math.abs(frame.time-selectedTime)<=5400?{frame,mode:'forecast',reason:'Native three-hour model frame; not a fish forecast'}:empty('Missing forecast step; no interpolation across the gap');
  }
  const valid=frames.filter(f=>f.time<=selectedTime).sort((a,b)=>b.time-a.time);
  return valid.length?{frame:valid[0],mode:'observed-context',reason:'Dated surface context, not a forecast for the trip date'}:empty('Analysis was not valid by the selected time');
}
export function tileOverlaps(a,b) {return a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];}
export function habitatTileURL(base,record,regionId) {
  if(!/^habitat-tiles\/[a-z0-9-]+-[a-f0-9]{16}\.json$/.test(record?.path||'')||!(/^[a-f0-9]{64}$/).test(record.sha256)||!numeric(record.bytes)||record.bytes<1||record.bytes>5_000_000)throw Error('Invalid ocean tile reference');
  const url=new URL(record.path,base),root=new URL('.',base);
  if(url.origin!==root.origin||!url.pathname.startsWith(root.pathname)||!root.pathname.includes(`/regions/${regionId}/`))throw Error('Ocean tile outside region');
  return url.href;
}
export function habitatTileMatchesLayer(tile,layer) {
  return !!layer && JSON.stringify(tile.fields)===JSON.stringify(layer.fields) && JSON.stringify(tile.resolution_degrees)===JSON.stringify(layer.resolution_degrees) && tile.frames.every(f=>layer.frames.some(parent=>parent.time===f.time));
}
export async function decodeHabitatTile(bytes,record,regionId,layerId,layer) {
  if(bytes.byteLength!==record.bytes)throw Error('Ocean tile length mismatch');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
  if(hash!==record.sha256)throw Error('Ocean tile integrity check failed');
  const tile=JSON.parse(new TextDecoder().decode(bytes));
  if(tile.schema_version!==1||tile.region_id!==regionId||tile.layer_id!==layerId||!Array.isArray(tile.fields)||!Array.isArray(tile.frames)||!Array.isArray(tile.resolution_degrees)||tile.resolution_degrees.some(v=>!numeric(v)||v<=0||v>.25))throw Error('Ocean tile identity or grid mismatch');
  if(JSON.stringify(tile.bounds)!==JSON.stringify(record.bounds))throw Error('Ocean tile bounds mismatch');
  if(tile.fields[0]!=='latitude'||tile.fields[1]!=='longitude'||tile.frames.some(f=>!numeric(f.time)||!Array.isArray(f.cells)||f.cells.some(r=>!Array.isArray(r)||r.length!==tile.fields.length||!numeric(r[0])||!numeric(r[1])||r.some(v=>v!==null&&!numeric(v)))))throw Error('Invalid ocean tile samples');
  if(!habitatTileMatchesLayer(tile,layer))throw Error('Ocean tile fields, resolution or times differ from parent layer');
  return tile;
}
export function thermalReference(method,temperature) {
  const band=method?.temperature_range_c;
  if(!numeric(temperature)||!Array.isArray(band))return 'No locally validated surface-temperature optimum is assigned.';
  return `${temperature>=band[0]&&temperature<=band[1]?'Within':'Outside'} the broad published thermal reference (${band.map(c=>(c*9/5+32).toFixed(0)).join('–')}°F). This does not establish fish presence or absence.`;
}
export function habitatColor(value,mode) {
  if(!numeric(value))return null;
  const t=mode==='chlorophyll'?Math.max(0,Math.min(1,(Math.log10(Math.max(value,.01))+2)/3)):mode==='fronts'?Math.max(0,Math.min(1,value/.5)):Math.max(0,Math.min(1,(value-10)/17));
  return `hsl(${Math.round(mode==='chlorophyll'?210-t*135:mode==='fronts'?190-t*155:235-t*230)} 72% 48%)`;
}
