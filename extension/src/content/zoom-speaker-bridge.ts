const ROOT_SELECTOR = "#live-transcription-subtitle";
const SPEAKER_ATTRIBUTE = "data-elsewise-speaker";
const MAX_SPEAKER_NAME_CHARACTERS = 512;

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function normalizedDisplayName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized || normalized.length > MAX_SPEAKER_NAME_CHARACTERS)
    return null;
  return normalized;
}

function displayNameFromProps(value: unknown): string | null {
  const queue: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
  const visited = new WeakSet<object>();
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    const record = objectRecord(current.value);
    if (!record || visited.has(record)) continue;
    visited.add(record);
    const displayName = normalizedDisplayName(record.displayName);
    if (displayName) return displayName;
    if (current.depth >= 4) continue;
    for (const key of ["props", "children"]) {
      const child = record[key];
      if (Array.isArray(child)) {
        for (const item of child)
          queue.push({ value: item, depth: current.depth + 1 });
      } else {
        queue.push({ value: child, depth: current.depth + 1 });
      }
    }
  }
  return null;
}

export function zoomDisplayNameFromRoot(root: HTMLElement): string | null {
  const privateKeys = Object.getOwnPropertyNames(root);
  for (const key of privateKeys) {
    if (!key.startsWith("__reactProps$")) continue;
    const displayName = displayNameFromProps(
      (root as unknown as Record<string, unknown>)[key],
    );
    if (displayName) return displayName;
  }
  for (const key of privateKeys) {
    if (!key.startsWith("__reactFiber$")) continue;
    let fiber = objectRecord((root as unknown as Record<string, unknown>)[key]);
    for (let depth = 0; fiber && depth < 5; depth += 1) {
      const displayName =
        displayNameFromProps(fiber.pendingProps) ??
        displayNameFromProps(fiber.memoizedProps);
      if (displayName) return displayName;
      fiber = objectRecord(fiber.child);
    }
  }
  return null;
}

export function annotateZoomCaptionSpeakers(document: Document): void {
  for (const root of document.querySelectorAll<HTMLElement>(ROOT_SELECTOR)) {
    const displayName = zoomDisplayNameFromRoot(root);
    if (displayName && root.getAttribute(SPEAKER_ATTRIBUTE) !== displayName) {
      root.setAttribute(SPEAKER_ATTRIBUTE, displayName);
    }
  }
}

export function installZoomSpeakerBridge(document: Document): () => void {
  const observer = new MutationObserver(() =>
    annotateZoomCaptionSpeakers(document),
  );
  const start = () => {
    annotateZoomCaptionSpeakers(document);
    if (document.documentElement) {
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }
  };
  if (document.documentElement) start();
  else document.addEventListener("readystatechange", start, { once: true });
  return () => observer.disconnect();
}
