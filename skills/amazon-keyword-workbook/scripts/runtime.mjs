import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const localRequire = createRequire(import.meta.url);
const binDir = path.dirname(process.execPath);

export async function loadArtifact() {
  const packageName = "@oai/artifact-tool";
  const directories = [
    process.env.KEYWORD_NODE_MODULES,
    path.resolve(binDir, "../node_modules"),
    path.join(binDir, "node_modules"),
  ].filter(Boolean);
  const resolvers = [
    localRequire,
    ...directories.map((dir) => createRequire(path.resolve(dir, "../skill-resolver.cjs"))),
  ];
  for (const resolver of resolvers) {
    let location;
    try {
      location = resolver.resolve(packageName);
    } catch (error) {
      if (error.code === "MODULE_NOT_FOUND") continue;
      throw error;
    }
    return import(pathToFileURL(location).href);
  }
  throw new Error("需要 @oai/artifact-tool。使用 Codex 表格运行时的 Node，或将 KEYWORD_NODE_MODULES 指向已安装该包的 node_modules。");
}

export function pythonCommand() {
  if (process.env.KEYWORD_PYTHON) return process.env.KEYWORD_PYTHON;
  const candidates = process.platform === "win32"
    ? [path.resolve(binDir, "../python/python.exe"), path.resolve(binDir, "../../python/python.exe")]
    : [path.resolve(binDir, "../../python/bin/python3")];
  return candidates.find((candidate) => existsSync(candidate)) ?? (process.platform === "win32" ? "python" : "python3");
}
