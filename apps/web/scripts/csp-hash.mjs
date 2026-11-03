// Computes the CSP hash of the inline theme bootstrap script in dist/index.html.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error("inline theme script not found");
const hash = "sha256-" + createHash("sha256").update(match[1]).digest("base64");
writeFileSync(new URL("../dist/csp-hash.txt", import.meta.url), hash + "\n");
console.log("csp hash", hash);
