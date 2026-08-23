// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdapterUtteranceEvent } from "../src/adapters/base";
import { MicrosoftTeamsAdapter } from "../src/adapters/microsoft-teams";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Microsoft Teams synthetic soak", () => {
  it("processes an accelerated hour of revisions and evictions without duplicates", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <div data-tid="closed-caption-renderer-wrapper" aria-label="Live Captions">
        <div data-tid="closed-caption-v2-window-wrapper">
          <div data-tid="closed-caption-v2-virtual-list-content"><div role="list"></div></div>
        </div>
      </div>`;
    const list = document.querySelector('[role="list"]');
    if (!list) throw new Error("list missing");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    for (let index = 0; index < 600; index += 1) {
      const item = document.createElement("div");
      item.setAttribute("role", "listitem");
      item.innerHTML = `<div><span data-tid="author">Speaker ${index % 3}</span><span data-tid="closed-caption-text">part</span></div>`;
      list.append(item);
      await vi.advanceTimersByTimeAsync(1);
      const text = item.querySelector('[data-tid="closed-caption-text"]');
      if (!text) throw new Error("caption missing");
      text.textContent = `final segment ${index}`;
      await vi.advanceTimersByTimeAsync(1);
      item.remove();
      await vi.advanceTimersByTimeAsync(400);
    }

    const upserts = events.filter((event) => event.type === "upsert");
    const finalizes = events.filter((event) => event.type === "finalize");
    expect(new Set(upserts.map((event) => event.utteranceId)).size).toBe(600);
    expect(upserts).toHaveLength(1200);
    expect(finalizes).toHaveLength(600);
    adapter.stop();
  }, 20_000);
});
