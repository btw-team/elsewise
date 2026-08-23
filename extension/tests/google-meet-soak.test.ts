// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { GoogleMeetAdapter } from "../src/adapters/google-meet";
import type { AdapterUtteranceEvent } from "../src/adapters/base";

afterEach(() => vi.useRealTimers());

describe("Google Meet accelerated soak", () => {
  it("keeps one revisioned identity through a generated 60-minute stream", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <button aria-label="Turn off captions">CC</button>
      <div role="region" aria-label="Captions">
        <div class="nMcdL"><img alt=""><div>
          <div class="KcIKyf"><span>Speaker A</span></div>
          <div class="ygicle">Revision 0</div>
        </div></div>
      </div>`;
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const text = document.querySelector<HTMLElement>(".ygicle");
    if (!text) throw new Error("caption text missing");

    for (let index = 1; index <= 600; index += 1) {
      text.textContent = `Revision ${index % 17}: generated meeting caption`;
      await Promise.resolve();
      vi.advanceTimersByTime(6_000);
    }

    const upserts = events.filter((event) => event.type === "upsert");
    expect(upserts.length).toBeGreaterThan(590);
    expect(new Set(upserts.map((event) => event.utteranceId)).size).toBe(1);
    expect(events.some((event) => event.type === "finalize")).toBe(false);
    vi.advanceTimersByTime(60_000);
    expect(events.at(-1)?.type).toBe("finalize");
    adapter.stop();
  });
});
