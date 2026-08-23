import { describe, expect, it } from "vitest";

import { FrameElection } from "../src/background/frame-election";

describe("meeting frame election", () => {
  it("elects exactly one caption-bearing frame and rejects duplicate events", () => {
    const election = new FrameElection();
    expect(election.acceptStatus(7, 0, "off", 0)).toBe(true);
    expect(election.acceptStatus(7, 3, "capturing", 1)).toBe(true);
    expect(election.frameFor(7)).toBe(3);
    expect(election.acceptStatus(7, 4, "capturing", 1)).toBe(false);
    expect(election.acceptUtterance(7, 3)).toBe(true);
    expect(election.acceptUtterance(7, 4)).toBe(false);
  });

  it("re-elects after the active frame disconnects or turns captions off", () => {
    const election = new FrameElection();
    election.acceptStatus(9, 2, "on_empty", 1);
    election.disconnected(9, 2);
    expect(election.acceptStatus(9, 4, "capturing", 1)).toBe(true);
    expect(election.acceptStatus(9, 4, "off", 0)).toBe(true);
    expect(election.frameFor(9)).toBeUndefined();
    expect(election.acceptUtterance(9, 0)).toBe(true);
  });

  it("elects a Zoom same-origin meeting iframe over the empty outer shell", () => {
    const election = new FrameElection();
    expect(election.acceptStatus(11, 0, "off", 0.3)).toBe(true);
    expect(election.acceptStatus(11, 2, "on_empty", 1)).toBe(true);
    expect(election.frameFor(11)).toBe(2);
    expect(election.acceptStatus(11, 0, "off", 0.3)).toBe(false);
    expect(election.acceptUtterance(11, 2)).toBe(true);
    expect(election.acceptUtterance(11, 0)).toBe(false);
  });
});
