// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { GoogleMeetAdapter } from "../src/adapters/google-meet";
import type {
  AdapterStatus,
  AdapterUtteranceEvent,
} from "../src/adapters/base";

const fixtures = `${resolve(process.cwd(), "../tests/fixtures/google-meet")}/`;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function load(name: string): void {
  document.body.innerHTML = readFileSync(`${fixtures}${name}`, "utf8");
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Google Meet adapter", () => {
  it("distinguishes captions off from enabled without speech", () => {
    load("captions-off.html");
    const offStatuses: AdapterStatus[] = [];
    const off = new GoogleMeetAdapter(document);
    expect(
      off.matchesLocation(new URL("https://meet.google.com/abc-defg-hij")),
    ).toBe(true);
    off.start(
      () => undefined,
      (status) => offStatuses.push(status),
    );
    expect(offStatuses.at(-1)?.captionsStatus).toBe("off");
    off.stop();

    load("captions-on-empty.html");
    const emptyStatuses: AdapterStatus[] = [];
    const empty = new GoogleMeetAdapter(document);
    empty.start(
      () => undefined,
      (status) => emptyStatuses.push(status),
    );
    expect(emptyStatuses.at(-1)).toMatchObject({
      captionsStatus: "on_empty",
      confidence: 1,
    });
    empty.stop();
  });

  it("tracks multiple speakers and non-monotonic revisions in place", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    expect(events).toHaveLength(2);
    const firstId = events[0]?.utteranceId;
    const text = document.querySelector<HTMLElement>(".ygicle");
    if (!text) throw new Error("caption text missing");
    text.textContent = "The first proposal is ready for review today.";
    await flush();
    text.textContent = "The first proposal is ready.";
    await flush();

    const firstEvents = events.filter((event) => event.utteranceId === firstId);
    expect(firstEvents.map((event) => event.revision)).toEqual([1, 2, 3]);
    expect(firstEvents.at(-1)?.text).toBe("The first proposal is ready.");
    expect(
      new Set(events.slice(0, 2).map((event) => event.utteranceId)).size,
    ).toBe(2);
    adapter.stop();
  });

  it("finalizes on speaker change and starts a new identity", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const speaker = document.querySelector<HTMLElement>(".KcIKyf span");
    if (!speaker) throw new Error("speaker missing");
    speaker.textContent = "Speaker C";
    await flush();

    const changed = events.filter((event) => event.speaker !== "Speaker B");
    expect(changed.slice(-2).map((event) => event.type)).toEqual([
      "finalize",
      "upsert",
    ]);
    expect(changed.at(-1)?.speaker).toBe("Speaker C");
    expect(changed.at(-1)?.utteranceId).not.toBe(changed[0]?.utteranceId);
    adapter.stop();
  });

  it("reconciles a temporarily reinserted block without a duplicate or finalize", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const region = document.querySelector('[role="region"]');
    const block = region?.querySelector(".nMcdL");
    if (!region || !block) throw new Error("fixture structure missing");
    block.remove();
    await flush();
    region.prepend(block);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    expect(events).toHaveLength(2);
    adapter.stop();
  });

  it("finalizes disconnected blocks and rediscovers a recreated caption region", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const statuses: AdapterStatus[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      (status) => statuses.push(status),
    );
    document.querySelector('[role="region"]')?.remove();
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(2);
    document.body.insertAdjacentHTML(
      "beforeend",
      '<div role="region" aria-label="Captions"><div><button>Jump to bottom</button></div></div>',
    );
    await flush();
    expect(statuses.at(-1)?.captionsStatus).toBe("on_empty");
    adapter.stop();
  });

  it("supports localized controls and an unknown speaker", () => {
    load("captions-ru-unknown.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    expect(events[0]).toMatchObject({
      speaker: null,
      text: "Текст без известного автора.",
    });
    expect(adapter.discover(document).confidence).toBe(1);
    adapter.stop();
  });

  it("uses a conservative idle finalize instead of short pause boundaries", () => {
    vi.useFakeTimers();
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new GoogleMeetAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    vi.advanceTimersByTime(15_000);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    vi.advanceTimersByTime(45_000);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(2);
    adapter.stop();
  });
});
