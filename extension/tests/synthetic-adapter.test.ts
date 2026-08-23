// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { SyntheticAdapter } from "../src/adapters/synthetic";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("synthetic adapter", () => {
  it("emits revisions in place and finalizes removed utterances", async () => {
    document.body.innerHTML = `
      <section data-elsewise-captions>
        <article data-utterance-id="u1" data-speaker="Speaker A">
          <span data-caption-text>Hello</span>
        </article>
      </section>`;
    const adapter = new SyntheticAdapter(document);
    const events: Array<{ type: string; revision: number; text: string }> = [];
    adapter.start(
      (event) => events.push(event),
      () => undefined,
    );

    const text = document.querySelector("[data-caption-text]");
    if (!text) throw new Error("caption text missing");
    text.textContent = "Hello world";
    await settle();
    document.querySelector("[data-utterance-id]")?.remove();
    await settle();

    expect(events).toEqual([
      expect.objectContaining({ type: "upsert", revision: 1, text: "Hello" }),
      expect.objectContaining({
        type: "upsert",
        revision: 2,
        text: "Hello world",
      }),
      expect.objectContaining({
        type: "finalize",
        revision: 2,
        text: "Hello world",
      }),
    ]);
    adapter.stop();
  });

  it("creates a bounded redacted subtree diagnostic", () => {
    document.body.innerHTML = `
      <section data-elsewise-captions>
        <article data-utterance-id="u1" data-speaker="Private Name" data-participant-id="secret">
          <a href="https://secret.invalid/token"><span data-caption-text>Private text</span></a>
        </article>
      </section>`;
    const adapter = new SyntheticAdapter(document);
    adapter.start(
      () => undefined,
      () => undefined,
    );
    const dump = adapter.dumpDiagnostics({
      redactNames: true,
      redactText: true,
    });
    expect(dump.subtree).toContain("[speaker]");
    expect(dump.subtree).toContain("[caption text]");
    expect(dump.subtree).not.toContain("Private Name");
    expect(dump.subtree).not.toContain("secret.invalid");
    expect(dump.subtree?.length).toBeLessThanOrEqual(100_000);
    adapter.stop();
  });
});
