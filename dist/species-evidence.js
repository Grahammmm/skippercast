let dossierPromise;
export async function appendSpeciesEvidence(container, species) {
  try {
    dossierPromise ||= fetch("data/species-evidence.json").then(r=>{if(!r.ok) throw new Error();return r.json();});
    const data=await dossierPromise;
    if(container.dataset.speciesEvidence!==species) return;
    const details=document.createElement("details");details.className="source-research";
    const summary=document.createElement("summary");summary.textContent="Research evidence and what would improve it";details.append(summary);
    const profiles=data.species.filter(s=>species==="reef"?["lingcod","rockfish"].includes(s.id):s.id===species);
    for(const p of profiles){
      const h=document.createElement("h3");h.textContent=p.name;details.append(h);
      const stage=document.createElement("p");stage.className="small";stage.textContent=`${p.scientific_name} · ${p.life_stage} · reviewed ${p.reviewed_at}`;details.append(stage);
      for(const claim of p.claims){const text=document.createElement("p");text.textContent=claim.claim;details.append(text);const link=document.createElement("a");link.href=claim.source_url;link.rel="noopener";link.target="_blank";link.textContent="Primary source ↗";details.append(link);}
      for(const [label,value] of [["How this affects the map",p.map_policy],["Depth strategy",p.depth_strategy],["Useful next measurements",p.next_measurements.join("; ")]]){const para=document.createElement("p");const strong=document.createElement("strong");strong.textContent=label+": ";para.append(strong,document.createTextNode(value));details.append(para);}
    }
    container.append(details);
  } catch { /* Existing field notes remain available; a failed fetch invents no new evidence. */ }
}
