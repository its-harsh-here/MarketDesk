// Regenerates src/lib/api/schema.d.ts from the FastAPI OpenAPI document.
import { execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const apiDir = path.resolve(here, "../../api");
const out = path.resolve(here, "../src/lib/api");
mkdirSync(out, { recursive: true });
const json = execFileSync("uv", ["run", "--quiet", "python", "-c",
  "import json,os;os.environ.setdefault('DEV_AUTH_BYPASS','true');from marketdesk.api.app import create_app;print(json.dumps(create_app().openapi()))"],
  { cwd: apiDir, env: { ...process.env, DATA_DIR: path.resolve(here, "../../../data/.openapi") } });
writeFileSync(path.join(out, "openapi.json"), json);
execFileSync("npx", ["openapi-typescript", path.join(out, "openapi.json"), "-o", path.join(out, "schema.d.ts")], { stdio: "inherit" });
