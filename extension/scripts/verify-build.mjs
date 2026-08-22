import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const target = process.argv[2];
if (target !== "chrome" && target !== "firefox") {
  throw new Error("Expected build target: chrome or firefox");
}

const output = resolve(import.meta.dirname, "..", "dist", target);
const manifest = JSON.parse(
  readFileSync(resolve(output, "manifest.json"), "utf8"),
);

for (const file of [
  "background.js",
  "content.js",
  "zoom-main.js",
  "popup.html",
  "sidepanel.html",
  "_locales/en/messages.json",
  "_locales/ru/messages.json",
  "_locales/fr/messages.json",
  "icons/elsewise-16.png",
  "icons/elsewise-32.png",
  "icons/elsewise-48.png",
  "icons/elsewise-128.png",
]) {
  readFileSync(resolve(output, file));
}

for (const file of ["content.js", "zoom-main.js"]) {
  const source = readFileSync(resolve(output, file), "utf8");
  if (/^\s*(?:import(?:[\s{*"']|$)|export(?:[\s{*]|$))/m.test(source)) {
    throw new Error(`${target}/${file} must remain a classic content script`);
  }
}

if (target === "chrome") {
  if (
    manifest.background?.service_worker !== "background.js" ||
    manifest.side_panel?.default_path !== "sidepanel.html" ||
    manifest.sidebar_action
  ) {
    throw new Error("The Chrome build contains an invalid target manifest");
  }
} else if (
  manifest.background?.scripts?.[0] !== "background.js" ||
  manifest.sidebar_action?.default_panel !== "sidepanel.html" ||
  manifest.browser_specific_settings?.gecko?.strict_min_version !== "140.0" ||
  !manifest.browser_specific_settings?.gecko?.data_collection_permissions ||
  manifest.side_panel ||
  manifest.permissions?.includes("sidePanel")
) {
  throw new Error("The Firefox build contains an invalid target manifest");
}

process.stdout.write(`Verified ${target} extension build at ${output}\n`);
