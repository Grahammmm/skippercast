import test from 'node:test';
import assert from 'node:assert/strict';
import {modelURLs,morningRows,gridDistanceNm,selectedHour,updateCoastalForecast,disposeCoastalForecast,suspendCoastalForecast} from '../dist/coastal-forecast.js';
const epoch=iso=>Date.parse(iso)/1000;
const packets=(start,count=24)=>{
 const times=Array.from({length:count},(_,i)=>epoch(start)+i*3600),make=()=>({latitude:35.4,longitude:-120.9,timezone:'UTC',utc_offset_seconds:0,hourly_units:{time:'unixtime'},hourly:{time:[...times]}}),wind=make(),wave=make();
 const add=(p,field,model,value,unit)=>{p.hourly[`${field}_${model}`]=times.map(()=>value);p.hourly_units[`${field}_${model}`]=unit;};
 for(const model of ['ecmwf_ifs025','gfs_global']){add(wind,'wind_speed_10m',model,5,'kn');add(wind,'wind_gusts_10m',model,7,'kn');add(wind,'wind_direction_10m',model,270,'°');}
 for(const model of ['ecmwf_wam','ncep_gfswave016'])add(wave,'wave_height',model,2,'ft');
 for(const [field,value,unit] of [['swell_wave_height',1.5,'ft'],['swell_wave_period',12,'s'],['swell_wave_direction',270,'°'],['secondary_swell_wave_height',.5,'ft'],['secondary_swell_wave_period',8,'s'],['secondary_swell_wave_direction',180,'°'],['wind_wave_height',.3,'ft']])add(wave,field,'ncep_gfswave016',value,unit);
 return {wind,wave};
};
const fetcher=(p,counter)=>async url=>{if(counter)counter.count++;return Response.json(url.includes('/marine?')?p.wave:p.wind);};
const point={latitude:35.4,longitude:-120.9};
test('requests retain approved model pairs/variables/units but request unambiguous UTC unix source times',()=>{
 for(const [lat,lon] of [[41.7,-124.5],[38.2,-123.1],[36.6,-122.1],[34.1,-119.3],[32.6,-117.2]]){
  const urls=modelURLs(lat,lon);for(const url of Object.values(urls)){const p=new URL(url,'https://s.test').searchParams;assert.equal(p.get('latitude'),lat.toFixed(2));assert.equal(p.get('longitude'),lon.toFixed(2));assert.equal(p.get('timezone'),'UTC');assert.equal(p.get('timeformat'),'unixtime');assert.equal(p.get('cell_selection'),'sea');assert.equal(p.get('forecast_days'),'8');}
  assert.equal(new URL(urls.wind,'https://s.test').searchParams.get('models'),'ecmwf_ifs025,gfs_global');assert.equal(new URL(urls.wave,'https://s.test').searchParams.get('models'),'ecmwf_wam,ncep_gfswave016');
 }
 assert.throws(()=>modelURLs(20,-110));assert.ok(gridDistanceNm({latitude:36.25,longitude:-121.9},{latitude:36.25,longitude:-122})<6);assert.equal(gridDistanceNm(point,{latitude:null,longitude:-122}),Infinity);
});
test('exact selected hours preserve independent model values and partial/missing source horizons',()=>{
 const p=packets('2026-10-07T12:00Z',3);p.wind.hourly.wind_speed_10m_gfs_global[1]=10;p.wave.hourly.wave_height_ncep_gfswave016[1]=4;p.wind.hourly.wind_gusts_10m_gfs_global[1]=12;
 const selected=selectedHour(p.wind,p.wave,new Date('2026-10-07T13:00Z'));assert.deepEqual(selected.wind,[5,10]);assert.deepEqual(selected.waves,[2,4]);assert.equal(selected.epoch,epoch('2026-10-07T13:00Z'));assert.ok(selected.flags.includes('wind models differ >4 kt'));
 for(const at of ['2026-10-07T11:00Z','2026-10-07T15:00Z']){const row=selectedHour(p.wind,p.wave,at);assert.deepEqual(row.wind,[null,null]);assert.deepEqual(row.waves,[null,null]);assert.equal(row.windEpoch,null);assert.equal(row.waveEpoch,null);}
 p.wave.hourly.time.splice(1,1);const gap=selectedHour(p.wind,p.wave,'2026-10-07T13:00Z');assert.deepEqual(gap.wind,[5,10]);assert.deepEqual(gap.waves,[null,null]);
 for(const at of ['2026-10-07T13:30Z','invalid',new Date(NaN),null])assert.equal(selectedHour(p.wind,p.wave,at),null);
});
test('duplicate epochs, wrong time metadata, invalid units, directions and gust contradictions stay gaps',()=>{
 const p=packets('2026-10-07T12:00Z',3);p.wind.hourly.time[1]=p.wind.hourly.time[0];assert.deepEqual(selectedHour(p.wind,p.wave,'2026-10-07T12:00Z').wind,[null,null]);
 for(const patch of [{timezone:'America/Los_Angeles'},{utc_offset_seconds:3600},{hourly_units:{time:'iso8601'}}])assert.deepEqual(selectedHour({...p.wind,...patch},p.wave,'2026-10-07T14:00Z').wind,[null,null]);
 const q=packets('2026-10-07T12:00Z',1);q.wind.hourly_units.wind_speed_10m_gfs_global='m/s';q.wave.hourly_units.wave_height_ecmwf_wam='m';q.wind.hourly.wind_gusts_10m_ecmwf_ifs025[0]=3;q.wave.hourly.swell_wave_period_ncep_gfswave016[0]=0;q.wave.hourly.swell_wave_direction_ncep_gfswave016[0]=361;
 const row=selectedHour(q.wind,q.wave,'2026-10-07T12:00Z');assert.deepEqual(row.wind,[5,null]);assert.deepEqual(row.gust,[null,null]);assert.deepEqual(row.waves,[null,2]);assert.equal(row.period,null);assert.equal(row.swellDirection,'—');assert.ok(row.flags.some(x=>x.includes('gust below')));
});
test('Pacific morning maxima and original 10am snapshots follow both DST transitions from UTC epochs',()=>{
 for(const [start,now,date,ten] of [['2026-03-08T00:00Z','2026-03-07T18:00Z','2026-03-08','2026-03-08T17:00Z'],['2026-11-01T00:00Z','2026-10-31T18:00Z','2026-11-01','2026-11-01T18:00Z']]){
  const p=packets(start,36),index=p.wind.hourly.time.indexOf(epoch(ten)+3*3600);p.wind.hourly.wind_speed_10m_gfs_global[index]=11;p.wind.hourly.wind_gusts_10m_gfs_global[index]=12;p.wave.hourly.wave_height_ncep_gfswave016[index]=5;
  const row=morningRows(p.wind,p.wave,new Date(now)).find(r=>r.date===date);assert.ok(row);assert.equal(row.time,epoch(ten));assert.equal(row.wind[1],11);assert.equal(row.waves[1],5);assert.equal(row.swell,1.5);
  p.wind.hourly.wind_gusts_10m_ecmwf_ifs025[index]=2;const contradictory=morningRows(p.wind,p.wave,new Date(now)).find(r=>r.date===date);assert.equal(contradictory.gust[0],null);assert.ok(contradictory.flags.some(x=>x.includes('gust below')));
  p.wave.hourly.time.splice(p.wave.hourly.time.indexOf(epoch(ten)-3*3600),1);assert.equal(morningRows(p.wind,p.wave,new Date(now)).find(r=>r.date===date).waves[1],null);
 }
});
test('incomplete Pacific mornings and duplicate snapshots are never replaced by a nearby hour',()=>{
 const p=packets('2026-09-24T14:00Z',7);const now=new Date('2026-09-23T15:00Z');assert.equal(morningRows(p.wind,p.wave,now)[0].time,epoch('2026-09-24T17:00Z'));
 p.wind.hourly.time[0]=p.wind.hourly.time[1];const row=morningRows(p.wind,p.wave,now)[0];assert.equal(row.wind[0],null);assert.equal(row.gust[1],null);
 p.wave.hourly.time[4]=p.wave.hourly.time[3];assert.equal(morningRows(p.wind,p.wave,now)[0].swell,null);
});
test('hour/profile/target updates reuse per-root snapshot and preserve requested gaps and access clock',async()=>{
 const p=packets('2026-10-07T12:00Z',3),root={innerHTML:''},counter={count:0},options={at:new Date('2026-10-07T12:00Z'),profile:'boat',target:'reef',fetchImpl:fetcher(p,counter)};
 await updateCoastalForecast(root,point,{name:'Original place'},options);assert.equal(counter.count,2);const access=root.innerHTML.match(/Model output accessed ([^<]+) Pacific/)[1];
 await updateCoastalForecast(root,point,null,{...options,at:new Date('2026-10-07T14:00Z'),profile:'spear',target:'<unknown>'});assert.equal(counter.count,2);assert.match(root.innerHTML,/2026-10-07T14:00:00.000Z/);assert.match(root.innerHTML,/In-water visibility/);assert.match(root.innerHTML,/&lt;unknown&gt;/);assert.equal(root.innerHTML.match(/Model output accessed ([^<]+) Pacific/)[1],access);
 await updateCoastalForecast(root,point,null,{...options,at:new Date('2026-10-11T12:00Z')});assert.match(root.innerHTML,/No exact wind source valid time/);assert.match(root.innerHTML,/exact source epoch missing/);assert.doesNotMatch(root.innerHTML,/2026-10-07T12:00:00.000Z/);disposeCoastalForecast(root);
});
test('independent roots, pending same-place clock updates, navigation and disposal never publish stale replies',async()=>{
 const p=packets('2026-10-07T12:00Z',3),root={innerHTML:''},other={innerHTML:''};let release,calls=0;const held=new Promise(resolve=>{release=resolve;});const slow=async url=>{calls++;await held;return fetcher(p)(url);};
 const first=updateCoastalForecast(root,point,null,{at:new Date('2026-10-07T12:00Z'),fetchImpl:slow});const second=updateCoastalForecast(root,point,null,{at:new Date('2026-10-07T14:00Z'),fetchImpl:slow});assert.equal(calls,2);
 await updateCoastalForecast(other,point,null,{at:new Date('2026-10-07T13:00Z'),fetchImpl:fetcher(p)});assert.match(other.innerHTML,/2026-10-07T13:00:00.000Z/);release();await Promise.all([first,second]);assert.match(root.innerHTML,/2026-10-07T14:00:00.000Z/);
 let releaseAgain;const hold=new Promise(resolve=>{releaseAgain=resolve;});const pending=updateCoastalForecast(root,{latitude:36,longitude:-121},null,{fetchImpl:async url=>{await hold;return fetcher(p)(url);}});disposeCoastalForecast(root);const afterDispose=root.innerHTML;releaseAgain();await pending;assert.equal(root.innerHTML,afterDispose);disposeCoastalForecast(other);
});
test('cached destination cancels a pending different location; distant grids never supply readings',async()=>{
 const p=packets('2026-10-07T12:00Z',3),root={innerHTML:''},opts={at:'2026-10-07T12:00Z',fetchImpl:fetcher(p)};await updateCoastalForecast(root,point,null,opts);
 let release;const hold=new Promise(resolve=>{release=resolve;});const pending=updateCoastalForecast(root,{latitude:36,longitude:-121},{name:'Stale destination'},{...opts,fetchImpl:async url=>{await hold;return fetcher(p)(url);}});await updateCoastalForecast(root,point,{name:'Current destination'},opts);release();await pending;assert.match(root.innerHTML,/Current destination/);assert.doesNotMatch(root.innerHTML,/Stale destination/);
 const distant={wind:{...p.wind,latitude:40},wave:{...p.wave,latitude:40}},other={innerHTML:''};await updateCoastalForecast(other,point,null,{...opts,fetchImpl:fetcher(distant)});assert.match(other.innerHTML,/more than 30 nm/);assert.doesNotMatch(other.innerHTML,/5.0 \/ 5.0 kt/);disposeCoastalForecast(root);disposeCoastalForecast(other);
});
test('UTC requests satisfy the existing server validator and retain provider units even during source outages',async()=>{
 const {answer}=await import('../server/model-api.js');const urls=modelURLs(point.latitude,point.longitude),store={manifest:async()=>null,tile:async()=>{throw Error('Missing publication must not read a tile');}};
 const wind=await answer('forecast',new URL(urls.wind,'https://s.test').searchParams,store,epoch('2026-10-07T12:00Z'));
 const wave=await answer('marine',new URL(urls.wave,'https://s.test').searchParams,store,epoch('2026-10-07T12:00Z'));
 assert.equal(wind.timezone,'UTC');assert.equal(wind.utc_offset_seconds,0);assert.equal(wind.hourly_units.time,'unixtime');assert.equal(wind.hourly_units.wind_speed_10m_ecmwf_ifs025,'kn');assert.equal(wave.hourly_units.wave_height_ecmwf_wam,'ft');assert.equal(wave.hourly_units.swell_wave_period_ncep_gfswave016,'s');
 const selected=selectedHour(wind,wave,'2026-10-07T12:00Z');assert.deepEqual(selected.wind,[null,null]);assert.deepEqual(selected.waves,[null,null]);
 assert.equal(selectedHour(wind,wave,'2026-02-30T12:00Z'),null);
 assert.deepEqual(morningRows(wind,wave,new Date('2026-10-07T12:00Z')).map(row=>row.date),['2026-10-08','2026-10-09','2026-10-10','2026-10-11','2026-10-12','2026-10-13','2026-10-14']);
});

test('suspension prevents late publication during host debounce and allows cached or new updates',async()=>{
 const p=packets('2026-10-07T12:00Z',3),root={innerHTML:''},counter={count:0},opts={at:'2026-10-07T12:00Z',fetchImpl:fetcher(p,counter)};
 await updateCoastalForecast(root,point,{name:'Cached original'},opts);assert.equal(counter.count,2);
 let release,aborted=false;const hold=new Promise(resolve=>{release=resolve;});
 const pending=updateCoastalForecast(root,{latitude:36,longitude:-121},{name:'Obsolete point'},{...opts,fetchImpl:async(url,{signal})=>{signal.addEventListener('abort',()=>aborted=true);await hold;return fetcher(p)(url);}});
 suspendCoastalForecast(root);const suspended=root.innerHTML;assert.equal(aborted,true);release();assert.equal(await pending,false);assert.equal(root.innerHTML,suspended);
 await updateCoastalForecast(root,point,{name:'Resumed cached'},opts);assert.equal(counter.count,2);assert.match(root.innerHTML,/Resumed cached/);
 suspendCoastalForecast(root);await updateCoastalForecast(root,{latitude:35.8,longitude:-121.2},{name:'Resumed new'},opts);assert.equal(counter.count,4);assert.match(root.innerHTML,/Resumed new/);disposeCoastalForecast(root);
});

test('malformed model replies never poison cached hour/profile updates and later valid sources recover',async()=>{
 const p=packets('2026-10-07T12:00Z',3);
 for(const malformed of [null,[],{}, {...p.wind,latitude:null}, {...p.wind,hourly:null}, {...p.wind,hourly:{time:null}}, {...p.wind,hourly_units:null}]){
  const root={innerHTML:''};let calls=0;const bad=async()=>{calls++;return Response.json(malformed);};
  for(const options of [{at:'2026-10-07T12:00Z',profile:'boat'},{at:'2026-10-07T13:00Z',profile:'shore'},{at:'2026-10-07T14:00Z',profile:'spear'}]){assert.equal(await updateCoastalForecast(root,point,null,{...options,fetchImpl:bad}),false);assert.match(root.innerHTML,/Malformed model packet/);assert.match(root.innerHTML,/unknown, not calm/);}
  assert.equal(calls,6,'malformed replies are not reused as admitted snapshots');assert.equal(await updateCoastalForecast(root,point,null,{at:'2026-10-07T13:00Z',fetchImpl:fetcher(p)}),true);assert.match(root.innerHTML,/2026-10-07T13:00:00.000Z/);disposeCoastalForecast(root);
 }
});
