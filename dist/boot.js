import { initRegion } from "./region.js?v=8.6";
try {
  await initRegion();
  await import("./app.js?v=8.6");
} catch(error) {
  const panel=document.getElementById("map-empty");panel.hidden=false;
  panel.replaceChildren();const title=document.createElement("strong");title.textContent="This region could not load";
  const reason=document.createElement("p");reason.textContent=error.message;
  const retry=document.createElement("a");retry.href="/?region=morro-bay#map";retry.textContent="Open Morro Bay";
  panel.append(title,reason,retry);console.error(error);
}
