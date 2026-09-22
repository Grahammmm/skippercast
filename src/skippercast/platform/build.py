"""Compile reviewed regional configuration into versioned public packages."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from .contracts import REPO, atomic_json, load_catalogs, load_region, read_json, requirement_report, within
from ..pipeline.regulations import validate_bindings, validate_region_binding, regulatory_snapshot
from datetime import datetime, timezone


def validate_regional_rules(region, root):
    jurisdiction = read_json(within(root, f"jurisdictions/{region['jurisdiction_id']}.json"))
    registry = read_json(within(root / 'dist', jurisdiction['regulations_asset']))
    validate_bindings(jurisdiction, registry)
    validate_region_binding(jurisdiction, registry, region)
    snapshot = regulatory_snapshot({}, datetime.now(timezone.utc), registry)
    if snapshot['rules_review_status'] != 'reviewed':
        raise ValueError('Changed regulatory content needs an explicit review decision before publishing')
    region['regulatory_authority_hosts'] = jurisdiction['authority_hosts']


def build(root=REPO):
    root = Path(root)
    needs, sources = load_catalogs(root)
    entries = []
    targets = read_json(root / 'catalog/targets.json')['targets']
    for path in sorted((root / "regions").glob("*/region.json")):
        region = load_region(path.parent.name, root)
        if region["status"] == "draft":
            continue
        validate_regional_rules(region, root)
        if not set(region['species']) <= targets.keys():
            raise ValueError('Every regional selector needs a reviewed target definition')
        region['target_options'] = [{ 'id': ident, **targets[ident]} for ident in region['species']]
        output = root / "dist/regions" / region["id"]
        output.mkdir(parents=True, exist_ok=True)
        ecology_id=region.get('intelligence',{}).get('ecology_profile')
        if ecology_id:
            ecology=read_json(within(root/'catalog/ecology',ecology_id+'.json'))
            if region['jurisdiction_id'] not in ecology['jurisdictions'] or not set(region['species'])<=ecology['profiles'].keys():
                raise ValueError('Ecology dossier does not cover this jurisdiction and species set')
            eb=ecology['bounds'];rb=region['fishing_bounds']
            if not (eb[0]<=rb[0]<rb[2]<=eb[2] and eb[1]<=rb[1]<rb[3]<=eb[3]):
                raise ValueError('Ecology evidence cannot silently transfer outside its reviewed geography')
            dossier=read_json(root/'catalog/species.json')
            for profile in ecology['profiles'].values():
                profile['sources']=[p for p in dossier['species'] if p['id'] in profile['source_species']]
                if len(profile['sources'])!=len(profile['source_species']):raise ValueError('Missing species evidence source')
            atomic_json(within(root/'dist',region['assets']['ecology']),{**ecology,'region_id':region['id']})
        # A new region may publish context with explicit empty target collections.
        for key, empty in (("atlas", {"schema_version": 1, "targets": [], "areas": [], "drifts": [], "sources": []}),
                           ("habitats", {"schema_version": 1, "areas": []}),
                           ("bottom_index", {"schema_version": 1, "views": {}, "sources": {}})):
            asset = within(root / "dist", region["assets"][key])
            if not asset.exists() and region["status"] == "preview":
                atomic_json(asset, {**empty, "region_id": region["id"], "note": region["coverage_note"]})
        assets = {}
        for key, value in region["assets"].items():
            if value is None:
                continue
            asset = within(root / "dist", value)
            if not asset.is_file():
                raise ValueError(f"Missing published asset for {region['id']}: {value}")
            assets[key] = {"path": value, "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(), "bytes": asset.stat().st_size}
        report = requirement_report(region, root)
        atlas = read_json(within(root / "dist", region["assets"]["atlas"]))
        if atlas["targets"] and not report["capabilities"]["surveyed-bottom-targets"]["ready"]:
            raise ValueError("Fishing targets cannot be published before their source requirements are met")
        west, south, east, north = region["fishing_bounds"]
        ids=set()
        for target in atlas["targets"]:
            if target["id"] in ids: raise ValueError("Duplicate target identity")
            ids.add(target["id"])
            if not west <= target["longitude"] <= east or not south <= target["latitude"] <= north:
                raise ValueError("Fishing target lies outside the region's fishing extent")
            if target["neighborhood_depth_ft"][1] > region["boat"]["bottom_depth_limit_ft"]:
                raise ValueError("Target exceeds the configured fishing depth limit")
        report["published_targets"] = len(atlas["targets"])
        report["published_bottom_views"] = sum(v["status"] == "surveyed" for v in read_json(within(root / "dist", region["assets"]["bottom_index"]))["views"].values())
        atomic_json(output / "coverage.json", report)
        atomic_json(output / "region.json", region)
        receipt = atomic_json(output / "manifest.json", {"schema_version": 1, "region_id": region["id"], "assets": assets})
        entries.append({"id": region["id"], "name": region["name"], "status": region["status"], "config": f"regions/{region['id']}/region.json", "manifest": receipt["sha256"]})
    atomic_json(root / "dist/regions/index.json", {"schema_version": 1, "default_region": "morro-bay", "regions": entries})
    default = load_region("morro-bay", root)
    validate_regional_rules(default, root)
    default['target_options'] = [{'id': ident, **targets[ident]} for ident in default['species']]
    (root / "dist/region-default.js").write_text("// Generated by skippercast.platform.build; edit regions/morro-bay/region.json.\nexport default " + json.dumps(default, separators=(",", ":")) + ";\n")
    atomic_json(root / "dist/data/source-catalog.json", {"schema_version": 1, "needs": list(needs.values()), "sources": list(sources.values())})
    if (root / "catalog/species.json").exists():
        shutil.copyfile(root / "catalog/species.json", root / "dist/data/species-evidence.json")
    return entries


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=REPO)
    print(json.dumps(build(p.parse_args().root), indent=2))
