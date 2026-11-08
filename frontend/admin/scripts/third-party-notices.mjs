#!/usr/bin/env node
// Prints the license texts of the admin console's production npm dependencies.
//
// The image build runs this after `npm ci`, so the runtime image ships the license terms of
// the packages bundled into the standalone Next.js output. Production packages are taken from
// package-lock.json (entries not marked dev); optional platform packages that are not
// installed on the build platform are skipped.
//
// Usage: node scripts/third-party-notices.mjs > THIRD_PARTY_NOTICES.txt
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const lock = JSON.parse(readFileSync(join(root, "package-lock.json"), "utf8"));
const LICENSE_FILE = /^(licen[cs]e|copying|notice)/i;

function declaredLicense(pkg) {
  if (typeof pkg.license === "string") return pkg.license;
  if (pkg.license && typeof pkg.license.type === "string") return pkg.license.type;
  if (Array.isArray(pkg.licenses)) return pkg.licenses.map((entry) => entry.type ?? entry).join(", ");
  return "not declared";
}

const sections = [
  [
    "Third-party software notices",
    "============================",
    "",
    "This image contains the npm packages listed below. Each entry gives the package version,",
    "its declared license and the license files shipped with the package. The ADCS code itself",
    "is MIT-licensed: https://github.com/aspose-core-mcp/context-engine/blob/main/LICENSE",
  ].join("\n"),
];

const seen = new Set();
const production = Object.entries(lock.packages ?? {})
  .filter(([path, info]) => path.startsWith("node_modules/") && !info.dev && !info.devOptional)
  .sort(([a], [b]) => a.localeCompare(b));

for (const [path] of production) {
  const dir = join(root, path);
  const manifest = join(dir, "package.json");
  if (!existsSync(manifest)) continue;
  const pkg = JSON.parse(readFileSync(manifest, "utf8"));
  const id = `${pkg.name} ${pkg.version}`;
  if (seen.has(id)) continue;
  seen.add(id);
  const lines = [id, "-".repeat(id.length), `License: ${declaredLicense(pkg)}`];
  const files = readdirSync(dir)
    .filter((name) => LICENSE_FILE.test(name) && statSync(join(dir, name)).isFile())
    .sort();
  if (files.length === 0) lines.push("No license file is included in the package.");
  for (const name of files) {
    lines.push("", `--- ${pkg.name}/${name} ---`, readFileSync(join(dir, name), "utf8").trimEnd());
  }
  sections.push(lines.join("\n"));
}

process.stdout.write(`${sections.join("\n\n\n")}\n`);
