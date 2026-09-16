// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { DomSemanticObserver } from "../src/adapters/dom-semantics";
import type { AdapterEvidenceEvent } from "../src/adapters/base";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("DOM semantic observer", () => {
  it("reconciles lifecycle and participant current-state changes", async () => {
    document.body.innerHTML = "<main></main>";
    const observer = new DomSemanticObserver("synthetic", document);
    const events: AdapterEvidenceEvent[] = [];
    observer.start((event) => events.push(event));

    document.querySelector("main")?.insertAdjacentHTML(
      "beforeend",
      `<section data-elsewise-activity>
        <div data-elsewise-participant-id="p-1" data-display-name="Alice"
          data-is-self="true" data-active-speaker="true" data-muted="true"
          data-hand-raised="true"></div>
      </section>`,
    );
    await settle();

    const participant = document.querySelector("[data-elsewise-participant-id]");
    participant?.setAttribute("data-active-speaker", "false");
    participant?.setAttribute("data-muted", "false");
    participant?.removeAttribute("data-hand-raised");
    await settle();
    participant?.remove();
    await settle();
    document.querySelector("[data-elsewise-activity]")?.remove();
    await settle();

    expect(events.map((event) => event.kind)).toEqual([
      "activity.started",
      "participant.upsert",
      "participant.self",
      "speaker.started",
      "participant.muted",
      "participant.hand_raised",
      "speaker.stopped",
      "participant.unmuted",
      "participant.left",
      "activity.ended",
    ]);
    expect(events[1]?.payload).toEqual({
      participant_id: "p-1",
      display_label: "Alice",
    });
    observer.stop();
  });

  it("does not emit after stop and advertises only observed capabilities", async () => {
    document.body.innerHTML = `<section data-elsewise-activity>
      <div data-elsewise-participant-id="p-1"></div>
    </section>`;
    const observer = new DomSemanticObserver("synthetic", document);
    expect([...observer.capabilities()].sort()).toEqual([
      "activity_lifecycle",
      "participants",
    ]);
    const events: AdapterEvidenceEvent[] = [];
    observer.start((event) => events.push(event));
    observer.stop(false);
    const count = events.length;
    document.querySelector("[data-elsewise-participant-id]")?.remove();
    await settle();
    expect(events).toHaveLength(count);
  });
});
