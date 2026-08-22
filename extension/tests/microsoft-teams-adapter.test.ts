// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AdapterStatus,
  AdapterUtteranceEvent,
} from "../src/adapters/base";
import { MicrosoftTeamsAdapter } from "../src/adapters/microsoft-teams";

const fixtures = `${resolve(process.cwd(), "../tests/fixtures/microsoft-teams")}/`;
const flush = () =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, 0));

function load(name: string): void {
  document.body.innerHTML = readFileSync(`${fixtures}${name}`, "utf8");
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Microsoft Teams adapter", () => {
  it("matches personal and corporate web origins only", () => {
    const adapter = new MicrosoftTeamsAdapter(document);
    expect(adapter.matchesLocation(new URL("https://teams.live.com/v2/"))).toBe(
      true,
    );
    expect(
      adapter.matchesLocation(new URL("https://teams.microsoft.com/v2/")),
    ).toBe(true);
    expect(
      adapter.matchesLocation(
        new URL("https://emea.teams.microsoft.com/meeting"),
      ),
    ).toBe(true);
    expect(
      adapter.matchesLocation(new URL("https://microsoft.com/teams")),
    ).toBe(false);
  });

  it("distinguishes captions off and enabled without speech", () => {
    load("captions-off.html");
    const statuses: AdapterStatus[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      () => undefined,
      (status) => statuses.push(status),
    );
    expect(statuses.at(-1)?.captionsStatus).toBe("off");
    expect(adapter.discover(document).root).toBeNull();
    adapter.stop();

    load("captions-on-empty.html");
    const enabled: AdapterStatus[] = [];
    const enabledAdapter = new MicrosoftTeamsAdapter(document);
    enabledAdapter.start(
      () => undefined,
      (status) => enabled.push(status),
    );
    expect(enabled.at(-1)).toMatchObject({
      captionsStatus: "on_empty",
      confidence: 1,
    });
    enabledAdapter.stop();
  });

  it("treats pause-separated fields as distinct utterances", () => {
    load("paused-utterances.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    expect(events).toHaveLength(4);
    expect(new Set(events.map((event) => event.utteranceId)).size).toBe(4);
    expect(new Set(events.map((event) => event.speaker))).toEqual(
      new Set(["Speaker A"]),
    );
    adapter.stop();
  });

  it("replaces the full text for append, correction, and retraction revisions", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const text = document.querySelector<HTMLElement>(
      '[data-tid="closed-caption-text"]',
    );
    if (!text) throw new Error("caption text missing");
    const firstId = events[0]?.utteranceId;
    text.textContent = "First speaker text grows.";
    await flush();
    text.textContent = "Corrected phrase.";
    await flush();
    text.textContent = "Short.";
    await flush();
    const revisions = events.filter((event) => event.utteranceId === firstId);
    expect(revisions.map((event) => event.revision)).toEqual([1, 2, 3, 4]);
    expect(revisions.at(-1)?.text).toBe("Short.");
    adapter.stop();
  });

  it("captures a changed speaker directly and finalizes virtual-list eviction", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    expect(events.slice(0, 2).map((event) => event.speaker)).toEqual([
      "Speaker A",
      "Speaker B",
    ]);
    document.querySelector('[role="listitem"]')?.remove();
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 400));
    const finalized = events.find(
      (event) => event.type === "finalize" && event.speaker === "Speaker A",
    );
    expect(finalized?.text).toBe("First speaker text.");
    adapter.stop();
  });

  it("keeps one identity when Teams resolves Unknown User to a guest name", async () => {
    load("speaker-layout.html");
    const author = document.querySelector<HTMLElement>('[data-tid="author"]');
    const text = document.querySelector<HTMLElement>(
      '[data-tid="closed-caption-text"]',
    );
    if (!author || !text) throw new Error("caption fields missing");
    author.textContent = "Unknown User";
    text.textContent =
      "Ну мы пытаемся понять перестановки предметов в комате и перегенерировать их в 3 д";
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const firstId = events[0]?.utteranceId;

    author.textContent = "Anna";
    text.textContent =
      "Ну мы пытаемся понять перестановки предметов в комнате и перегенерировать их в 3 д.";
    await flush();

    expect(events).toHaveLength(2);
    expect(events.map((event) => event.type)).toEqual(["upsert", "upsert"]);
    expect(events.map((event) => event.utteranceId)).toEqual([
      firstId,
      firstId,
    ]);
    expect(events.map((event) => event.revision)).toEqual([1, 2]);
    expect(events.map((event) => event.speaker)).toEqual([
      "Unknown User",
      "Anna",
    ]);
    expect(events.at(-1)?.text).toBe(
      "Ну мы пытаемся понять перестановки предметов в комнате и перегенерировать их в 3 д.",
    );
    adapter.stop();
  });

  it("still splits a recycled Unknown User node when the text is unrelated", async () => {
    load("speaker-layout.html");
    const author = document.querySelector<HTMLElement>('[data-tid="author"]');
    const text = document.querySelector<HTMLElement>(
      '[data-tid="closed-caption-text"]',
    );
    if (!author || !text) throw new Error("caption fields missing");
    author.textContent = "Unknown User";
    text.textContent = "The first participant finishes a thought.";
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const firstId = events[0]?.utteranceId;

    author.textContent = "Anna";
    text.textContent = "A completely different sentence begins.";
    await flush();

    expect(events.map((event) => event.type)).toEqual([
      "upsert",
      "finalize",
      "upsert",
    ]);
    expect(events[1]?.utteranceId).toBe(firstId);
    expect(events[2]?.utteranceId).not.toBe(firstId);
    expect(events[2]?.speaker).toBe("Anna");
    adapter.stop();
  });

  it("reconciles temporary reinsertion without duplicate or finalize", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    const list = document.querySelector('[role="list"]');
    const item = list?.firstElementChild;
    if (!list || !item) throw new Error("fixture structure missing");
    item.remove();
    await flush();
    list.prepend(item);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 400));
    expect(events).toHaveLength(2);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    adapter.stop();
  });

  it("finalizes on captions off and rediscovers a fresh empty root", async () => {
    load("two-speakers.html");
    const events: AdapterUtteranceEvent[] = [];
    const statuses: AdapterStatus[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      (status) => statuses.push(status),
    );
    document
      .querySelector('[data-tid="closed-caption-renderer-wrapper"]')
      ?.remove();
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 400));
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(2);
    expect(statuses.some((status) => status.captionsStatus === "off")).toBe(
      true,
    );
    document.body.innerHTML = readFileSync(
      `${fixtures}captions-on-empty.html`,
      "utf8",
    );
    await flush();
    expect(statuses.at(-1)?.captionsStatus).toBe("on_empty");
    adapter.stop();
  });

  it("uses the same extraction in Speaker layout and redacts diagnostics", () => {
    load("speaker-layout.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    expect(events[0]).toMatchObject({
      speaker: "Speaker C",
      text: "Speaker layout uses the same fields.",
    });
    const diagnostic = adapter.dumpDiagnostics({
      redactText: true,
      redactNames: true,
    });
    expect(diagnostic.subtree).not.toContain("Speaker C");
    expect(diagnostic.subtree).not.toContain(
      "Speaker layout uses the same fields.",
    );
    expect(diagnostic.sanitizedUrl).not.toContain("?");
    adapter.stop();
  });

  it("keeps short pauses partial and conservatively finalizes after 60 seconds", () => {
    vi.useFakeTimers();
    load("speaker-layout.html");
    const events: AdapterUtteranceEvent[] = [];
    const adapter = new MicrosoftTeamsAdapter(document);
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );
    vi.advanceTimersByTime(15_000);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(0);
    vi.advanceTimersByTime(45_000);
    expect(events.filter((event) => event.type === "finalize")).toHaveLength(1);
    adapter.stop();
  });
});
