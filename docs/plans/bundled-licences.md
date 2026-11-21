# Which libraries reach the browser?

| Library | Built location | Licence ID | Credits at main |
| --- | --- | --- | --- |
| MapLibre GL JS 6.18.0 | Browser: `maplibre-gl` chunk and its browser worker | BSD-3-Clause | Page and NOTICE current |
| PMTiles 4.5.0 | Browser: `maplibre-gl` chunk | BSD-3-Clause | Page and NOTICE current |
| Three.js 0.187.0 | Browser: `terrain` | MIT | Page missing; NOTICE says 0.180.0 |
| Preact 11.2.0 | Browser: `jsxRuntime`, `signals.module`; also in server | MIT | Page and NOTICE missing |
| `@preact/signals` 2.11.4 | Browser: `signals.module`; also in server | MIT | Page and NOTICE missing |
| SunCalc 2.1.4 | Browser: `suncalc` | BSD-2-Clause | Page missing; NOTICE says 2.1.0 |
| `@preact/signals-core` 1.14.5 | Browser: `signals.module`; also in server | MIT | Page and NOTICE missing |
| fflate 0.8.3 | Browser: `maplibre-gl` | MIT | Page and NOTICE missing |
| `@simplewebauthn/browser` 14.0.0 | Browser: separate `/vendor/` script, not a chunk | MIT | Page and NOTICE missing |
| Hono, `@simplewebauthn/server`, `@block65/webcrypto-web-push` | Server Worker only | — | Not part of the browser-credit proposal |
| `drizzle-orm` | Neither build output | — | Schema/tooling only in this audit |

Evidence below is from the local `origin/main` pin `c5f07fc5d9516d1d9b0954e7ec47506b343963c8`. This report supplies proposed text for the owner, not a licence decision or a change to the approved backlog status.

## R1. Trace code in the built output

From a clean checkout of the pin, run `pnpm install --offline --frozen-lockfile` and `pnpm build` (Node 22.23.2, pnpm 10.34.8 in this run). The build finished with ID `162ab90fec`. `package.json:9-10,17-27` defines the command and direct runtime list; `scripts/build-worker.mjs:19-20,33-35` separates the browser output from `dist/server/index.js`.

Searching minified JavaScript for package names alone can miss code or mistake a string for code. Instead, save this as `scan-bundle.mjs` outside the checkout and run `node ../scan-bundle.mjs` from its root. It replays the same client config (`scripts/client-build.mjs:195-199`, `vite.config.mjs:197-227`) without writing output, searches the bundler's module records for non-empty rendered package modules, and checks every generated JS asset against the actual `pnpm build` bytes. This covers lazy chunks, not just scripts loaded on first paint.

```js
import {readFileSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const load = p => import(pathToFileURL(resolve(p)));
const {build} = await load('node_modules/vite/dist/node/index.js');
const {clientConfig} = await load('vite.config.mjs');
const cfg = clientConfig({root:'dist',outDir:'dist/client'});
const byPackage = new Map();
const seen = new Set();
cfg.plugins.push({name:'audit-package-origins',generateBundle:{order:'post',handler(_,bundle){
  for (const [file,out] of Object.entries(bundle)) {
    if (!/^assets\/.*\.js$/.test(file)) continue;
    const bytes = out.type === 'chunk' ? out.code : out.source;
    if (!readFileSync(`dist/client/${file}`).equals(Buffer.from(bytes))) throw Error(`byte mismatch: ${file}`);
    seen.add(file);
    if (out.type !== 'chunk') continue;
    for (const [id,mod] of Object.entries(out.modules)) {
      const path = id.replaceAll('\\','/').split('/node_modules/').at(-1);
      const pkg = path.match(/^(@[^/]+\/[^/]+|[^/]+)\//)?.[1];
      if (path === id || !pkg || mod.renderedLength <= 0) continue;
      const files = byPackage.get(pkg) || new Set();
      files.add(file); byPackage.set(pkg,files);
    }
  }
}}});
await build({configFile:false,...cfg,build:{...cfg.build,write:false}});
const actual = readdirSync('dist/client/assets').filter(f=>f.endsWith('.js')).map(f=>`assets/${f}`);
if (actual.some(f=>!seen.has(f))) throw Error('unmatched JS: '+actual.filter(f=>!seen.has(f)).join(', '));
console.log(`${seen.size} JS assets matched byte for byte`);
for (const [pkg,files] of [...byPackage].sort()) console.log(pkg,[...files].sort().join(' '));
```

```text
136 JS assets matched byte for byte
@preact/signals assets/signals.module.4056e0625e.js
@preact/signals-core assets/signals.module.4056e0625e.js
fflate assets/maplibre-gl.8f7dab85e8.js
maplibre-gl assets/maplibre-gl.8f7dab85e8.js
pmtiles assets/maplibre-gl.8f7dab85e8.js
preact assets/jsxRuntime.440b43772a.js assets/signals.module.4056e0625e.js
suncalc assets/suncalc.38c042ae4b.js
three assets/terrain.24f01340ba.js
```

The scan reports packages that the site's bundler sees individually; it does not unpack libraries already welded together upstream. MapLibre also emits `maplibre-gl-worker.12723c8195.js` (`web/map/maplibre.js:9-14`; `rg --files --no-ignore dist/client/assets -g '*worker*'`). The existing MapLibre credit already calls out upstream Mapbox GL JS v1.13 code (`dist/licenses.html:37-45`); this is not an upstream component-by-component audit of MapLibre or other prebundled scripts.

To check the server side, search actual module-origin comments, not the package manifest copied into the Worker:

```sh
rg -o --no-filename '^// node_modules/\.pnpm/[^/]+/node_modules/(@[^/]+/[^/]+|[^/]+)' dist/server/index.js | sort -u
rg -n 'drizzle-orm|suncalc|preact-render-to-string' dist/server/index.js
```

The Worker has Hono 4.13.18, `@simplewebauthn/server` 14.1.0 and `@block65/webcrypto-web-push` 2.0.0; none of those three is in the browser scan. It also has Preact, signals and signals-core, so they are not server-only. The occurrences of Drizzle, SunCalc and `preact-render-to-string` in the second search are manifest text, not module-origin lines. Drizzle is used by `db/schema.ts:1` for schema generation (`package.json:14`); it did not reach either output in this build.

The passkey script is an independent browser delivery: `dist/account.js:231-247,264-271` sets its URL and loads it on demand. The first command below found only a URL in `account.3265450be1.js`; the second confirmed the actual library is copied unchanged, outside `assets/`.

```sh
rg -n -o 'simplewebauthn-browser-14\.0\.0/index\.umd\.min\.js' dist/client/assets -g '*.js' --no-ignore
cmp dist/{vendor,client/vendor}/simplewebauthn-browser-14.0.0/index.umd.min.js
```

## R2. What is missing, and which texts are retained?

The page's web-app section (`dist/licenses.html:36-190`) lists only MapLibre and PMTiles. `NOTICE.md:37,65-69` gives their current versions, but its other renderer credits have stale Three.js/SunCalc versions. Run `git ls-tree -r --name-only HEAD dist/vendor` for all retained paths, and run the searches below for the versions, licence IDs and text differences.

| Missing or stale credit | Licence ID | Retained under `dist/vendor`? |
| --- | --- | --- |
| Three.js 0.187.0 | MIT | `THREE-LICENSE.txt` exists; same terms, but its copyright line ends in 2025 rather than the installed 2026. |
| Preact 11.2.0 | MIT | No Preact licence text. |
| `@preact/signals` 2.11.4 | MIT | No signals licence text. |
| SunCalc 2.1.4 | BSD-2-Clause | `SUNCALC-LICENSE.txt` exactly matches the installed text. This ID comes from the two conditions in that text, not a manifest `license` field. |
| `@preact/signals-core` 1.14.5 | MIT | No retained text; installed text is byte-identical to signals. |
| fflate 0.8.3 | MIT | No fflate licence text. |
| `@simplewebauthn/browser` 14.0.0 (separate delivery) | MIT | `simplewebauthn-browser-14.0.0/LICENSE.md:1-18`. |

```sh
rg -n '"(version|license)"' node_modules/{maplibre-gl,pmtiles,three,preact,@preact/signals,suncalc}/package.json
rg -n '"(version|license)"' node_modules/.pnpm/{@preact+signals-core@1.14.5/node_modules/@preact/signals-core,fflate@0.8.3/node_modules/fflate}/package.json
rg -n 'signals-core|fflate' pnpm-lock.yaml
rg -n '<h[23]|simplewebauthn-browser' dist/licenses.html
rg -ni 'preact|three\.js|suncalc|fflate|simplewebauthn' NOTICE.md
diff -u dist/vendor/THREE-LICENSE.txt node_modules/three/LICENSE
cmp dist/vendor/SUNCALC-LICENSE.txt node_modules/suncalc/LICENSE
cmp node_modules/@preact/signals/LICENSE node_modules/.pnpm/@preact+signals-core@1.14.5/node_modules/@preact/signals-core/LICENSE
```

## R3. Proposed edits for the owner — not applied

`.github/CODEOWNERS:1-5` gives the owner review of NOTICE and legal documents. These proposals pair the two version corrections with new page and NOTICE credits. They preserve the page's heading, project link, usage description and expandable licence text format (`dist/licenses.html:37-45,162-170`); the extra browser-library credits are labelled by delivery path. No decision is made about legal sufficiency. The proposed diffs use zero context; to check an extracted block without modifying the checkout, use `git apply --unidiff-zero --check <patch-file>`.

**`dist/licenses.html`** — insert before “Software in the server”. The Three.js “Licence file” link assumes the owner refreshes `dist/vendor/THREE-LICENSE.txt` from `node_modules/three/LICENSE` (R2 shows the exact one-line difference). Preact, signals/core and fflate have their text inline because no retained file is present. The passkey credit links the already vendored text.

```diff
--- a/dist/licenses.html
+++ b/dist/licenses.html
@@ -190,0 +191,181 @@
+      <h3>Three.js 0.187.0</h3>
+      <p>
+        <a href="https://threejs.org/">Three.js</a> · MIT.
+        Renders the coastal terrain in 3D.
+        <a href="vendor/THREE-LICENSE.txt">Licence file</a>.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">The MIT License
+
+Copyright © 2010-2026 three.js authors
+
+Permission is hereby granted, free of charge, to any person obtaining a copy
+of this software and associated documentation files (the &quot;Software&quot;), to deal
+in the Software without restriction, including without limitation the rights
+to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
+copies of the Software, and to permit persons to whom the Software is
+furnished to do so, subject to the following conditions:
+
+The above copyright notice and this permission notice shall be included in
+all copies or substantial portions of the Software.
+
+THE SOFTWARE IS PROVIDED &quot;AS IS&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
+IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
+FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
+AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
+LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
+OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
+THE SOFTWARE.</pre>
+      </details>
+
+      <h3>Preact 11.2.0</h3>
+      <p>
+        <a href="https://preactjs.com/">Preact</a> · MIT.
+        Renders interactive parts of the site.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">The MIT License (MIT)
+
+Copyright (c) 2015-present Jason Miller
+
+Permission is hereby granted, free of charge, to any person obtaining a copy
+of this software and associated documentation files (the &quot;Software&quot;), to deal
+in the Software without restriction, including without limitation the rights
+to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
+copies of the Software, and to permit persons to whom the Software is
+furnished to do so, subject to the following conditions:
+
+The above copyright notice and this permission notice shall be included in all
+copies or substantial portions of the Software.
+
+THE SOFTWARE IS PROVIDED &quot;AS IS&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
+IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
+FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
+AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
+LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
+OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
+SOFTWARE.</pre>
+      </details>
+
+      <h3>@preact/signals 2.11.4</h3>
+      <p>
+        <a href="https://github.com/preactjs/signals">@preact/signals</a> · MIT.
+        Keeps the interface in sync as values change. The bundle also includes @preact/signals-core 1.14.5 under the same licence notice.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">The MIT License (MIT)
+
+Copyright (c) 2022-present Preact Team
+
+Permission is hereby granted, free of charge, to any person obtaining a copy
+of this software and associated documentation files (the &quot;Software&quot;), to deal
+in the Software without restriction, including without limitation the rights
+to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
+copies of the Software, and to permit persons to whom the Software is
+furnished to do so, subject to the following conditions:
+
+The above copyright notice and this permission notice shall be included in all
+copies or substantial portions of the Software.
+
+THE SOFTWARE IS PROVIDED &quot;AS IS&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
+IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
+FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
+AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
+LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
+OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
+SOFTWARE.</pre>
+      </details>
+
+      <h3>SunCalc 2.1.4</h3>
+      <p>
+        <a href="https://github.com/mourner/suncalc">SunCalc</a> · BSD 2-Clause.
+        Calculates sun times for trip planning.
+        <a href="vendor/SUNCALC-LICENSE.txt">Licence file</a>.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">Copyright (c) 2026, Volodymyr Agafonkin
+All rights reserved.
+
+Redistribution and use in source and binary forms, with or without modification, are
+permitted provided that the following conditions are met:
+
+   1. Redistributions of source code must retain the above copyright notice, this list of
+      conditions and the following disclaimer.
+
+   2. Redistributions in binary form must reproduce the above copyright notice, this list
+      of conditions and the following disclaimer in the documentation and/or other materials
+      provided with the distribution.
+
+THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS &quot;AS IS&quot; AND ANY
+EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
+MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
+COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
+EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
+SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
+HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
+TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
+SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.</pre>
+      </details>
+
+      <h3>fflate 0.8.3</h3>
+      <p>
+        <a href="https://github.com/101arrowz/fflate">fflate</a> · MIT.
+        Decompresses data used by the bundled PMTiles reader.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">MIT License
+
+Copyright (c) 2026 Arjun Barrett
+
+Permission is hereby granted, free of charge, to any person obtaining a copy
+of this software and associated documentation files (the &quot;Software&quot;), to deal
+in the Software without restriction, including without limitation the rights
+to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
+copies of the Software, and to permit persons to whom the Software is
+furnished to do so, subject to the following conditions:
+
+The above copyright notice and this permission notice shall be included in all
+copies or substantial portions of the Software.
+
+THE SOFTWARE IS PROVIDED &quot;AS IS&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
+IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
+FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
+AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
+LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
+OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
+SOFTWARE.</pre>
+      </details>
+
+      <h3>@simplewebauthn/browser 14.0.0</h3>
+      <p>
+        <a href="https://github.com/MasterKale/SimpleWebAuthn">@simplewebauthn/browser</a> · MIT.
+        Handles passkey registration and sign-in. Loaded separately when needed, not bundled in the app chunks.
+        <a href="vendor/simplewebauthn-browser-14.0.0/LICENSE.md">Licence file</a>.
+      </p>
+      <details>
+        <summary>Licence text</summary>
+        <pre class="small">MIT License
+
+Copyright (c) 2020 Matthew Miller
+
+Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
+associated documentation files (the &quot;Software&quot;), to deal in the Software without restriction,
+including without limitation the rights to use, copy, modify, merge, publish, distribute,
+sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
+furnished to do so, subject to the following conditions:
+
+The above copyright notice and this permission notice shall be included in all copies or substantial
+portions of the Software.
+
+THE SOFTWARE IS PROVIDED &quot;AS IS&quot;, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
+NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
+NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
+OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
+CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.</pre>
+      </details>
+
```

**`NOTICE.md`** — correct the retained renderer credits and name the remaining libraries. Update the retained Three.js copyright as noted above before using its link to refer to the current release. In this block only, replace `] (` with `](` before saving the patch: the space distinguishes quoted repo-root link syntax from links relative to this report, which the repository checker scans even inside code fences.

```diff
--- a/NOTICE.md
+++ b/NOTICE.md
@@ -69 +69,3 @@
-Three.js 0.180.0 is MIT licensed ([retained notice] (dist/vendor/THREE-LICENSE.txt)). SunCalc 2.1.0 is BSD 2-Clause licensed ([retained notice] (dist/vendor/SUNCALC-LICENSE.txt)). These notices remain separate from the SkipperCast license. The coastal interface uses the already self-hosted DM Sans font under the retained SIL OFL notice above.
+Three.js 0.187.0 is MIT licensed ([retained notice] (dist/vendor/THREE-LICENSE.txt)). SunCalc 2.1.4 is BSD 2-Clause licensed ([retained notice] (dist/vendor/SUNCALC-LICENSE.txt)). These notices remain separate from the SkipperCast license. The coastal interface uses the already self-hosted DM Sans font under the retained SIL OFL notice above.
+
+The web app also bundles Preact 11.2.0, @preact/signals 2.11.4 (including @preact/signals-core 1.14.5), and fflate 0.8.3, all MIT licensed. It loads @simplewebauthn/browser 14.0.0 separately for passkeys (MIT; [retained notice] (dist/vendor/simplewebauthn-browser-14.0.0/LICENSE.md)). See the web app software section of the licences page for the licence texts.
```

**`scripts/check_web.py`** — list the four newly credited direct dependencies. `check_bundled_licence_versions` (`scripts/check_web.py:351-361,369`) checks exact `package.json` dependency versions against both documents; keep the separately vendored script and transitive-only packages out of that table because they are not direct dependency pins. Apply the three proposals together so the checker can find the exact names and versions on both surfaces.

```diff
--- a/scripts/check_web.py
+++ b/scripts/check_web.py
@@ -348 +348,8 @@
-BUNDLED_LIBRARIES = {"maplibre-gl": "MapLibre GL JS", "pmtiles": "PMTiles"}
+BUNDLED_LIBRARIES = {
+    "maplibre-gl": "MapLibre GL JS",
+    "pmtiles": "PMTiles",
+    "three": "Three.js",
+    "preact": "Preact",
+    "@preact/signals": "@preact/signals",
+    "suncalc": "SunCalc",
+}
```

## R4. One-file change

Only `docs/plans/bundled-licences.md` is added. To verify from the signed checkout, `git diff --name-status origin/main HEAD` lists only `A` for this report; `git status --short` is empty. The build and offline install produce ignored files only; the HTML, NOTICE, vendor copies in the source tree and checker are unchanged. Run `python scripts/check_repository.py` at the report commit.
