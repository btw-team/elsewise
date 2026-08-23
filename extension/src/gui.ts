import {
  openBrowserPanel,
  type BrowserPanelApi,
  webExtension,
} from "./browser-api";

export const GUI_URL = "http://127.0.0.1:38473/";

type TabsApi = Pick<typeof webExtension.tabs, "create">;
type RuntimeApi = Pick<typeof webExtension.runtime, "getURL">;

export async function openGuiInNewTab(
  tabsApi: TabsApi = webExtension.tabs,
  runtimeApi: RuntimeApi = webExtension.runtime,
): Promise<void> {
  await tabsApi.create({
    url: runtimeApi.getURL("sidepanel.html"),
    active: true,
  });
}

export async function openGuiInSidePanel(
  tabId: number,
  panelApi?: BrowserPanelApi,
): Promise<void> {
  await openBrowserPanel(tabId, panelApi);
}

export async function guiIsAvailable(
  fetcher: typeof fetch = fetch,
  timeoutMs = 2_000,
): Promise<boolean> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(GUI_URL, {
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}
