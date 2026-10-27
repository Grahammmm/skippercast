// BODY09 rendered acceptance candidate. NOT RUN by its author. Execute only
// after exact-source review, final-source binding and a separate surviving run grant.
// Actual Reports -> CatchCards -> CoastMarkup -> catchSheet; no replacement count DOM.
import {test, expect, type Locator, type Page, type TestInfo} from '@playwright/test';
import {build, type Plugin} from 'esbuild';
import {readFileSync} from 'node:fs';
import {resolve, relative} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {coastReportFixture} from './coast-report-fixture.ts';
import {backingContrast, pngPixels} from './p04-paint-evidence.ts';

const ROOT = resolve(import.meta.dirname, '..');
const ORIGIN = 'http://p04-body09.test';
const NOW = new Date('2026-10-08T19:00:00Z');
const hash = (b: string | Buffer) => createHash('sha256').update(b).digest('hex');
const read = (p: string) => readFileSync(resolve(ROOT, p));
const STYLES = ['web/tokens.css', 'web/ui/ui.css', 'web/app/app.css', 'packages/coast/panel.css', 'packages/coast/tokens-bridge.css'];
const FONTS = ['web/fonts/dm-sans-latin.woff2', 'web/fonts/jetbrains-mono-latin.woff2'];
const INPUTS = [...STYLES, ...FONTS, 'web/species.ts', 'web/app/App.tsx', 'web/app/Masthead.tsx', 'web/app/LayerRail.tsx', 'web/app/MapStage.tsx', 'web/app/views/Reports.tsx', 'web/app/CoastMarkup.tsx',
  'packages/coast/src/ui/catches.ts', 'packages/coast/src/counties.ts', 'web/coast-data.ts',
  'scripts/check_contrast.mjs', 'package.json', 'pnpm-lock.yaml', 'e2e/coast-report-fixture.ts',
  'e2e/p04-catch-contrast.spec.ts', 'e2e/p04-paint-evidence.ts', 'e2e/p04-catch.config.ts'];
// Immutable named-source bindings from the reviewed base. Fixture/self hashes
// are recorded below and additionally bound by task85's sealed execution packet.
// Applicability review, #696 (ranked trip spots legend row): app.css adds only a
// `.app-swatch[data-layer="trip-ranked"]` rule, which the Reports catch flow never
// renders; check_contrast.mjs changes only SURFACE_SOURCE_SHA256 and its line
// citations, not `contrast()`, the one export this spec reads. Both rebound.
// #697 (legend survey summary): check_contrast.mjs changes only the Legend.tsx hash; rebound.
// FE-61 part 3 group 2: panel.css drops only the v1 literal fallbacks of bridged --coast-* roles (the host always
// applies tokens-bridge.css, so they never render); check_contrast.mjs rebinds that hash and its catch contract's
// fallback-free forms, with catch and surface results unchanged and contrast() untouched. Both rebound.
// FE-61 Accept 2: check_contrast.mjs drops only the retired v1 dist/tokens.css spec, its pairs and the v1 defaults
// (now web/tokens.css); contrast(), the one export this spec reads, is unchanged. Rebound.
// #711 (legend ramp tokens): web/tokens.css adds only theme-invariant cartography ramps (--bathy-*, --current-*, --reef-*,
// --reef-fit-*, --shore-*, --wave-*) after --mpa-line, tokens-bridge.css maps --coast-<ramp>-N onto them after
// --coast-sst-5 (cited lines unchanged), panel.css drops those 26 ramp fallbacks in place; none is a Reports catch
// colour. check_contrast.mjs rebinds only those three hashes, with catch and surface results unchanged and
// contrast() untouched. All four rebound.
// #711 part B (chart series): tokens-bridge.css adds only --coast-series-gust and --coast-series-violet before
// --coast-sans (cited lines unchanged); no Reports catch colour. check_contrast.mjs rebinds only that hash, with catch
// and surface results unchanged and contrast() untouched. Both rebound.
// #730 (npm-minor-and-patch group): package.json and pnpm-lock.yaml change only dependency version pins
// (maplibre-gl 6.12.0->6.14.0, drizzle-orm, @axe-core/playwright, @cloudflare/workers-types, @playwright/test,
// preact-render-to-string, vite). No CSS/TSX source in INPUTS, and not check_contrast.mjs's contrast(), is touched;
// the Reports catch flow and its contrast results are unchanged. package.json and pnpm-lock.yaml rebound.
// CI6-09 (swell partition selector): Legend.tsx gains an existing Segmented control; no paint chain changes.
// check_contrast.mjs changes only the Legend.tsx hash and line citations, not contrast(). Rebound.
// CI6-08 chlorophyll: MapStage adds only the createChlorophyll layer; check_contrast.mjs changes only the
// legendTsx source hash and citations, leaving contrast() untouched. Both rebound.
// CI6-13 (shelf depth contours): app.css adds only the two depth-contour legend swatch rules and joins the
// contour row to the wrapping legend rows; MapStage.tsx only adds createDepthContours to the Chart's layers. The
// Reports catch flow renders neither, and check_contrast.mjs rebinds only the surface-proof hashes and cited lines
// (moved, byte-identical), with contrast() untouched. All three rebound.
// CI6-17 (tide station selection): App.tsx only configures the tide selector
// from region metadata; the Reports catch flow and its contrast results are unaffected.
// CI6-03 (Temp contrast layer): web/tokens.css adds only theme-invariant --contrast-0/1/2 after --swell-3; app.css
// adds only `.app-legend-sst-contrast` to an existing flex-wrap rule and an `.app-swatch[data-layer="sst-contrast"]`
// rule; MapStage.tsx adds only the createContrast chart layer. The Reports catch flow mounts none of them.
// check_contrast.mjs rebinds only the tokens/app/Legend surface hashes and their shifted line citations, with
// surface results unchanged and contrast() untouched. All four rebound.
// CI6-13 merge-forward onto CI6-03: the union of both entries above and nothing else. app.css carries both sides'
// rules unchanged; MapStage.tsx adds both chart layers; check_contrast.mjs rebinds the union's surface hashes and
// shifted line citations, with contrast() untouched. All four rebound.
// CI6-10 wind adds a chart-only createWind factory to MapStage; Reports does not mount it. The reviewed contrast()
// implementation and this test's rendered catch path are unchanged; MapStage and check_contrast source hashes rebound.
// Wind/contour merge-forward retains all three factories and both legend rows; only union hashes/line citations rebound.
// Chlorophyll merge-forward preserves Temp contrast, wind and depth contours; only union hashes and line citations change.
// CI6-18: MapStage.tsx adds the Stations chart renderer; BODY09 mounts Reports/CatchCards only, never MapStage.
// Legend.tsx adds station legend markup/basis/list and app.css adds layout rules scoped to that row; neither
// changes Reports catch count paint or its backdrop. check_contrast.mjs only rebinds the Legend source hash.
// Verified applicability: BODY09's rendered flow, sampled elements, paint, thresholds and surface checks are unchanged.
// CI6-18 merge-forward: union of the entries above, contrast() untouched.
// CI6-14: MapStage.tsx imports waypoint placement state and adds a Chart-only placement note/cancel button.
// BODY09 mounts Reports/CatchCards, not PresentationToggle; catch count paint and its backdrop are unchanged.
// Only the MapStage source hash is rebound; rendered checks, thresholds and contrast() are unchanged.
// CI6-08 x CI6-18 merge-forward: MapStage keeps createChlorophyll and createStations; Legend keeps both rows;
// only union hashes and line citations rebound, contrast() untouched.
// CI6-08 x CI6-14 merge-forward keeps createChlorophyll and the placement note; only the union hash is rebound.
// CI6-09 merge-forward retains the partition selector alongside wind, shelf contours, chlorophyll and Stations.
// Legend.tsx changes only the selector import/control from main; existing text/muted glass roles and the Reports
// catch path are unchanged. check_contrast.mjs rebinds only the Legend hash and line citations; contrast() is untouched.
// COAST C3 rights adapter: package.json adds only a `check` script alias for `pnpm typecheck`; no dependency,
// build or served asset changes, and the Reports catch path is untouched. Only the package.json hash is rebound.
const REVIEWED_SOURCE_INPUTS: Record<string, string> = {
  "web/species.ts": "c12ff47e9043360709771993682734f3fb56bccc8b8713a6a1e62c6d4ceb2a2d",
  "web/app/App.tsx": "d8486f26dafbb97b0499cd7ef536c386c446c1b002c44b219d42151a5ab11446",
  "web/app/Masthead.tsx": "191309f6c9a54ee6bd24608a1983c6bf07141538267f87bef163f8ad4ccbea00",
  "web/app/LayerRail.tsx": "18db08dcba921446038b48d24552c0e756cba3fc52ecdbd005013521caf2566c",
  "web/app/MapStage.tsx": "b33b7cb5c6e8abb5c1050acd694073c26b705259ffdc1ce0034db9cb87470fe6",
  "web/tokens.css": "41cd0ad0581c0efd8374e4dec8cd44daf41db0e09a64980735547962273517b8",
  "web/ui/ui.css": "44666b0864845a575b3baf6ecdbcccf7340fe9d2df1d54c01e21f593095dfd2e",  // #600: only .ui-icon-button min sizes changed; the catch sheet has no icon button
  "web/app/app.css": "4a3867af18c9eba3eb01391e84380a8052177bb8b841b4928f72287b2ef4dbd5",
  "packages/coast/panel.css": "fda5b83480f2c32243d5ff90b99e2581d459a46f88543d6a264705bdc8e821fb",
  "packages/coast/tokens-bridge.css": "8ea4a379a3e516817d4472ad434da797482c4b96e07697aa29269464f433e6d5",
  "web/fonts/dm-sans-latin.woff2": "9fea608a947e67020c33cad9a6fe3d60c54119dfb8cff87768a8117a15ed7543",
  "web/fonts/jetbrains-mono-latin.woff2": "83c005d49d8a6a50474c73a5a36ac0468076e9c4a29da7bdb14995d80560a5be",
  "web/app/views/Reports.tsx": "8ef399a5024b6bf2b232934647c40029674e8f661ea3391b037460ca66246af1",
  "web/app/CoastMarkup.tsx": "3d318379ff1194b26f68adadb523db08c21829ff71cf5e7cfe2ac903821f0efc",
  "packages/coast/src/ui/catches.ts": "bb8b97124e3b116a81e4b2f2c651c661dba2e064f9bbdfe903781ec1a6d6ea1e",
  "packages/coast/src/counties.ts": "975f2de9b300bf290841cabb061478080b2b61cf44154c83484a2ea9c1851ba2",
  "web/coast-data.ts": "ca649d7b3583777985bcb062614fd4ab7d6dbe97c3bc709a99b524dbd27e7d25",
  "scripts/check_contrast.mjs": "1701f0ae0b6283f517c97b5fd5582c25400705b3f0101a0f24e79173a3af0c83",
  "package.json": "714c1869b08a1bb2c915406050167c41ea9c57431f2fef5449b4ea8c6d3f080b",
  "pnpm-lock.yaml": "68b00d873cb91ed71fb473d7145c31127602dfd3073ed847c0fbef7795dcc153",
  "e2e/coast-report-fixture.ts": "2746e2ac1ff9fbce2a96925a7088180e682060e79dfb1330efea4ac0e2ca65c1"
};
function qualifiedInputs() {
  const actual = Object.fromEntries(INPUTS.map(p => [p, hash(read(p))]));
  expect(Object.fromEntries(Object.keys(REVIEWED_SOURCE_INPUTS).map(p => [p,actual[p]])),
    'reviewed source bindings; changed final source requires applicability review').toEqual(REVIEWED_SOURCE_INPUTS);
  const path = process.env.P04_BODY09_INPUT_MANIFEST;
  if (path) {
    const expected = JSON.parse(readFileSync(path, 'utf8')) as Record<string,string>;
    expect(Object.keys(expected).sort()).toEqual([...INPUTS].sort());
    expect(actual, 'operator sealed exact final fixture/resource inputs').toEqual(expected);
  }
  return {manifestPath: path ?? null, manifestSha256: path ? hash(readFileSync(path)) : null, inputs: actual};
}
const urlImports: Plugin = {name: 'p04-production-url-assets', setup(b) {
  b.onResolve({filter: /\?url$/}, args => ({path: resolve(args.resolveDir, args.path.replace(/\?url$/, '')), namespace: 'p04-url'}));
  b.onLoad({filter: /.*/, namespace: 'p04-url'}, args => {
    const p = relative(ROOT, args.path).replaceAll('\\', '/');
    if (!STYLES.includes(p)) throw Error('Unqualified production URL asset ' + p);
    return {contents: `export default ${JSON.stringify('/' + p)};`, loader: 'js'};
  });
  // Same deferred renderer seam as existing Reports/coast-markup fixtures.
  // Reports never mounts either GPU factory. Fail if either is actually requested.
  b.onResolve({filter: /^\.\/(?:map\/)?(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}));
}};
async function productionBundle() {
  const result = await build({stdin: {resolveDir: ROOT, loader: 'tsx', contents: `
    import {h, render} from 'preact';
    import {Reports, reportsData} from './web/app/views/Reports.tsx';
    import {coastData, coastReport} from './web/coast-data.ts';
    import {region, profile, species, configureStore, startURLSync} from './web/state.ts';
    window.mountP04Reports = async () => {
      configureStore({v2:true,storage:null});startURLSync();
      const now = new Date(${JSON.stringify(NOW.toISOString())});
      if(region.value !== 'morro-bay' || profile.value !== 'boat' || species.value !== 'lingcod') throw Error('Wrong Reports URL state');
      reportsData.value = {key: 'morro-bay:lingcod', data: {evidence:null,
        discussions:{status:'unavailable', candidates:[], checkedQueries:0, totalQueries:0}, watch:null, charters:null}};
      coastData.setPlace({regionId:'morro-bay', point:{latitude:35.34,longitude:-120.97},
        localAreas:[{id:'estero-bay',bounds:[-122,34,-120,36]}], profile:'boat',target:'lingcod',at:now});
      await coastData.load('report');
      if(!coastReport.value) throw Error('Synthetic report was not admitted by the real coast client');
      render(h(Reports,{now}), document.getElementById('mount'));
      window.p04ReportGeneratedAt = coastReport.value.data.generatedAt;
    };`},
    bundle: true, write: false, metafile: true, format: 'iife', platform: 'browser',
    logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [urlImports],
  });
  const moduleInputs = Object.fromEntries(Object.keys(result.metafile!.inputs)
    .filter(p => p !== '<stdin>' && !p.startsWith('p04-url:'))
    .map(p => [p, hash(readFileSync(resolve(ROOT, p)))]));
  return {script: result.outputFiles[0]!.text, moduleInputs};
}

// Entire DOM/ancestor and hit-test audit is re-used for controls. Unsupported
// paint/occlusion fails closed; it is never discarded as a sample to make green.
async function audit(row: Locator) {
  return row.evaluate(element => {
    const dd = element.querySelector('dd')!, bar = element.querySelector<HTMLElement>('.catch-bar')!;
    const shadow = element.getRootNode() as ShadowRoot, host = shadow.host as HTMLElement;
    const rect = (e: Element) => {const b = e.getBoundingClientRect(); return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
    const rgba = (colour: string) => {const canvas = document.createElement('canvas');canvas.width=canvas.height=1;
      const c=canvas.getContext('2d')!;c.fillStyle=colour;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data];};
    const token = (name: string) => rgba(getComputedStyle(host).getPropertyValue(name).trim());
    const composedParent = (e: Element): Element | null => e.parentElement ?? ((e.getRootNode() as ShadowRoot).host ?? null);
    const describe = (e: Element) => e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).trim().replaceAll(' ', '.') : '');
    const issues: string[] = [], chain: Record<string, string>[] = [];
    const ancestors = new Set<Element>();
    for (let node: Element | null = dd; node; node = composedParent(node)) {
      ancestors.add(node);
      const s = getComputedStyle(node);
      const p = {element:describe(node), color:s.color, background:s.backgroundColor, image:s.backgroundImage,
        opacity:s.opacity, filter:s.filter, backdropFilter:s.backdropFilter, mixBlendMode:s.mixBlendMode,
        transform:s.transform, visibility:s.visibility, display:s.display, textShadow:s.textShadow,
        clipPath:s.clipPath, maskImage:s.maskImage, overflow:s.overflow, zIndex:s.zIndex};
      chain.push(p);
      if (s.opacity !== '1' || s.filter !== 'none' || s.backdropFilter !== 'none' || s.mixBlendMode !== 'normal' || s.transform !== 'none'
        || s.visibility !== 'visible' || s.display === 'none' || s.clipPath !== 'none' || s.maskImage !== 'none') issues.push('unsupported_ancestor:' + describe(node));
      if (s.textShadow !== 'none') issues.push('text_shadow:' + describe(node));
      if (s.backgroundImage !== 'none') issues.push('unexpected_ancestor_background:' + describe(node));
      for (const pseudo of ['::before','::after']) {
        const ps = getComputedStyle(node, pseudo);
        if (ps.content !== 'none' && ps.content !== 'normal' && ps.display !== 'none') issues.push('unqualified_pseudo:' + describe(node) + pseudo);
      }
    }
    const sheets = [...shadow.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].map(l => ({href:l.href, loaded:!!l.sheet,disabled:l.disabled}));
    if (sheets.length !== 2 || sheets.some(l => !l.loaded || l.disabled) || !sheets.some(l => l.href.endsWith('/packages/coast/panel.css'))
      || !sheets.some(l => l.href.endsWith('/packages/coast/tokens-bridge.css'))) issues.push('bridge_or_panel_not_loaded');
    if (host.dataset.coastTheme !== 'tokens') issues.push('missing_token_optin');
    const ds=getComputedStyle(dd), rs=getComputedStyle(element), bs=getComputedStyle(bar);
    const foreground=rgba(ds.color), panel=token('--panel'), mint=token('--mint');
    if (foreground.join() !== mint.join()) issues.push('count_foreground_not_mint');
    if (rgba(rs.backgroundColor).join() !== panel.join() || panel[3] !== 255) issues.push('row_background_not_opaque_panel');
    if (ds.backgroundImage !== 'none' || rgba(ds.backgroundColor)[3] !== 0) issues.push('unqualified_dd_background');
    // Browser resolves the declared production gradient against the actual host tokens.
    const probe=document.createElement('i');probe.style.cssText='position:absolute;left:-10000px;';
    probe.style.backgroundImage='linear-gradient(90deg in srgb, var(--coast-mint-wash), var(--coast-panel))';
    shadow.append(probe);const expectedGradient=getComputedStyle(probe).backgroundImage;probe.remove();
    if (expectedGradient === 'none' || bs.backgroundImage !== expectedGradient) issues.push('gradient_cascade_mismatch');
    if (bs.opacity !== '1' || bs.filter !== 'none' || bs.mixBlendMode !== 'normal' || bs.transform !== 'none' || bs.backdropFilter !== 'none') issues.push('unsupported_bar_paint');
    if (bs.display === 'none' || bs.visibility !== 'visible') issues.push('bar_hidden');
    if (bs.position !== 'absolute' || bs.zIndex !== 'auto' || ds.position !== 'relative' || ds.zIndex !== 'auto'
      || !(bar.compareDocumentPosition(dd) & Node.DOCUMENT_POSITION_FOLLOWING) || rs.overflow !== 'hidden') issues.push('unqualified_paint_order');
    if (!document.fonts.check('12px "JetBrains Mono"') || !ds.fontFamily.includes('JetBrains Mono')) issues.push('count_font_unloaded');
    const range=document.createRange();range.selectNodeContents(dd);const text=range.getBoundingClientRect();
    const boxes={row:rect(element),dd:rect(dd),bar:rect(bar),text:{x:text.x,y:text.y,width:text.width,height:text.height,right:text.right,bottom:text.bottom}};
    const deep = (x:number,y:number) => {let e=document.elementFromPoint(x,y);while(e?.shadowRoot){const next=e.shadowRoot.elementFromPoint(x,y);if(!next||next===e)break;e=next;}return e;};
    const hits=[];
    for (const fx of [.1,.5,.9]) for (const fy of [.2,.5,.8]) {
      const x=text.x+text.width*fx,y=text.y+text.height*fy,top=deep(x,y);
      const ok=!!top&&(top===dd||dd.contains(top));hits.push({x,y,top:top?describe(top):null,ok});if(!ok)issues.push('count_occluded');
    }
    if (text.width <= 0 || text.height <= 0 || text.x < 0 || text.y < 0 || text.right > innerWidth || text.bottom > innerHeight) issues.push('count_outside_viewport');
    // Geometry also catches pointer-events:none overlays that hit-testing alone cannot see.
    const overlaps: Record<string,unknown>[]=[];
    const visit=(root:Document|ShadowRoot) => {
      for(const e of root.querySelectorAll('*')) {
        if(e.shadowRoot)visit(e.shadowRoot);
        if(ancestors.has(e)||dd.contains(e)||e===bar)continue;
        const b=e.getBoundingClientRect(),s=getComputedStyle(e);
        if(s.display==='none'||s.visibility!=='visible'||Number(s.opacity)===0)continue;
        if(Math.min(b.right,text.right)<=Math.max(b.left,text.left)||Math.min(b.bottom,text.bottom)<=Math.max(b.top,text.top))continue;
        const painted=rgba(s.backgroundColor)[3]!==0||s.backgroundImage!=='none'||!!e.textContent?.trim()||e instanceof SVGElement||['IMG','CANVAS','VIDEO'].includes(e.tagName);
        if(painted){overlaps.push({element:describe(e),box:rect(e),background:s.backgroundColor,image:s.backgroundImage,opacity:s.opacity,pointerEvents:s.pointerEvents,zIndex:s.zIndex});issues.push('unexpected_overlap');}
      }
    };
    visit(document);
    const overlap=Math.max(0,Math.min(boxes.bar.right,text.right)-Math.max(boxes.bar.x,text.x));
    return {issues:[...new Set(issues)],text:dd.textContent,theme:document.documentElement.dataset.theme,
      foreground,panel,mint,gradient:bs.backgroundImage,expectedGradient,barComputed:{position:bs.position,zIndex:bs.zIndex,opacity:bs.opacity,filter:bs.filter},
      rowComputed:{overflow:rs.overflow,borderRadius:rs.borderRadius},countComputed:{font:ds.font,color:ds.color,position:ds.position,zIndex:ds.zIndex},
      boxes,textBarOverlapFraction:overlap/text.width,ancestors:chain,hitTests:hits,overlaps,sheets};
  });
}
async function evidence(page: Page, row: Locator, info: TestInfo, name: string) {
  await row.scrollIntoViewIfNeeded();
  await expect(row.locator('dd')).toBeVisible();
  const before=await audit(row);
  expect(before.issues, name + ' paint and visibility contract').toEqual([]);
  // Viewport screenshots and getBoundingClientRect share CSS-pixel coordinates.
  const viewport=page.viewportSize();
  expect(viewport, name+' configured viewport is required').not.toBeNull();
  const layout=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scale:visualViewport?.scale??null}));
  expect({width:layout.width,height:layout.height}, name+' layout coordinates equal capture viewport').toEqual(viewport);
  expect(layout.scale, name+' no mobile shrink-to-fit or pinch zoom').toBe(1);
  const visible=await page.screenshot({scale:'css',animations:'disabled'});
  const visiblePixels=pngPixels(visible);
  expect({width:visiblePixels.width,height:visiblePixels.height}, name+' visible PNG uses viewport CSS pixels').toEqual(viewport);
  await info.attach(name+'-visible',{body:visible,contentType:'image/png'});
  // Observe the actual backing behind the glyph bounds. Only glyph colour is
  // temporarily transparent; no backing, gradient, layout or ancestor is replaced.
  const style=await row.locator('dd').getAttribute('style');
  let backing: Buffer;
  try {
    await row.locator('dd').evaluate(e => (e as HTMLElement).style.setProperty('color','transparent','important'));
    backing=await page.screenshot({scale:'css',animations:'disabled'});
  } finally {
    await row.locator('dd').evaluate((e,original) => {if(original===null)e.removeAttribute('style');else e.setAttribute('style',original);},style);
  }
  const after=await audit(row);
  expect(after, name+' exact restored production paint').toEqual(before);
  const text=before.boxes.text;
  const backingPixels=pngPixels(backing!);
  expect({width:backingPixels.width,height:backingPixels.height}, name+' backing PNG uses viewport CSS pixels').toEqual(viewport);
  const measured=backingContrast(backing!,before.foreground,{x:text.x,y:text.y,width:text.width,height:text.height});
  await info.attach(name+'-glyph-free-backing',{body:backing!,contentType:'image/png'});
  await info.attach(name+'-computed-and-pixels',{body:JSON.stringify({before,after,viewport,
    visibleSha256:hash(visible),backingSha256:hash(backing!),measured,
    method:'Primary image is real production UI; secondary image temporarily clears dd glyph colour only, then exact computed state is restored. Ratios use computed opaque foreground and every whole backing pixel beneath text rectangle.'},null,2),contentType:'application/json'});
  expect(measured.samples).toBeGreaterThan(0);
  expect(measured.minimum, name+' actual backing-pixel contrast').toBeGreaterThanOrEqual(4.5);
  // Independent meaningful failure control for the reused ratio helper, not a proof rerun.
  const same=measured.backgrounds[0]!.colour;
  const matching=[1,3,5].map(i=>parseInt(same.slice(i,i+2),16)).concat(255);
  expect(backingContrast(backing!,matching,{x:text.x,y:text.y,width:text.width,height:text.height}).minimum, 'foreground=actual backing must fail4.5').toBe(1);
  return before;
}

test('BODY09 real Reports counts: light/dark paint, overlap, backing and fail-closed controls', async ({page,browser},info) => {
  const bindings=qualifiedInputs(), {script,moduleInputs}=await productionBundle();
  const report=coastReportFixture(NOW.getTime());
  report.catches=report.catches.slice(0,1);
  report.catches[0]!.species=[{name:'Synthetic full bar',count:100,disposition:'reported'},
    {name:'Synthetic partial bar',count:25,disposition:'reported'},{name:'Synthetic zero bar',count:0,disposition:'reported'}];
  const unexpected: string[]=[], errors:string[]=[], served:Record<string,string>={};
  page.on('pageerror',e=>errors.push(String(e)));
  await page.clock.setFixedTime(NOW);
  // Every request is handled here before any server/provider; no Worker is started by the dedicated config.
  await page.route('**/*',route=>{
    const url=new URL(route.request().url()),path=url.pathname.slice(1);
    if(url.origin!==ORIGIN){unexpected.push(url.href);return route.abort('blockedbyclient');}
    if(path==='__p04/')return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>BODY09 production Reports</title>${STYLES.slice(0,3).map(p=>`<link rel="stylesheet" href="/${p}">`).join('')}<style>#mount{padding:16px;max-width:760px;margin:0 auto;}</style></head><body><main id="mount"></main><script src="/__p04/host.js"></script></body></html>`});
    if(path==='__p04/host.js'){served[path]=hash(script);return route.fulfill({contentType:'text/javascript',body:script});}
    if(path==='api/coast/report'){served[path]=hash(JSON.stringify(report));return route.fulfill({json:report});}
    if([...STYLES,...FONTS].includes(path)){const body=read(path);served[path]=hash(body);return route.fulfill({body,contentType:path.endsWith('.css')?'text/css':'font/woff2'});}
    unexpected.push(url.href);return route.abort('blockedbyclient');
  });
  await page.goto(ORIGIN+'/__p04/?region=morro-bay&view=reports&profile=boat&target=lingcod');
  await page.evaluate(()=> (window as unknown as {mountP04Reports():Promise<void>}).mountP04Reports());
  const host=page.locator('.app-reports [data-renderer="catchSheet"]');
  const rows=host.locator('.catch-counts > div');
  await expect(rows).toHaveCount(3);
  await expect(rows.locator('dd')).toHaveText(['100','25','0']);
  const results:unknown[]=[];
  for(const theme of ['dark','light']) {
    await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
    await expect.poll(()=>host.evaluate(e=>{const links=[...e.shadowRoot!.querySelectorAll<HTMLLinkElement>('link')];return links.length===2&&links.every(l=>!!l.sheet&&!l.disabled);})).toBe(true);
    await page.evaluate(async()=>{await document.fonts.load('15px "DM Sans"');await document.fonts.load('12px "JetBrains Mono"');await document.fonts.ready;});
    for(const [i,kind] of ['full','partial','zero'].entries()) {
      const got=await evidence(page,rows.nth(i),info,`${theme}-${kind}`);
      expect(got.theme).toBe(theme);
      if(kind==='full')expect(got.textBarOverlapFraction).toBeGreaterThan(.99);
      else expect(got.textBarOverlapFraction).toBe(0);
      if(kind==='partial')expect(got.boxes.bar.width).toBeGreaterThan(0);
      if(kind==='zero')expect(got.boxes.bar.width).toBe(0);
      results.push({theme,kind,foreground:got.foreground,panel:got.panel});
    }
    await info.attach(theme+'-reports-visible',{body:await page.screenshot({fullPage:true,scale:'css',animations:'disabled'}),contentType:'image/png'});
  }
  expect((results[0] as {foreground:number[]}).foreground).not.toEqual((results[3] as {foreground:number[]}).foreground);
  // Controls are mutations after primary evidence, restored in finally; never count as production passes.
  const controls=[];
  await rows.first().scrollIntoViewIfNeeded();
  await host.evaluate(e=>{e.shadowRoot!.querySelector<HTMLLinkElement>('link[href$="tokens-bridge.css"]')!.disabled=true;});
  try {const got=await audit(rows.first());expect(got.issues).toContain('bridge_or_panel_not_loaded');controls.push({id:'missing-bridge',issues:got.issues});}
  finally {await host.evaluate(e=>{e.shadowRoot!.querySelector<HTMLLinkElement>('link[href$="tokens-bridge.css"]')!.disabled=false;});}
  await expect.poll(async()=> (await audit(rows.first())).issues).toEqual([]);
  await rows.first().locator('dd').evaluate(e=>(e as HTMLElement).style.setProperty('color','var(--coast-panel)','important'));
  try {const got=await audit(rows.first());expect(got.issues).toContain('count_foreground_not_mint');controls.push({id:'cascade-mismatch',issues:got.issues});}
  finally {await rows.first().locator('dd').evaluate(e=>e.removeAttribute('style'));}
  await host.evaluate(e=>(e as HTMLElement).style.opacity='.5');
  try {const got=await audit(rows.first());expect(got.issues.some(s=>s.startsWith('unsupported_ancestor:'))).toBe(true);controls.push({id:'ancestor-opacity',issues:got.issues});}
  finally {await host.evaluate(e=>e.removeAttribute('style'));}
  const box=await rows.first().locator('dd').boundingBox();expect(box).not.toBeNull();
  await page.evaluate(b=>{const e=document.createElement('div');e.id='p04-control-overlay';e.style.cssText=`position:fixed;left:${b!.x}px;top:${b!.y}px;width:${b!.width}px;height:${b!.height}px;background:black;z-index:2147483647;`;document.body.append(e);},box);
  try {const got=await audit(rows.first());expect(got.issues).toContain('count_occluded');controls.push({id:'overlay',issues:got.issues});}
  finally {await page.locator('#p04-control-overlay').evaluate(e=>e.remove());}
  expect((await audit(rows.first())).issues).toEqual([]);
  expect(errors,'uncaught errors').toEqual([]);
  expect(unexpected,'no unstubbed/server/provider/GPU requests').toEqual([]);
  for(const p of [...STYLES,...FONTS])expect(served[p],p+' actually served exact bytes').toBe(bindings.inputs[p]);
  await info.attach('provenance-and-controls',{body:JSON.stringify({bindings,moduleInputs,bundleSha256:hash(script),served,
    gitHead:execFileSync('git',['rev-parse','HEAD'],{cwd:ROOT,encoding:'utf8'}).trim(),
    gitTree:execFileSync('git',['rev-parse','HEAD^{tree}'],{cwd:ROOT,encoding:'utf8'}).trim(),
    runtime:process.version,browser:browser.version(),project:info.project.name,viewport:page.viewportSize(),
    date:NOW.toISOString(),url:page.url(),reportSha256:hash(JSON.stringify(report)),results,controls,
    scope:'Actual production Reports/CatchCards/CoastMarkup/catchSheet in a finite local route host, not full map/shell/GPU/native or legacy fallback acceptance.'},null,2),contentType:'application/json'});
});
