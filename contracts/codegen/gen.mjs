// contracts/codegen/gen.mjs
// JSON-Schema -> TypeScript for the FROZEN §4 boundary AND the Elydora REST DTOs.
// Output: console/src/types/contracts.d.ts (the @elydora/shared replacement).
// W0: working skeleton. The §4 snapshots are W0 stubs; contracts/elydora/*.schema.json
// is populated at W1 by sdk-builder + console-builder. `npm run gen` is wired into the
// console build (see console/package.json) and the CI `console` job.
import { compileFromFile } from "json-schema-to-typescript";
import { readdirSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const contractsDir = resolve(here, "..");
const outFile = resolve(here, "../../console/src/types/contracts.d.ts");

const sources = [];
for (const f of readdirSync(contractsDir)) {
  if (f.endsWith(".schema.json")) sources.push(join(contractsDir, f));
}
const elydoraDir = join(contractsDir, "elydora");
if (existsSync(elydoraDir)) {
  for (const f of readdirSync(elydoraDir)) {
    if (f.endsWith(".schema.json")) sources.push(join(elydoraDir, f));
  }
}

const banner = "// AUTO-GENERATED from contracts/*.schema.json — DO NOT EDIT.\n" +
  "// Regenerate: (cd contracts/codegen && npm run gen). Source of truth = contracts/.\n";

let out = banner;
for (const src of sources.sort()) {
  out += await compileFromFile(src, { bannerComment: "", additionalProperties: true });
  out += "\n";
}

mkdirSync(dirname(outFile), { recursive: true });
writeFileSync(outFile, out);
console.log(`contracts codegen: wrote ${outFile} from ${sources.length} schema(s)`);
