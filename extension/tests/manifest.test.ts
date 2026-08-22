import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

type Manifest = Record<string, unknown> & { permissions?: string[] };

function manifestSource(name: string): Manifest {
  const path = fileURLToPath(
    new URL(`../manifests/${name}.json`, import.meta.url),
  );
  return JSON.parse(readFileSync(path, "utf8")) as Manifest;
}

function targetManifest(target: "chrome" | "firefox"): Manifest {
  const base = manifestSource("base");
  const overlay = manifestSource(target);
  return {
    ...base,
    ...overlay,
    permissions: [...(base.permissions ?? []), ...(overlay.permissions ?? [])],
  };
}

function localeMessages(locale: string): Record<string, { message: string }> {
  const localePath = fileURLToPath(
    new URL(`../public/_locales/${locale}/messages.json`, import.meta.url),
  );
  return JSON.parse(readFileSync(localePath, "utf8")) as Record<
    string,
    { message: string }
  >;
}

describe("cross-browser manifests", () => {
  it("keeps platform and daemon access in one shared MV3 manifest", () => {
    const manifest = targetManifest("chrome");
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.host_permissions).toEqual(
      expect.arrayContaining([
        "http://127.0.0.1/*",
        "https://meet.google.com/*",
        "https://teams.microsoft.com/*",
        "https://teams.live.com/*",
        "https://app.zoom.us/*",
      ]),
    );
    const contentScripts = manifest.content_scripts as Array<{
      matches: string[];
      js: string[];
      all_frames?: boolean;
      run_at?: string;
      world?: string;
    }>;
    const zoomScripts = contentScripts.filter((script) =>
      script.matches.includes("https://app.zoom.us/*"),
    );
    expect(zoomScripts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          js: ["zoom-main.js"],
          all_frames: true,
          run_at: "document_start",
          world: "MAIN",
        }),
        expect.objectContaining({
          js: ["content.js"],
          all_frames: true,
        }),
      ]),
    );
    expect(manifest.content_security_policy).toEqual({
      extension_pages:
        "script-src 'self'; object-src 'self'; frame-src http://127.0.0.1:38473",
    });
    expect(manifest.icons).toEqual({
      "16": "icons/elsewise-16.png",
      "32": "icons/elsewise-32.png",
      "48": "icons/elsewise-48.png",
      "128": "icons/elsewise-128.png",
    });
    expect(manifest.action).toEqual({
      default_title: "__MSG_appName__",
      default_popup: "popup.html",
      default_icon: {
        "16": "icons/elsewise-16.png",
        "32": "icons/elsewise-32.png",
      },
    });
    expect(JSON.stringify(manifest)).not.toContain("<all_urls>");
  });

  it("uses a Chrome service worker and Chrome side panel only", () => {
    const manifest = targetManifest("chrome");
    expect(manifest.minimum_chrome_version).toBe("116");
    expect(manifest.permissions).toEqual(
      expect.arrayContaining(["sidePanel", "tabs"]),
    );
    expect(manifest.background).toEqual({
      service_worker: "background.js",
      type: "module",
    });
    expect(manifest.side_panel).toEqual({ default_path: "sidepanel.html" });
    expect(manifest).not.toHaveProperty("sidebar_action");
    expect(manifest).not.toHaveProperty("browser_specific_settings");
  });

  it("uses a Firefox background module and Firefox sidebar only", () => {
    const manifest = targetManifest("firefox");
    expect(manifest.permissions).not.toContain("sidePanel");
    expect(manifest.background).toEqual({
      scripts: ["background.js"],
      type: "module",
    });
    expect(manifest.sidebar_action).toEqual({
      default_title: "__MSG_appName__",
      default_panel: "sidepanel.html",
      open_at_install: false,
    });
    expect(manifest).not.toHaveProperty("side_panel");
    expect(manifest).not.toHaveProperty("minimum_chrome_version");
    expect(manifest.browser_specific_settings).toEqual({
      gecko: {
        id: "{d410f9f2-4892-5d4a-b92e-f5c25db456e8}",
        strict_min_version: "140.0",
        data_collection_permissions: {
          required: [
            "authenticationInfo",
            "personalCommunications",
            "personallyIdentifyingInfo",
          ],
        },
      },
    });
  });

  it("ships complete catalogs for all six supported locales", () => {
    expect(targetManifest("firefox").default_locale).toBe("en");

    const englishKeys = Object.keys(localeMessages("en")).sort();
    for (const locale of ["ru", "fr", "es", "de", "pt_BR"]) {
      expect(Object.keys(localeMessages(locale)).sort()).toEqual(englishKeys);
    }
  });
});
