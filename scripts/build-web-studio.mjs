import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontendDir = path.join(rootDir, "apps", "web-studio", "frontend");
const distDir = path.join(frontendDir, "dist");
const entryPoint = path.join(frontendDir, "src", "main.tsx");
const indexHtml = path.join(frontendDir, "index.html");
const esbuild = require(path.join(rootDir, "renderer", "remotion", "node_modules", "esbuild"));
const watch = process.argv.includes("--watch");

function prepareDist() {
  fs.rmSync(distDir, { recursive: true, force: true });
  fs.mkdirSync(distDir, { recursive: true });
  fs.copyFileSync(indexHtml, path.join(distDir, "index.html"));
}

const buildOptions = {
  entryPoints: [entryPoint],
  bundle: true,
  outdir: distDir,
  entryNames: "assets/app",
  assetNames: "assets/[name]",
  chunkNames: "assets/[name]-[hash]",
  format: "esm",
  platform: "browser",
  target: ["es2020"],
  sourcemap: false,
  minify: !watch,
  loader: {
    ".css": "css",
  },
  logLevel: "info",
};

prepareDist();

if (watch) {
  const context = await esbuild.context(buildOptions);
  await context.watch();
  console.log("Watching EchoForge Web Studio frontend...");
} else {
  await esbuild.build(buildOptions);
  console.log(`Built EchoForge Web Studio frontend at ${distDir}`);
}
