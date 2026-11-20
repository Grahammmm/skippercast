// Historical single-target exports for local research only, not web assets.
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { targetGPX } from "../../dist/gpx.js";

const atlas = JSON.parse(
  await readFile(new URL("../../dist/data/atlas.json", import.meta.url)),
);
const directory = new URL("../../var/research/legacy-target-gpx/", import.meta.url);
await mkdir(directory, { recursive: true });
let bytes = 0;
for (const target of atlas.targets) {
  if (!/^SC26-\d{3}$/.test(target.id))
    throw new Error(`Unexpected target ID: ${target.id}`);
  const gpx = targetGPX(atlas, target.id);
  await writeFile(new URL(`${target.id}.gpx`, directory), gpx);
  bytes += Buffer.byteLength(gpx);
}
console.log(
  `Prepared ${atlas.targets.length} local research GPX files (${bytes} bytes).`,
);
