import type browser from "webextension-polyfill";

type WebExtensionApi = typeof browser;
const scope = globalThis as typeof globalThis & {
  browser?: WebExtensionApi;
  chrome?: WebExtensionApi;
};

// This module is background-entry-specific so Rollup can inline it into both
// Chrome's service worker and Firefox's background module.
export const backgroundApi = (scope.browser ?? scope.chrome) as WebExtensionApi;
