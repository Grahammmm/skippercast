// Notification delivery only. No stale offline weather cache is implied.
self.addEventListener('push',event=>{
  let data;try{data=event.data?.json();}catch{return;}
  if(!data?.eventId||!data.body)return;
  event.waitUntil(self.registration.showNotification(data.title||'SkipperCast',{body:data.body,tag:data.eventId,renotify:false,data:{url:'/#forecast'},icon:'/app-icon.svg'}));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();event.waitUntil((async()=>{const windows=await clients.matchAll({type:'window',includeUncontrolled:true});const target=windows.find(w=>new URL(w.url).origin===self.location.origin);if(target){await target.navigate('/#forecast');return target.focus();}return clients.openWindow('/#forecast');})());
});
