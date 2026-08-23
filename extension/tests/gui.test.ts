import { describe, expect, it, vi } from "vitest";

import type { BrowserPanelApi } from "../src/browser-api";
import {
  guiIsAvailable,
  openGuiInNewTab,
  openGuiInSidePanel,
} from "../src/gui";

describe("GUI launch controls", () => {
  it("opens the standard GUI in a new active tab", async () => {
    const create = vi.fn().mockResolvedValue({});
    const getURL = vi.fn().mockReturnValue("moz-extension://id/sidepanel.html");

    await openGuiInNewTab({ create }, { getURL });

    expect(getURL).toHaveBeenCalledWith("sidepanel.html");
    expect(create).toHaveBeenCalledWith({
      url: "moz-extension://id/sidepanel.html",
      active: true,
    });
  });

  it("opens the extension side panel for the current tab", async () => {
    const open = vi.fn().mockResolvedValue(undefined);

    await openGuiInSidePanel(42, { sidePanel: { open } });

    expect(open).toHaveBeenCalledWith({ tabId: 42 });
  });

  it("opens the Firefox sidebar without passing a Chrome tab id", async () => {
    const open = vi.fn().mockResolvedValue(undefined);

    await openGuiInSidePanel(42, {
      sidebarAction: { open },
    } satisfies BrowserPanelApi);

    expect(open).toHaveBeenCalledWith();
  });

  it("distinguishes an available GUI from a stopped server", async () => {
    const available = vi.fn().mockResolvedValue({ ok: true });
    const unavailable = vi
      .fn()
      .mockRejectedValue(new TypeError("connection refused"));

    await expect(guiIsAvailable(available as typeof fetch)).resolves.toBe(true);
    await expect(guiIsAvailable(unavailable as typeof fetch)).resolves.toBe(
      false,
    );
  });
});
