// Copies pipeline output (../data/derived and ../data/history) into public/data for local dev,
// or into dist/data after `vite build` when called with --dist. Missing data is not an error:
// the dashboard renders an explicit "no data collected yet" state.
import { cpSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(process.env.PFI_DATA_DIR || resolve(here, "../../data"));
const target = resolve(here, process.argv.includes("--dist") ? "../dist/data" : "../public/data");
mkdirSync(target, { recursive: true });
for (const sub of ["derived", "history"]) {
  const from = resolve(src, sub);
  if (existsSync(from)) cpSync(from, resolve(target, sub), { recursive: true });
  else console.warn(`[sync-data] ${from} not found — skipping`);
}
writeFileSync(resolve(target, "manifest.json"), JSON.stringify({ synced_at: new Date().toISOString() }));
console.log(`[sync-data] ${src} -> ${target}`);
