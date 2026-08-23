// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import type { AdapterUtteranceEvent } from "../src/adapters/base";
import { ZoomAdapter } from "../src/adapters/zoom";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Zoom Web synthetic soak", () => {
  it("preserves a three-minute rolling window without losing its evicted prefix", async () => {
    vi.useFakeTimers();
    const words = Array.from(
      { length: 180 },
      (_, index) => `слово${String(index + 1).padStart(3, "0")}`,
    );
    document.body.innerHTML = `
      <div class="meeting-client-inner">
        <div id="captions" data-feature-type="captions">
          <button aria-label="Hide Captions">Hide Captions</button>
        </div>
        <div class="live-transcription-subtitle__overlay-container">
          <div class="live-transcription-subtitle__content">
            <div id="live-transcription-subtitle" style="display: flex">
              <img class="zmu-data-selector-item__icon" src="https://example.invalid/avatar-a.png" alt="" />
              <span class="live-transcription-subtitle__item">${words.slice(0, 8).join(" ")}</span>
            </div>
          </div>
        </div>
        <div class="lt-subtitle-wrap"></div>
      </div>`;
    const text = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    const root = document.querySelector<HTMLElement>(
      "#live-transcription-subtitle",
    );
    if (!text || !root) throw new Error("caption fixture missing");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    for (let end = 9; end <= words.length; end += 1) {
      text.textContent = words.slice(Math.max(0, end - 14), end).join(" ");
      await vi.advanceTimersByTimeAsync(1_000);
    }
    root.style.display = "none";
    await vi.advanceTimersByTimeAsync(550);

    const finalized = events.filter((event) => event.type === "finalize");
    expect(finalized.length).toBeGreaterThan(10);
    expect(finalized.every((event) => event.text.length <= 80)).toBe(true);
    expect(finalized.map((event) => event.text).join(" ")).toBe(
      words.join(" "),
    );
    adapter.stop();
  });

  it("processes an accelerated hour of revisions and hidden roots without duplicates", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <div class="meeting-client-inner">
        <div id="captions" data-feature-type="captions">
          <button aria-label="Hide Captions">Hide Captions</button>
        </div>
        <div class="live-transcription-subtitle__overlay-container">
          <div class="live-transcription-subtitle__content"></div>
        </div>
        <div class="lt-subtitle-wrap"></div>
      </div>`;
    const content = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__content",
    );
    if (!content) throw new Error("caption content missing");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    for (let index = 0; index < 600; index += 1) {
      const root = document.createElement("div");
      root.id = "live-transcription-subtitle";
      root.style.display = "flex";
      root.innerHTML = `<img class="zmu-data-selector-item__icon" src="https://example.invalid/avatar-${index % 2}.png" alt="" /><span class="live-transcription-subtitle__item">part ${index}</span>`;
      content.append(root);
      await vi.advanceTimersByTimeAsync(200);
      const text = root.querySelector(".live-transcription-subtitle__item");
      if (!text) throw new Error("caption text missing");
      text.textContent = `final segment ${index}`;
      await vi.advanceTimersByTimeAsync(200);
      root.style.display = "none";
      await vi.advanceTimersByTimeAsync(550);
      root.remove();
      await vi.advanceTimersByTimeAsync(200);
    }

    const upserts = events.filter((event) => event.type === "upsert");
    const finalizes = events.filter((event) => event.type === "finalize");
    expect(new Set(upserts.map((event) => event.utteranceId)).size).toBe(600);
    expect(upserts).toHaveLength(1200);
    expect(finalizes).toHaveLength(600);
    adapter.stop();
  }, 60_000);
});
