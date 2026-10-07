import {effect} from '@preact/signals';
import {region,coast,species,hour,profile} from '../web/state.ts';
import {coastURL} from '../packages/coast/src/links.ts';
const link=document.getElementById('coast-relief-link');
function update(){const url=coastURL(location.href);if(!url.searchParams.has('place')&&!url.searchParams.has('region')&&!url.searchParams.has('coast'))url.searchParams.set('place','morro');link.hidden=!url.searchParams.has('place');url.pathname='/coast';url.hash='';link.href=url.href;}
effect(()=>{region.value;coast.value;species.value;hour.value;profile.value;update();});window.addEventListener('popstate',update);
