// Build metadata is descriptive: version and build time, not a checksum gate.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const uiRoot = path.join(here, "..");
const dist = path.join(uiRoot, "dist");
const pkg = JSON.parse(readFileSync(path.join(uiRoot, "package.json"), "utf8"));
const stamp = {
  version: pkg.version,
  built_at: new Date().toISOString(),
};
mkdirSync(dist, { recursive: true });
writeFileSync(path.join(dist, "build.json"), JSON.stringify(stamp, null, 2) + "\n");
console.log(`[build] ${stamp.version} · ${stamp.built_at}`);
