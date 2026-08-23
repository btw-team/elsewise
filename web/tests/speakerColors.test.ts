import { describe, expect, it } from "vitest";

import {
  assignSpeakerColors,
  DARK_SPEAKER_PALETTE,
  LIGHT_SPEAKER_PALETTE,
  loadSpeakerColors,
  normalizeSpeakerIdentity,
  saveSpeakerColors,
} from "../src/speakerColors";

describe("speaker colors", () => {
  it("defines matching seven-color palettes for dark and light themes", () => {
    expect(DARK_SPEAKER_PALETTE).toHaveLength(7);
    expect(LIGHT_SPEAKER_PALETTE).toHaveLength(7);
    expect(new Set(DARK_SPEAKER_PALETTE).size).toBe(7);
    expect(new Set(LIGHT_SPEAKER_PALETTE).size).toBe(7);
    expect(DARK_SPEAKER_PALETTE).not.toContain("#f7fbfa");
  });

  it("chooses only among the least-used colors and keeps existing assignments", () => {
    const speakers = Array.from(
      { length: 9 },
      (_, index) => `speaker-${index}`,
    );
    const first = assignSpeakerColors(new Map(), speakers, 7, () => 0);
    const firstSeven = speakers
      .slice(0, 7)
      .map((speaker) => first.get(speaker));
    expect(new Set(firstSeven).size).toBe(7);

    const counts = Array.from({ length: 7 }, () => 0);
    for (const colorIndex of first.values())
      counts[colorIndex] = (counts[colorIndex] ?? 0) + 1;
    expect(Math.max(...counts) - Math.min(...counts)).toBeLessThanOrEqual(1);

    const expanded = assignSpeakerColors(
      first,
      [...speakers, "new-speaker"],
      7,
      () => 0.99,
    );
    for (const speaker of speakers)
      expect(expanded.get(speaker)).toBe(first.get(speaker));
  });

  it("normalizes names and persists a versioned map per session", () => {
    expect(normalizeSpeakerIdentity("  ИВАН   Петров ")).toBe("иван петров");
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    const assignments = new Map([
      ["speaker-a", 2],
      ["speaker-b", 5],
    ]);
    saveSpeakerColors(storage, "session-1", assignments);
    expect(loadSpeakerColors(storage, "session-1")).toEqual(assignments);
    expect(loadSpeakerColors(storage, "session-2")).toEqual(new Map());
  });
});
