# What ships in the SkipperCast Worker

| Question | Offline result |
| --- | --- |
| R1. How big? | **2,883,992 bytes raw; 642,586 bytes gzip**. One JavaScript file, no separate Worker chunks. |
| R2. What does a cold start carry? | Admin, advisor, fleet and coast data/page routers are all registered up front. Together, **748,121 attributed raw bytes** are reached only through those router families, not through the other app or entry-point imports (module-level estimate). |
| R3. What has the most room to move? | **`catalog/sources.json`, 279,310 raw bytes** (9.7% of the output). The repo specifies the deploy entry, not an upload size limit; the headroom below is conditional. |
| R4. What should we watch? | Recommend **3,030,000 raw bytes**, checked after the existing CI build. No build changes in this report. |

Measured offline on 2026-11-21 at staged `origin/main` `26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e` (Node 22.23.2, pnpm 10.34.8, esbuild 0.28.2). This is the repo's esbuild artifact, not a deployed or Wrangler-rebundled payload, and not a measurement of cold-start time. `wrangler.jsonc:8,12–15` separates this file from the browser's `dist/client` assets.

## R1. Bundle composition

The stock `pnpm build` (`package.json:9–10`) produced `dist/server/index.js`. A scratch rerun with esbuild's metafile enabled produced byte-identical output (SHA-256 `cd8f89627cbe0dd98314cf63597c11ae14296f1677636b0a95c06184812049e6`). Gzip is for the whole file, level 9 with a zero timestamp (zlib 1.3); compressed sizes by input are not additive. The metafile lists 564 contributing input entries; esbuild does not attribute every output byte to an input.

| Group | Raw bytes | Basis |
| --- | ---: | --- |
| Server code | 1,207,106 | `server/`, less the HTML literal counted below |
| Catalogue, region and jurisdiction data | 774,087 | `catalog/`, `jurisdictions/`, generated `REGIONS` and `DEPLOYMENT` |
| Compiled 404 | 1,939 | Exact emitted HTML literal including backticks, carved out of the 7,633 bytes for `server/routes/assets.ts`; the source is 1,925 bytes |
| Third-party packages | 773,544 | `node_modules/` |
| Other first-party inputs | 60,754 | Shared `packages/`, `web/`, `dist/boat-handling.js`, package metadata, and build/shell/advisor defines outside the data group |
| Unattributed bytes | 66,562 | File length minus sum of `bytesInOutput` (e.g. generated framing) |
| **Total** | **2,883,992** | `dist/server/index.js` |

The **20 largest metafile inputs**, grouped below, retain their overall ranks. The 404 is broken out separately because esbuild attributes it to its call site, not to `web/404.html`. Package paths omit the pnpm store/version prefix.

| Group | Rank | Input | Raw bytes in output |
| --- | ---: | --- | ---: |
| Server | 6 | `server/advisor/consumer.ts` | 46,113 |
| Server | 7 | `server/advisor/intake/reports.ts` | 44,832 |
| Server | 11 | `server/advisor/media.ts` | 35,085 |
| Server | 13 | `server/routes/advisor.ts` | 29,451 |
| Server | 14 | `server/fleet/registry.ts` | 28,019 |
| Server | 15 | `server/advisor/engine.ts` | 26,735 |
| Server | 16 | `server/advisor/social/publish.ts` | 23,743 |
| Server | 17 | `server/coast-data.ts` | 23,687 |
| Server | 18 | `server/coast-pages.ts` | 23,414 |
| Server | 19 | `server/fleet/activity.ts` | 21,235 |
| Server | 20 | `server/feeds.ts` | 21,190 |
| Data | 1 | `catalog/sources.json` | 279,310 |
| Data | 2 | `<define:REGIONS>` | 217,105 |
| Data | 5 | `catalog/search-methods.json` | 52,304 |
| Data | 9 | `catalog/species.json` | 38,822 |
| Data | 10 | `catalog/advisor/strings.json` | 37,579 |
| Data | 12 | `catalog/advisor/species-pages.json` | 34,159 |
| Third-party | 3 | `@peculiar/x509/build/x509.es.js` | 111,115 |
| Third-party | 4 | `asn1js/build/index.es.js` | 96,863 |
| Third-party | 8 | `reflect-metadata/Reflect.js` | 40,090 |
| Compiled 404 | — | `web/404.html` inside `server/routes/assets.ts` | 1,939 (not an additional metafile input) |

The build reads each `regions/*/region.json` and injects the non-drafts as one object (16 included, 6 draft manifests excluded); it also injects production deployment JSON, the client shell paths and build metadata. The 404 is a string used on the HTML fallback path, not a standalone Worker module (`scripts/build-worker.mjs:9–12,18–34`; `server/config.ts:5–6`; `server/routes/assets.ts:85–89`).

## R2. Code that ships even when its routes are not used

`server/index.ts:2–12,67` imports the app, scheduled and queue code. `server/app.ts:10–44,46–76` creates the router and mounts the families at module scope. The gates decide whether to answer a request; they do not decide what to load. “Rare” here means not needed for the ordinary map shell or core feed route, not a measured traffic share. On a cold invocation that reaches this Worker, the entry bundle is already there regardless of route; warm requests do not reinitialize it on every hit. These are shipped bytes and eager registration, not evidence that every handler runs or that the engine fully parses/compiles each function on the first hit.

| Family | Startup source and request paths | Router input(s) only | All reachable bytes* | Family-only bytes* | Also reached elsewhere* |
| --- | --- | ---: | ---: | ---: | ---: |
| Admin | `server/app.ts:37,63–74`; `server/routes/admin.ts:141–158,217–218,298–349,363`. Role-gated admin pages, `/api/admin/*`, and fleet map. | 16,390 | 993,919 | 110,520 | 883,399 |
| Advisor HTTP | `server/app.ts:26,57–58`; `server/routes/advisor.ts:69–79,136–182,435–443,670–691`. Webhooks, chat/media and public landing/detail pages. Request gates also allow separately enabled pages and fleet boat lookups (`server/advisor/gate.ts:13–16,28–42`). | 29,451 | 1,156,965 | 156,555 | 1,000,410 |
| Fleet | `server/app.ts:27,59–60`; `server/routes/fleet.ts:47–53,107–160`. Feature-gated jobs and `/go/:slug`; the admin and advisor routers also reach fleet modules. | 4,977 | 227,270 | 16,194 | 211,076 |
| Coast data and pages | `server/app.ts:22–23,53–54`; `server/routes/coast.ts:7–15` and `server/routes/coast-pages.ts:9–17`. `/api/coast/*`, `/coast-data/*`, `/report`, `/feed.xml`, `/methodology`, `/about`. | 1,460 | 487,699 | 381,118 | 106,581 |

*Raw byte estimates by module reachability in the actual output, not savings from deleting a route. The method counts a shared module's whole output, even when different routes use different exports. “Family-only” subtracts the other three families and all other entry/app imports (including cron/queue); “also reached elsewhere” is the difference. Do not add the inclusive rows. Their deduplicated union is 1,768,799 bytes, of which 748,121 are outside the other entry/app imports; 83,734 of those bytes are shared between two or more of the four families. In particular, advisor's consumer/engine also have direct queue/cron entry-point paths (`server/index.ts:9–12,30–35,46–58`); splitting only the HTTP router would not move that shared work.

**No separate lazy chunk for any of these routers.** The graph's two dynamic imports are in the common asset handler (`server/routes/assets.ts:119–120`): `config.ts` and `og.ts` for map HTML metadata. Those imports can defer a call or initialization, not remove bytes from this Worker: the build uses one bundled ESM entry, does not ask esbuild to split it, and the metafile reports one output with no output imports (`scripts/build-worker.mjs:33–34`). `config.ts` is also statically imported (for example `server/routes/coast-pages.ts:3`).

## R3. Cloudflare size margin and best candidate

- `wrangler.jsonc:8,12–15` says `"main": "dist/server/index.js"` and `"directory": "dist/client"` for assets. `docs/cloudflare.md:7` says “the Worker (`dist/server/index.js`), the fingerprinted site (`dist/client`)”. Neither file specifies a numerical **Worker upload** cap or establishes the account's plan; `docs/cloudflare.md:22` is about the size of an R2 response cached as one object, not Worker code. Recheck with `git grep -niE 'size|limit|[0-9]+ *Mi?B|gzip|compressed|dist/server' -- wrangler.jsonc docs/cloudflare.md` plus a full read of those files.
- As an **illustrative estimate**, if the Cloudflare upload limits are 3 MB (Free) and 10 MB (Paid), the R1 gzip file has **2,357,414 B** and **9,357,414 B** of room respectively using decimal MB. At 3 and 10 MiB the equivalent margins are 2,503,142 B and 9,843,174 B. These are assumed comparison thresholds, not repo caps or a live validation. Use gzipped upload bytes for that comparison, not the raw-size regression budget below; the deployed bundle and applicable plan were not checked.
- `catalog/sources.json` is the largest individual opportunity (R1), and its sole direct metafile importer is `server/coast-data.ts:10`. `coastFeeds` uses the catalogue to check the source rows behind named feeds (`server/coast-data.ts:200–216`). A build-generated projection of just the required rows/fields, or a separately approved static asset read on the coast path, could move data out of the entry. **279,310 B is the current raw contribution, not a savings estimate**: a replacement still costs bytes and must preserve source eligibility checks and failure behavior. Do not expose the full catalogue as a new public asset by default. A dynamic import alone under today's single-output build would keep the bytes in the entry.

## R4. Recommendation: budget raw startup weight where CI already builds it

Set a proposed cap of **3,030,000 raw bytes** for `dist/server/index.js`: 146,008 B above this baseline (about 5%). Prefer raw here to catch growth in code and data the Worker carries; this is not a Cloudflare upload cap or a timing target. Today's `scripts/startup-budget.json:2–7,14–22` covers browser startup JSON, precache and initial client JS/CSS. `scripts/perf-budget.json:192–255` and `scripts/check_perf_budget.py:45–48,81–116` cover built client files and specific site/data paths, not the Worker.

One optional follow-up, **under two hours**: in `scripts/perf-budget.json` only, add a `worker_bundle` entry of `kind: files`, with `paths: ["dist/server/index.js"]`, `max_bytes: 3030000` and a matching initial history entry. The existing `pnpm build` → `python scripts/check_perf_budget.py` job (`.github/workflows/ci.yml:428–429`) can read it without a workflow or build change. Offline acceptance: build a disposable checkout and run the checker; rerun with `--budget` pointing to a scratch copy whose new cap and history value are 2,883,991. The 2026-11-21 scratch probe passed at 3,030,000 (exit 0) and failed specifically on `Worker bundle (raw)` at 2,883,991 (exit 1); no published config was changed. No bundle restructuring is needed to add this check.

## Reproduce R1–R2 offline

Use a disposable checkout of the measured SHA. Run `pnpm install --offline --frozen-lockfile` and `pnpm build` there. Save the following as `measure-worker.py` **outside the checkout**, then run `python3 ../measure-worker.py` from the disposable checkout root. It runs a scratch sibling copy of the existing build script with only `metafile: true` and a JSON dump added, checks identical bytes, then reads the graph. No source edits in the reporting checkout.

```python
import gzip, json, subprocess
from pathlib import Path

entry = 'dist/server/index.js'
stock = Path(entry).read_bytes()
s = Path('scripts/build-worker.mjs').read_text()
needle = 'await build({entryPoints:'
assert s.count(needle) == 1
s = s.replace(needle, 'const result = await build({metafile:true,entryPoints:')
s += "\n(await import('node:fs')).writeFileSync('../worker-meta.json', JSON.stringify(result.metafile));\n"
probe = Path('scripts/measure-worker.mjs')
probe.write_text(s)
subprocess.run(['node', str(probe)], check=True)
assert stock == Path(entry).read_bytes()
m = json.loads(Path('../worker-meta.json').read_text())
assert list(m['outputs']) == [entry] and not m['outputs'][entry]['imports']
w = {p: v['bytesInOutput'] for p, v in m['outputs'][entry]['inputs'].items()}
print('raw, gzip, unattributed', len(stock), len(gzip.compress(stock, 9, mtime=0)), len(stock)-sum(w.values()))
print(*sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))[:20], sep='\n')
prefix = b'return new Response(`<!doctype html>'
assert stock.count(prefix) == 1
lo = stock.index(prefix) + len(b'return new Response(')
hi = stock.index(b'`, { status: 404,', lo) + 1
html = hi - lo
server = sum(v for p, v in w.items() if p.startswith('server/')) - html
data = sum(v for p, v in w.items()
           if p.startswith(('catalog/', 'jurisdictions/')) or p in ('<define:REGIONS>', '<define:DEPLOYMENT>'))
third_party = sum(v for p, v in w.items() if p.startswith('node_modules/'))
print('server, data, HTML, third-party, other', server, data, html, third_party,
      sum(w.values()) - server - data - html - third_party)

inputs = m['inputs']
def edges(p):
    return {i['path'] for i in inputs[p]['imports'] if not i.get('external') and i['path'] in inputs}

def closure(roots):
    seen, todo = set(), set(roots)
    while todo:
        p = todo.pop()
        seen.add(p)
        todo.update(edges(p) - seen)
    return seen

def weight(paths):
    return sum(w.get(p, 0) for p in paths)

roots = [{f'server/routes/{name}.ts' for name in names} for names in
         [('admin',), ('advisor',), ('fleet',), ('coast', 'coast-pages')]]
sets = [closure(r) for r in roots]
core = closure((edges('server/app.ts') - set.union(*roots)) |
               (edges('server/index.ts') - {'server/app.ts'}))
for i, paths in enumerate(sets):
    only = paths - core - set.union(*(s for j, s in enumerate(sets) if i != j))
    print(weight(roots[i]), weight(paths), weight(only), weight(paths - only))
all_routes = set.union(*sets)
print(weight(all_routes), weight(all_routes - core))
print([(p, i['path']) for p, info in inputs.items() for i in info['imports']
       if i['kind'] == 'dynamic-import'])
```
