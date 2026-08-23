// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AdapterStatus,
  AdapterUtteranceEvent,
} from "../src/adapters/base";
import { ZoomAdapter } from "../src/adapters/zoom";

const fixtures = `${resolve(process.cwd(), "../tests/fixtures/zoom")}/`;
const flush = () =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
const settle = () =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, 200));

function fixture(name: string): string {
  return readFileSync(`${fixtures}${name}`, "utf8");
}

function load(name: string): void {
  document.body.innerHTML = fixture(name);
}

function captionContent(): HTMLElement {
  const content = document.querySelector<HTMLElement>(
    ".live-transcription-subtitle__content",
  );
  if (!content) throw new Error("caption content missing");
  return content;
}

function rootMarkup(avatar: string, text: string): string {
  return `<div id="live-transcription-subtitle" style="display: flex">
    <img class="zmu-data-selector-item__icon" src="https://example.invalid/${avatar}.png" alt="" aria-hidden="true" />
    <span class="live-transcription-subtitle__item">${text}</span>
  </div>`;
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Zoom Web adapter", () => {
  it("matches the Zoom Web Client origin only", () => {
    const adapter = new ZoomAdapter(document);
    expect(
      adapter.matchesLocation(
        new URL("https://app.zoom.us/wc/fixture/join?pwd=secret"),
      ),
    ).toBe(true);
    expect(adapter.matchesLocation(new URL("https://zoom.us/meeting"))).toBe(
      false,
    );
    expect(
      adapter.matchesLocation(new URL("https://meet.google.com/fixture")),
    ).toBe(false);
  });

  it("distinguishes captions off from enabled without speech", () => {
    load("captions-off.html");
    const offStatuses: AdapterStatus[] = [];
    const off = new ZoomAdapter(document);
    off.start(
      () => undefined,
      (status) => offStatuses.push(status),
    );
    expect(offStatuses.at(-1)?.captionsStatus).toBe("off");
    expect(off.discover(document).root).toBeNull();
    off.stop();

    load("captions-on-empty.html");
    const enabledStatuses: AdapterStatus[] = [];
    const enabled = new ZoomAdapter(document);
    enabled.start(
      () => undefined,
      (status) => enabledStatuses.push(status),
    );
    expect(enabledStatuses.at(-1)).toMatchObject({
      captionsStatus: "on_empty",
      confidence: 1,
    });
    enabled.stop();
  });

  it("tracks append, correction, and retraction revisions in place", async () => {
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const text = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    if (!text) throw new Error("caption text missing");
    text.textContent = "Alpha begins with a longer draft.";
    await settle();
    text.textContent = "Alpha begins with a corrected draft.";
    await settle();
    text.textContent = "Alpha begins.";
    await settle();

    expect(events.map((event) => event.revision)).toEqual([1, 2, 3, 4]);
    expect(events.at(-1)?.text).toBe("Alpha begins.");
    expect(new Set(events.map((event) => event.utteranceId)).size).toBe(1);
    expect(events.every((event) => event.speaker === null)).toBe(true);
    adapter.stop();
  });

  it("coalesces Zoom's transient overlapping caption layers", async () => {
    vi.useFakeTimers();
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const text = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    if (!text) throw new Error("caption text missing");

    text.textContent =
      "Alpha begins. A stale continuation.Alpha begins. A stale continuation overlaps the next layer.";
    await vi.advanceTimersByTimeAsync(50);
    text.textContent = "Alpha begins. A stable continuation.";
    await vi.advanceTimersByTimeAsync(150);

    expect(events.map((event) => event.text)).toEqual([
      "Alpha begins.",
      "Alpha begins. A stable continuation.",
    ]);
    expect(events.map((event) => event.revision)).toEqual([1, 2]);
    adapter.stop();
  });

  it("preserves a long rolling caption as ordered chunks", async () => {
    load("one-speaker.html");
    const text = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    if (!text) throw new Error("caption text missing");
    const words = Array.from(
      { length: 34 },
      (_, index) => `слово${String(index + 1).padStart(2, "0")}`,
    );
    text.textContent = words.slice(0, 9).join(" ");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    for (const [start, end] of [
      [0, 14],
      [5, 19],
      [10, 24],
      [15, 29],
      [20, 34],
    ]) {
      text.textContent = words.slice(start, end).join(" ");
      await settle();
    }
    document.querySelector<HTMLElement>(
      "#live-transcription-subtitle",
    )!.style.display = "none";
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 550));

    const finalized = events.filter((event) => event.type === "finalize");
    expect(finalized.length).toBeGreaterThan(1);
    expect(finalized.every((event) => event.text.length <= 80)).toBe(true);
    expect(finalized.map((event) => event.text).join(" ")).toBe(
      words.join(" "),
    );
    expect(new Set(finalized.map((event) => event.utteranceId)).size).toBe(
      finalized.length,
    );
    adapter.stop();
  });

  it("reads the speaker name from the main-world bridge attribute", () => {
    load("one-speaker.html");
    const root = document.querySelector<HTMLElement>(
      "#live-transcription-subtitle",
    );
    if (!root) throw new Error("caption root missing");
    root.setAttribute("data-elsewise-speaker", "  Chu   Kimba  ");
    const events: AdapterUtteranceEvent[] = [];
    const statuses: AdapterStatus[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      (status) => statuses.push(status),
    );

    expect(events[0]).toMatchObject({
      speaker: "Chu Kimba",
      text: "Alpha begins.",
    });
    expect(statuses.at(-1)?.speakerDetection).toBe("available");
    const diagnostic = adapter.dumpDiagnostics({ redactNames: true });
    expect(diagnostic.subtree).not.toContain("Chu Kimba");
    expect(diagnostic.subtree).toContain('data-elsewise-speaker="[speaker]"');
    adapter.stop();
  });

  it("reconciles a same-avatar root replacement as one rolling utterance", async () => {
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const firstId = events[0]?.utteranceId;
    document.querySelector("#live-transcription-subtitle")?.remove();
    captionContent().insertAdjacentHTML(
      "afterbegin",
      rootMarkup("avatar-a", "Alpha begins. A second clause follows."),
    );
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 400));

    expect(events.filter((event) => event.type === "upsert")).toHaveLength(2);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    expect(events.at(-1)).toMatchObject({
      utteranceId: firstId,
      revision: 2,
      text: "Alpha begins. A second clause follows.",
    });
    adapter.stop();
  });

  it("keeps simultaneous distinct-avatar roots as separate anonymous utterances", () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const statuses: AdapterStatus[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      (status) => statuses.push(status),
    );

    expect(events).toHaveLength(2);
    expect(new Set(events.map((event) => event.utteranceId)).size).toBe(2);
    expect(events.map((event) => event.speaker)).toEqual([null, null]);
    expect(statuses.at(-1)).toMatchObject({
      captionsStatus: "capturing",
      speakerDetection: "unavailable",
    });
    adapter.stop();
  });

  it("keeps interleaved rolling streams isolated by speaker", async () => {
    load("two-speakers.html");
    const roots = Array.from(
      document.querySelectorAll<HTMLElement>("#live-transcription-subtitle"),
    );
    const annaText = roots[0]?.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    const selfText = roots[1]?.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    if (!roots[0] || !roots[1] || !annaText || !selfText)
      throw new Error("speaker fixtures missing");
    roots[0].setAttribute("data-elsewise-speaker", "Anna Tolkacheva");
    roots[1].setAttribute("data-elsewise-speaker", "Chu Kimba");
    const annaWords = Array.from(
      { length: 30 },
      (_, index) => `anna${String(index + 1).padStart(2, "0")}`,
    );
    const selfWords = Array.from(
      { length: 12 },
      (_, index) => `self${String(index + 1).padStart(2, "0")}`,
    );
    annaText.textContent = annaWords.slice(0, 8).join(" ");
    selfText.textContent = selfWords.slice(0, 4).join(" ");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    for (const [annaEnd, selfEnd] of [
      [14, 6],
      [18, 8],
      [22, 8],
      [26, 10],
      [30, 12],
    ] as const) {
      annaText.textContent = annaWords
        .slice(Math.max(0, annaEnd - 14), annaEnd)
        .join(" ");
      selfText.textContent = selfWords.slice(0, selfEnd).join(" ");
      await settle();
    }
    roots.forEach((root) => {
      root.style.display = "none";
    });
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 550));

    const finalized = events.filter((event) => event.type === "finalize");
    expect(
      finalized
        .filter((event) => event.speaker === "Anna Tolkacheva")
        .map((event) => event.text)
        .join(" "),
    ).toBe(annaWords.join(" "));
    expect(
      finalized
        .filter((event) => event.speaker === "Chu Kimba")
        .map((event) => event.text)
        .join(" "),
    ).toBe(selfWords.join(" "));
    adapter.stop();
  });

  it("finalizes when Zoom hides a root even though the node remains mounted", async () => {
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const root = document.querySelector<HTMLElement>(
      "#live-transcription-subtitle",
    );
    if (!root) throw new Error("caption root missing");
    root.style.display = "none";
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 550));

    expect(events.at(-1)).toMatchObject({
      type: "finalize",
      text: "Alpha begins.",
    });
    expect(root.isConnected).toBe(true);
    adapter.stop();
  });

  it("suppresses off/on historical replay and emits only genuinely new speech", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const statuses: AdapterStatus[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      (status) => statuses.push(status),
    );
    expect(events.filter((event) => event.type === "upsert")).toHaveLength(2);

    document
      .querySelector(".live-transcription-subtitle__overlay-container")
      ?.remove();
    const control = document.querySelector<HTMLElement>("#captions button");
    if (!control) throw new Error("caption control missing");
    control.setAttribute("aria-label", "Show Captions");
    control.textContent = "Show Captions";
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 400));
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(2);
    expect(statuses.some((status) => status.captionsStatus === "off")).toBe(
      true,
    );

    document.body.innerHTML = fixture("two-speakers.html");
    await flush();
    expect(events.filter((event) => event.type === "upsert")).toHaveLength(2);

    const content = captionContent();
    content.replaceChildren();
    content.insertAdjacentHTML(
      "afterbegin",
      rootMarkup("avatar-a", "Fresh speech after restart."),
    );
    await settle();
    const upserts = events.filter((event) => event.type === "upsert");
    expect(upserts).toHaveLength(3);
    expect(upserts.at(-1)).toMatchObject({
      revision: 1,
      speaker: null,
      text: "Fresh speech after restart.",
    });
    adapter.stop();
  });

  it("survives unrelated Speaker/Gallery layout mutations", async () => {
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const meeting = document.querySelector(".meeting-client-inner");
    meeting?.classList.add("gallery-view");
    meeting?.classList.replace("gallery-view", "speaker-view");
    await flush();
    expect(events).toHaveLength(1);
    adapter.stop();
  });

  it("redacts caption text, avatar source, and URL secrets from diagnostics", () => {
    load("two-speakers.html");
    const adapter = new ZoomAdapter(document);
    adapter.start(
      () => undefined,
      () => undefined,
    );
    const diagnostic = adapter.dumpDiagnostics({
      redactText: true,
      redactNames: true,
    });
    expect(diagnostic.subtree).not.toContain("Alpha begins.");
    expect(diagnostic.subtree).not.toContain("Bravo replies.");
    expect(diagnostic.subtree).not.toContain("example.invalid");
    expect(diagnostic.sanitizedUrl).not.toContain("?");
    adapter.stop();
  });

  it("splits a persistent caption after a five-second pause without replaying its prefix", async () => {
    vi.useFakeTimers();
    load("one-speaker.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new ZoomAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const firstId = events[0]?.utteranceId;
    await vi.advanceTimersByTimeAsync(4_999);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(1);

    const text = document.querySelector<HTMLElement>(
      ".live-transcription-subtitle__item",
    );
    if (!text) throw new Error("caption text missing");
    text.textContent = "Alpha begins. A separate reply follows.";
    await vi.advanceTimersByTimeAsync(150);

    const upserts = events.filter((event) => event.type === "upsert");
    expect(upserts.at(-1)).toMatchObject({
      revision: 1,
      text: "A separate reply follows.",
    });
    expect(upserts.at(-1)?.utteranceId).not.toBe(firstId);
    adapter.stop();
  });
});
