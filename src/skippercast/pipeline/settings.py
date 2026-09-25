"""Resolve provider bindings and jurisdictions before starting network jobs."""
from ..platform.contracts import REPO, ID, load_region, load_catalogs, read_json, within, public_url
from .regulations import validate_bindings, validate_region_binding


def settings(region_id="morro-bay", root=REPO):
    region=load_region(region_id,root)
    _, sources=load_catalogs(root)
    grids={}
    needs={"sst":"sea-temperature","chlorophyll":"chlorophyll","currents":"surface-currents"}
    for kind, ident in region["pipeline_sources"].items():
        source=sources[ident]
        if ident not in region["source_bindings"][needs[kind]] or source["review_status"]!="approved" or source["adapter"] not in ({"erddap-grid", "noaa-ncss-sst"} if kind == "sst" else {"erddap-grid"}):
            raise ValueError("Scheduled grid requires a reviewed, compatible regional binding")
        request=source["request"]
        public_url(request["base_url"])
        grids[kind]={**request,"source_id":ident,"name":source["name"],"adapter":source["adapter"],"documentation_url":source["documentation_url"]}
    jurisdiction_id=region["jurisdiction_id"]
    if not ID.fullmatch(jurisdiction_id): raise ValueError("Invalid jurisdiction id")
    jurisdiction=read_json(within(root,f"jurisdictions/{jurisdiction_id}.json"))
    if jurisdiction["id"]!=jurisdiction_id or jurisdiction["schema_version"]!=1:
        raise ValueError("Jurisdiction mismatch")
    watches={k:dict(v) for k,v in jurisdiction["watches"].items()}
    for watch in watches.values(): public_url(watch['url'])
    harbor=region["harbor"]
    watches['harbor']={'name':harbor['name']+' harbor information','url':public_url(harbor['information_url']),'keywords':harbor['watch_keywords']}
    model_ids=[]
    for need in ("wind-forecast","wave-forecast"):
        for ident in region["source_bindings"][need]:
            source=sources[ident]
            if source["adapter"]=="open-meteo" and source["review_status"]=="approved":
                model_ids.append(source["model"])
    regulations=read_json(within(root/"dist",jurisdiction["regulations_asset"]))
    validate_bindings(jurisdiction, regulations)
    validate_region_binding(jurisdiction, regulations, region)
    regulations["area"]=region["name"]+" · "+region["jurisdiction"]
    return {"region":region,"grids":grids,"watches":watches,"jurisdiction":jurisdiction,
            "regulations":regulations,"model_ids":model_ids}


def previous_for_region(previous, region_id):
    if not previous: return {}
    if previous.get("schema_version")!=1: raise ValueError("Unsupported prior feed")
    # The only pre-region feed was Morro Bay. Never migrate it to another coast.
    if previous.get("region_id", "morro-bay")!=region_id:
        raise ValueError("Previous feed belongs to another region")
    return previous
