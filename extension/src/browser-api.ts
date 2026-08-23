import type browser from "webextension-polyfill";

type WebExtensionApi = typeof browser;

const extensionScope = globalThis as typeof globalThis & {
  browser?: WebExtensionApi;
  chrome?: WebExtensionApi & BrowserPanelApi;
};

// Firefox exposes the standard Promise-based `browser` namespace. Chromium
// exposes the equivalent MV3 APIs as `chrome`. Keeping this choice here avoids
// leaking browser checks throughout the extension.
export const webExtension = (extensionScope.browser ??
  extensionScope.chrome ??
  {}) as WebExtensionApi;

export interface BrowserPanelApi {
  sidePanel?: {
    open(options: { tabId: number }): Promise<void> | void;
  };
  sidebarAction?: {
    open(): Promise<void> | void;
  };
}

function runtimePanelApi(): BrowserPanelApi {
  return {
    sidePanel: extensionScope.chrome?.sidePanel,
    sidebarAction:
      extensionScope.browser?.sidebarAction ??
      extensionScope.chrome?.sidebarAction,
  };
}

export async function openBrowserPanel(
  tabId: number,
  api: BrowserPanelApi = runtimePanelApi(),
): Promise<void> {
  if (api.sidePanel?.open) {
    await api.sidePanel.open({ tabId });
    return;
  }
  if (api.sidebarAction?.open) {
    await api.sidebarAction.open();
    return;
  }
  throw new Error("This browser does not expose a supported sidebar API.");
}
