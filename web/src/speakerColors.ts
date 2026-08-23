export const DARK_SPEAKER_PALETTE = [
  "#d88962",
  "#d4a24f",
  "#a6b86b",
  "#73b184",
  "#6fa7a0",
  "#a997c8",
  "#d58aa6",
] as const;

export const LIGHT_SPEAKER_PALETTE = [
  "#9d3f24",
  "#8a5c00",
  "#5c6e1d",
  "#317346",
  "#2c6b68",
  "#65508f",
  "#9b3f66",
] as const;

const STORAGE_VERSION = 1;
const STORAGE_PREFIX = "elsewise-speaker-colors";

interface StoredSpeakerColors {
  version: typeof STORAGE_VERSION;
  assignments: Array<[string, number]>;
}

export function normalizeSpeakerIdentity(name: string): string {
  return name.normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

export function assignSpeakerColors(
  existing: ReadonlyMap<string, number>,
  speakers: readonly string[],
  paletteSize: number,
  random: () => number = Math.random,
): Map<string, number> {
  const assignments = new Map(
    [...existing].filter(
      ([, colorIndex]) =>
        Number.isInteger(colorIndex) &&
        colorIndex >= 0 &&
        colorIndex < paletteSize,
    ),
  );
  if (paletteSize === 0) return assignments;

  const usage = Array.from({ length: paletteSize }, () => 0);
  for (const colorIndex of assignments.values())
    usage[colorIndex] = (usage[colorIndex] ?? 0) + 1;

  for (const speaker of speakers) {
    if (assignments.has(speaker)) continue;
    const leastUsed = Math.min(...usage);
    const candidates = usage
      .map((count, colorIndex) => ({ count, colorIndex }))
      .filter(({ count }) => count === leastUsed);
    const choice = Math.min(
      candidates.length - 1,
      Math.floor(Math.max(0, random()) * candidates.length),
    );
    const colorIndex = candidates[choice]?.colorIndex ?? 0;
    assignments.set(speaker, colorIndex);
    usage[colorIndex] = (usage[colorIndex] ?? 0) + 1;
  }
  return assignments;
}

export function loadSpeakerColors(
  storage: Pick<Storage, "getItem">,
  sessionId: string,
): Map<string, number> {
  try {
    const raw = storage.getItem(`${STORAGE_PREFIX}:${sessionId}`);
    if (!raw) return new Map();
    const stored = JSON.parse(raw) as Partial<StoredSpeakerColors>;
    if (
      stored.version !== STORAGE_VERSION ||
      !Array.isArray(stored.assignments)
    )
      return new Map();
    return new Map(
      stored.assignments.filter(
        (entry): entry is [string, number] =>
          Array.isArray(entry) &&
          entry.length === 2 &&
          typeof entry[0] === "string" &&
          typeof entry[1] === "number",
      ),
    );
  } catch {
    return new Map();
  }
}

export function saveSpeakerColors(
  storage: Pick<Storage, "setItem">,
  sessionId: string,
  assignments: ReadonlyMap<string, number>,
): void {
  const stored: StoredSpeakerColors = {
    version: STORAGE_VERSION,
    assignments: [...assignments],
  };
  try {
    storage.setItem(`${STORAGE_PREFIX}:${sessionId}`, JSON.stringify(stored));
  } catch {
    // A blocked or full browser store must not prevent transcript rendering.
  }
}
