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
const frontendNodeModules = path.join(frontendDir, "node_modules");
const remotionNodeModules = path.join(rootDir, "renderer", "remotion", "node_modules");
const nodeModulePaths = [frontendNodeModules, remotionNodeModules].filter((candidate) => fs.existsSync(candidate));
const esbuild = requireFirst("esbuild");
const watch = process.argv.includes("--watch");

function requireFirst(packageName) {
  for (const nodeModules of nodeModulePaths) {
    try {
      return require(path.join(nodeModules, packageName));
    } catch {
      // Try the next installed dependency root.
    }
  }
  throw new Error(`Missing ${packageName}. Run npm install in apps/web-studio/frontend or renderer/remotion.`);
}

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
  nodePaths: nodeModulePaths,
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
