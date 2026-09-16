import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

type BrowserTarget = "chrome" | "firefox" | "safari";
type Manifest = Record<string, unknown> & { permissions?: string[] };

const packageMetadata = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
) as { version: string };

function readManifest(name: string): Manifest {
  return JSON.parse(
    readFileSync(
      fileURLToPath(new URL(`manifests/${name}.json`, import.meta.url)),
      "utf8",
    ),
  ) as Manifest;
}

function targetManifest(target: BrowserTarget): string {
  const base = readManifest("base");
  const overlay = readManifest(target);
  const manifest: Manifest = {
    ...base,
    ...overlay,
    version: packageMetadata.version,
    permissions: [...(base.permissions ?? []), ...(overlay.permissions ?? [])],
  };
  if (target === "safari") {
    manifest.permissions = manifest.permissions?.filter(
      (permission) => permission !== "downloads",
    );
    const background = { ...(manifest.background as Record<string, unknown>) };
    delete background.type;
    manifest.background = background;
    manifest.content_scripts = (
      manifest.content_scripts as Array<Record<string, unknown>>
    ).map((script) => {
      const compatible = { ...script };
      delete compatible.world;
      return compatible;
    });
  }
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

function manifestPlugin(target: BrowserTarget): Plugin {
  return {
    name: "elsewise-target-manifest",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "manifest.json",
        source: targetManifest(target),
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const target: BrowserTarget =
    mode === "firefox" ? "firefox" : mode === "safari" ? "safari" : "chrome";
  return {
    define: {
      __EXTENSION_VERSION__: JSON.stringify(packageMetadata.version),
    },
    plugins: [manifestPlugin(target)],
    build: {
      outDir: `dist/${target}`,
      emptyOutDir: true,
      modulePreload: false,
      rollupOptions: {
        input: {
          background: fileURLToPath(
            new URL("src/background/index.ts", import.meta.url),
          ),
          content: fileURLToPath(
            new URL("src/content/index.ts", import.meta.url),
          ),
          "zoom-main": fileURLToPath(
            new URL("src/content/zoom-main.ts", import.meta.url),
          ),
          popup: fileURLToPath(new URL("popup.html", import.meta.url)),
          sidepanel: fileURLToPath(new URL("sidepanel.html", import.meta.url)),
        },
        output: {
          entryFileNames: "[name].js",
          chunkFileNames: "chunks/[name]-[hash].js",
          assetFileNames: "assets/[name]-[hash][extname]",
        },
      },
    },
  };
});
