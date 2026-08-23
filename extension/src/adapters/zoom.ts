import { sanitizeSubtree, sanitizeUrl } from "../content/diagnostics";
import type {
  AdapterStatus,
  AdapterUtteranceEvent,
  DiagnosticBundle,
  DiscoveryResult,
  PlatformAdapter,
} from "./base";

const extensionVersion = __EXTENSION_VERSION__;

const OVERLAY_SELECTOR = ".live-transcription-subtitle__overlay-container";
const WRAPPER_SELECTOR = ".lt-subtitle-wrap";
const ROOT_SELECTOR = "#live-transcription-subtitle";
const TEXT_SELECTOR = ".live-transcription-subtitle__item";
const AVATAR_SELECTOR = "img.zmu-data-selector-item__icon";
const SHOW_CONTROL = /show captions|показать субтитры/i;
const HIDE_CONTROL = /hide captions|скрыть субтитры/i;
const RECONCILIATION_MILLISECONDS = 350;
const MUTATION_SETTLE_MILLISECONDS = 150;
const IDLE_FINALIZE_MILLISECONDS = 5_000;
const MAX_UTTERANCE_CHARACTERS = 80;
const TARGET_REMAINDER_CHARACTERS = 30;
const MIN_CHUNK_CHARACTERS = 20;
const MAX_REPLAY_FINGERPRINTS = 200;
const MAX_SPEAKER_NAME_CHARACTERS = 512;
const SPEAKER_ATTRIBUTE = "data-elsewise-speaker";

interface SegmentState {
  id: string;
  revision: number;
  speakerKey: string | null;
  speaker: string | null;
  text: string;
  visibleText: string;
  activeStart: number;
  final: boolean;
  idleTimer: ReturnType<typeof setTimeout> | null;
  removalTimer: ReturnType<typeof setTimeout> | null;
}

interface ExtractedSegment {
  root: HTMLElement;
  speakerKey: string | null;
  speaker: string | null;
  text: string;
}

function normalizedDisplayName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized || normalized.length > MAX_SPEAKER_NAME_CHARACTERS)
    return null;
  return normalized;
}

function zoomDisplayName(root: HTMLElement): string | null {
  return normalizedDisplayName(root.getAttribute(SPEAKER_ATTRIBUTE));
}

function normalizedText(node: Element | null): string {
  return node?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function contentStart(text: string, index: number): number {
  let start = Math.max(0, Math.min(index, text.length));
  while (start < text.length && /\s/u.test(text[start]!)) start += 1;
  return start;
}

interface TextToken {
  key: string;
  start: number;
}

function textTokens(text: string): TextToken[] {
  return Array.from(text.matchAll(/[\p{L}\p{N}]+/gu), (match) => ({
    key: match[0].toLocaleLowerCase(),
    start: match.index,
  }));
}

function mappedTextBoundary(
  previous: string,
  next: string,
  boundary: number,
): number {
  if (boundary <= 0) return 0;
  if (!previous || !next) return 0;

  const left = textTokens(previous);
  const right = textTokens(next);
  const boundaryToken = left.findIndex((token) => token.start >= boundary);
  const activeToken = boundaryToken === -1 ? left.length : boundaryToken;
  const lengths = Array.from(
    { length: left.length + 1 },
    () => new Uint32Array(right.length + 1),
  );

  for (let leftIndex = left.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = right.length - 1; rightIndex >= 0; rightIndex -= 1) {
      lengths[leftIndex]![rightIndex] =
        left[leftIndex]!.key === right[rightIndex]!.key
          ? lengths[leftIndex + 1]![rightIndex + 1]! + 1
          : Math.max(
              lengths[leftIndex + 1]![rightIndex]!,
              lengths[leftIndex]![rightIndex + 1]!,
            );
    }
  }

  let leftIndex = 0;
  let rightIndex = 0;
  let lastCommittedToken = -1;
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex]!.key === right[rightIndex]!.key) {
      if (leftIndex >= activeToken)
        return contentStart(next, right[rightIndex]!.start);
      lastCommittedToken = rightIndex;
      leftIndex += 1;
      rightIndex += 1;
    } else if (
      lengths[leftIndex + 1]![rightIndex]! >=
      lengths[leftIndex]![rightIndex + 1]!
    ) {
      leftIndex += 1;
    } else {
      rightIndex += 1;
    }
  }

  return right[lastCommittedToken + 1]?.start ?? next.length;
}

function chunkSplitIndex(text: string): number | null {
  if (text.length <= MAX_UTTERANCE_CHARACTERS) return null;
  const maximum = Math.min(
    MAX_UTTERANCE_CHARACTERS,
    text.length - MIN_CHUNK_CHARACTERS,
  );
  const target = Math.max(
    MIN_CHUNK_CHARACTERS,
    Math.min(maximum, text.length - TARGET_REMAINDER_CHARACTERS),
  );
  const sentenceBoundaries = Array.from(
    text.matchAll(/[.!?…](?:["»')\]]*)\s+/gu),
    (match) => match.index + match[0].length,
  ).filter((index) => index >= MIN_CHUNK_CHARACTERS && index <= maximum);
  const preferredSentence = sentenceBoundaries
    .filter((index) => index <= target)
    .at(-1);
  if (preferredSentence !== undefined) return preferredSentence;
  if (sentenceBoundaries[0] !== undefined) return sentenceBoundaries[0];

  const whitespace = text.lastIndexOf(" ", target);
  if (whitespace >= MIN_CHUNK_CHARACTERS) return whitespace + 1;
  return target;
}

function controlLabels(document: Document): string[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      '#captions, [data-feature-type="captions"], [aria-label*="caption" i], [role="button"]',
    ),
  )
    .map((element) =>
      [element.getAttribute("aria-label"), element.innerText]
        .filter(Boolean)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter((label) => SHOW_CONTROL.test(label) || HIDE_CONTROL.test(label));
}

function isRendered(root: HTMLElement): boolean {
  return getComputedStyle(root).display !== "none";
}

function relationScore(left: string, right: string): number {
  const a = left.toLocaleLowerCase();
  const b = right.toLocaleLowerCase();
  if (a === b) return 100_000 + a.length;
  if (a.includes(b) || b.includes(a))
    return 50_000 + Math.min(a.length, b.length);

  let prefix = 0;
  while (prefix < Math.min(a.length, b.length) && a[prefix] === b[prefix])
    prefix += 1;

  let suffixPrefix = 0;
  const maximum = Math.min(a.length, b.length);
  for (let length = maximum; length >= 1; length -= 1) {
    if (a.endsWith(b.slice(0, length)) || b.endsWith(a.slice(0, length))) {
      suffixPrefix = length;
      break;
    }
  }
  return Math.max(prefix, suffixPrefix);
}

export class ZoomAdapter implements PlatformAdapter {
  readonly platform = "zoom" as const;
  readonly #document: Document;
  readonly #documentIdentity = crypto.randomUUID().slice(0, 8);
  #overlay: Element | null = null;
  #overlayObserver: MutationObserver | null = null;
  #lifecycleObserver: MutationObserver | null = null;
  #segments = new Map<HTMLElement, SegmentState>();
  #suppressedReplayRoots = new Set<HTMLElement>();
  #avatarKeys = new Map<string, string>();
  #recentFingerprints = new Set<string>();
  #fingerprintOrder: string[] = [];
  #counter = 0;
  #speakerCounter = 0;
  #signals: string[] = [];
  #mutations: string[] = [];
  #scanTimer: ReturnType<typeof setTimeout> | null = null;
  #onEvent: ((event: AdapterUtteranceEvent) => void) | null = null;
  #onStatus: ((status: AdapterStatus) => void) | null = null;

  constructor(document: Document) {
    this.#document = document;
  }

  matchesLocation(url: URL): boolean {
    return url.hostname === "app.zoom.us";
  }

  discover(document: Document): DiscoveryResult {
    const root = document.querySelector(OVERLAY_SELECTOR);
    const labels = controlLabels(document);
    const matchedSignals: string[] = [];
    if (
      root?.classList.contains("live-transcription-subtitle__overlay-container")
    )
      matchedSignals.push("live transcription overlay class");
    if (document.querySelector(WRAPPER_SELECTOR))
      matchedSignals.push("persistent subtitle wrapper");
    if (labels.some((label) => HIDE_CONTROL.test(label)))
      matchedSignals.push("enabled caption control");
    if (labels.some((label) => SHOW_CONTROL.test(label)))
      matchedSignals.push("disabled caption control");
    if (root?.querySelector('[aria-label="Caption Language"]'))
      matchedSignals.push("caption language control");
    if (root?.querySelector(`${ROOT_SELECTOR} ${TEXT_SELECTOR}`))
      matchedSignals.push("caption root and text structure");
    const confidence = Math.min(
      1,
      matchedSignals.reduce((total, signal) => {
        if (signal === "live transcription overlay class") return total + 0.35;
        if (signal.includes("caption control")) return total + 0.3;
        return total + 0.18;
      }, 0),
    );
    return { root, confidence, matchedSignals };
  }

  start(
    onEvent: (event: AdapterUtteranceEvent) => void,
    onStatus: (status: AdapterStatus) => void,
  ): void {
    this.stop();
    this.#onEvent = onEvent;
    this.#onStatus = onStatus;
    this.#rediscover();
    this.#lifecycleObserver = new MutationObserver(() => {
      if (!this.#overlay?.isConnected || !this.#overlay) this.#rediscover();
    });
    if (this.#document.body) {
      this.#lifecycleObserver.observe(this.#document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }
  }

  stop(): void {
    this.#overlayObserver?.disconnect();
    this.#lifecycleObserver?.disconnect();
    this.#overlayObserver = null;
    this.#lifecycleObserver = null;
    if (this.#scanTimer) clearTimeout(this.#scanTimer);
    this.#scanTimer = null;
    for (const state of this.#segments.values()) {
      if (state.idleTimer) clearTimeout(state.idleTimer);
      if (state.removalTimer) clearTimeout(state.removalTimer);
    }
    this.#segments.clear();
    this.#suppressedReplayRoots.clear();
    this.#avatarKeys.clear();
    this.#recentFingerprints.clear();
    this.#fingerprintOrder = [];
    this.#overlay = null;
  }

  dumpDiagnostics(
    options: { redactText?: boolean; redactNames?: boolean } = {},
  ): DiagnosticBundle {
    return {
      adapter: "zoom",
      adapterVersion: extensionVersion,
      platform: this.platform,
      sanitizedUrl: sanitizeUrl(this.#document.location.href),
      matchedSignals: this.#signals,
      subtree: this.#overlay ? sanitizeSubtree(this.#overlay, options) : null,
      recentMutations: [...this.#mutations],
      warning:
        "Caption text and speaker names are sensitive. Avatar URLs are removed; names can be redacted.",
    };
  }

  #rediscover(): void {
    const previousOverlay = this.#overlay;
    const discovery = this.discover(this.#document);
    this.#signals = discovery.matchedSignals;
    if (previousOverlay === discovery.root && discovery.root) {
      this.#scan();
      return;
    }

    this.#overlayObserver?.disconnect();
    this.#overlayObserver = null;
    this.#overlay = discovery.root;
    if (!this.#overlay) {
      for (const root of this.#segments.keys()) this.#scheduleRemoval(root);
      const isOff = controlLabels(this.#document).some((label) =>
        SHOW_CONTROL.test(label),
      );
      this.#publishStatus(isOff ? "off" : "unknown", discovery.confidence);
      return;
    }

    this.#overlayObserver = new MutationObserver((records) => {
      for (const record of records)
        this.#trace(`${record.type}:${record.target.nodeName}`);
      this.#queueScan();
    });
    this.#overlayObserver.observe(this.#overlay, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["class", "style", "aria-hidden", SPEAKER_ATTRIBUTE],
    });
    this.#scan();
  }

  #queueScan(): void {
    if (this.#scanTimer) clearTimeout(this.#scanTimer);
    this.#scanTimer = setTimeout(() => {
      this.#scanTimer = null;
      this.#scan();
    }, MUTATION_SETTLE_MILLISECONDS);
  }

  #extractSegments(): ExtractedSegment[] {
    if (!this.#overlay) return [];
    return Array.from(
      this.#overlay.querySelectorAll<HTMLElement>(ROOT_SELECTOR),
    ).flatMap((root) => {
      const text = normalizedText(root.querySelector(TEXT_SELECTOR));
      if (!text || !isRendered(root)) return [];
      return [
        {
          root,
          speakerKey: this.#speakerKey(root.querySelector(AVATAR_SELECTOR)),
          speaker: zoomDisplayName(root),
          text,
        },
      ];
    });
  }

  #speakerKey(avatar: Element | null): string | null {
    const source = avatar?.getAttribute("src")?.trim();
    if (!source) return null;
    const existing = this.#avatarKeys.get(source);
    if (existing) return existing;
    const created = `avatar-${++this.#speakerCounter}`;
    this.#avatarKeys.set(source, created);
    return created;
  }

  #scan(): void {
    if (!this.#overlay?.isConnected) {
      this.#rediscover();
      return;
    }
    const current = new Set<HTMLElement>();
    for (const extracted of this.#extractSegments()) {
      current.add(extracted.root);
      this.#observeSegment(extracted);
    }
    for (const root of this.#segments.keys()) {
      if (!current.has(root)) this.#scheduleRemoval(root);
    }
    for (const root of this.#suppressedReplayRoots) {
      if (!current.has(root)) this.#suppressedReplayRoots.delete(root);
    }
    this.#publishStatus(current.size > 0 ? "capturing" : "on_empty", 1);
  }

  #observeSegment(extracted: ExtractedSegment): void {
    const existing = this.#segments.get(extracted.root);
    if (existing) {
      if (existing.removalTimer) {
        clearTimeout(existing.removalTimer);
        existing.removalTimer = null;
      }
      if (existing.final) {
        if (existing.visibleText === extracted.text) return;
        this.#continueAfterFinalized(extracted.root, existing, extracted);
        return;
      } else if (
        existing.speakerKey !== extracted.speakerKey ||
        (existing.speaker !== null &&
          extracted.speaker !== null &&
          existing.speaker !== extracted.speaker)
      ) {
        this.#finalize(existing);
        this.#segments.delete(extracted.root);
      } else {
        this.#update(
          extracted.root,
          existing,
          extracted.text,
          extracted.speaker,
        );
        return;
      }
    }

    const replacement = this.#replacementCandidate(extracted);
    if (replacement) {
      const [previousRoot, state] = replacement;
      if (state.removalTimer) clearTimeout(state.removalTimer);
      state.removalTimer = null;
      this.#segments.delete(previousRoot);
      this.#segments.set(extracted.root, state);
      if (state.final) {
        this.#continueAfterFinalized(extracted.root, state, extracted);
      } else {
        this.#update(extracted.root, state, extracted.text, extracted.speaker);
      }
      return;
    }

    const fingerprint = this.#fingerprint(
      extracted.speakerKey ?? extracted.speaker,
      extracted.text,
    );
    if (this.#recentFingerprints.has(fingerprint)) {
      this.#suppressedReplayRoots.add(extracted.root);
      return;
    }
    if (this.#suppressedReplayRoots.has(extracted.root))
      this.#suppressedReplayRoots.delete(extracted.root);

    const created: SegmentState = {
      id: `zoom-${this.#documentIdentity}-${++this.#counter}`,
      revision: 1,
      speakerKey: extracted.speakerKey,
      speaker: extracted.speaker,
      text: extracted.text,
      visibleText: extracted.text,
      activeStart: 0,
      final: false,
      idleTimer: null,
      removalTimer: null,
    };
    this.#segments.set(extracted.root, created);
    this.#emit(created, "upsert");
    this.#resetIdle(created);
    this.#splitIfNeeded(extracted.root, created);
  }

  #replacementCandidate(
    extracted: ExtractedSegment,
  ): [HTMLElement, SegmentState] | null {
    let best: [HTMLElement, SegmentState] | null = null;
    let bestScore = 0;
    for (const entry of this.#segments.entries()) {
      const [root, state] = entry;
      if (
        state.speakerKey !== extracted.speakerKey ||
        (state.speaker !== null &&
          extracted.speaker !== null &&
          state.speaker !== extracted.speaker) ||
        (root.isConnected && isRendered(root))
      ) {
        continue;
      }
      const score = relationScore(state.visibleText, extracted.text);
      if (score >= 8 && score > bestScore) {
        best = entry;
        bestScore = score;
      }
    }
    return best;
  }

  #continueAfterFinalized(
    root: HTMLElement,
    state: SegmentState,
    extracted: ExtractedSegment,
  ): void {
    if (
      state.speakerKey !== extracted.speakerKey ||
      (state.speaker !== null &&
        extracted.speaker !== null &&
        state.speaker !== extracted.speaker)
    ) {
      this.#segments.delete(root);
      this.#observeSegment(extracted);
      return;
    }

    const activeStart = mappedTextBoundary(
      state.visibleText,
      extracted.text,
      state.activeStart,
    );
    const text = extracted.text.slice(activeStart).trim();
    state.visibleText = extracted.text;
    state.activeStart = activeStart;
    if (!text) return;

    const created: SegmentState = {
      id: `zoom-${this.#documentIdentity}-${++this.#counter}`,
      revision: 1,
      speakerKey: state.speakerKey,
      speaker: state.speaker ?? extracted.speaker,
      text,
      visibleText: extracted.text,
      activeStart,
      final: false,
      idleTimer: null,
      removalTimer: null,
    };
    this.#segments.set(root, created);
    this.#emit(created, "upsert");
    this.#resetIdle(created);
    this.#splitIfNeeded(root, created);
  }

  #update(
    root: HTMLElement,
    state: SegmentState,
    text: string,
    speaker: string | null,
  ): void {
    if (state.final) return;
    const resolvedSpeaker = state.speaker ?? speaker;
    const activeStart = mappedTextBoundary(
      state.visibleText,
      text,
      state.activeStart,
    );
    const activeText = text.slice(activeStart).trim();
    state.visibleText = text;
    state.activeStart = activeStart;
    if (!activeText) return;
    if (state.text === activeText && state.speaker === resolvedSpeaker) return;
    state.revision += 1;
    state.text = activeText;
    state.speaker = resolvedSpeaker;
    this.#emit(state, "upsert");
    this.#resetIdle(state);
    this.#splitIfNeeded(root, state);
  }

  #splitIfNeeded(root: HTMLElement, state: SegmentState): void {
    let current = state;
    let splitIndex = chunkSplitIndex(current.text);
    while (splitIndex !== null) {
      const originalText = current.text;
      const prefix = originalText.slice(0, splitIndex).trim();
      const nextStart = contentStart(
        current.visibleText,
        current.activeStart + splitIndex,
      );
      const suffix = current.visibleText.slice(nextStart).trim();
      if (!prefix || !suffix) return;

      if (prefix !== current.text) {
        current.revision += 1;
        current.text = prefix;
        this.#emit(current, "upsert");
      }
      this.#finalize(current);

      current = {
        id: `zoom-${this.#documentIdentity}-${++this.#counter}`,
        revision: 1,
        speakerKey: current.speakerKey,
        speaker: current.speaker,
        text: suffix,
        visibleText: current.visibleText,
        activeStart: nextStart,
        final: false,
        idleTimer: null,
        removalTimer: null,
      };
      this.#segments.set(root, current);
      this.#emit(current, "upsert");
      this.#resetIdle(current);
      splitIndex = chunkSplitIndex(current.text);
    }
  }

  #scheduleRemoval(root: HTMLElement): void {
    const state = this.#segments.get(root);
    if (!state || state.removalTimer) return;
    state.removalTimer = setTimeout(() => {
      state.removalTimer = null;
      if (root.isConnected && this.#overlay?.contains(root) && isRendered(root))
        return;
      this.#finalize(state);
      this.#segments.delete(root);
    }, RECONCILIATION_MILLISECONDS);
  }

  #resetIdle(state: SegmentState): void {
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = setTimeout(() => {
      state.activeStart = state.visibleText.length;
      this.#finalize(state);
    }, IDLE_FINALIZE_MILLISECONDS);
  }

  #finalize(state: SegmentState): void {
    if (state.final) return;
    state.final = true;
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = null;
    this.#rememberFingerprint(state.speakerKey ?? state.speaker, state.text);
    this.#emit(state, "finalize");
  }

  #fingerprint(speakerKey: string | null, text: string): string {
    return `${speakerKey ?? "unknown"}\u0000${text
      .replace(/\s+/g, " ")
      .trim()
      .toLocaleLowerCase()}`;
  }

  #rememberFingerprint(speakerKey: string | null, text: string): void {
    const fingerprint = this.#fingerprint(speakerKey, text);
    if (this.#recentFingerprints.has(fingerprint)) return;
    this.#recentFingerprints.add(fingerprint);
    this.#fingerprintOrder.push(fingerprint);
    while (this.#fingerprintOrder.length > MAX_REPLAY_FINGERPRINTS) {
      const oldest = this.#fingerprintOrder.shift();
      if (oldest) this.#recentFingerprints.delete(oldest);
    }
  }

  #emit(state: SegmentState, type: AdapterUtteranceEvent["type"]): void {
    this.#onEvent?.({
      type,
      utteranceId: state.id,
      revision: state.revision,
      speaker: state.speaker,
      text: state.text,
      observedAt: new Date().toISOString(),
    });
  }

  #publishStatus(
    captionsStatus: AdapterStatus["captionsStatus"],
    confidence: number,
  ): void {
    const segments = [...this.#segments.values()];
    this.#onStatus?.({
      platform: this.platform,
      captionsStatus,
      speakerDetection: segments.some((segment) => segment.speaker !== null)
        ? "available"
        : segments.length > 0 || this.#suppressedReplayRoots.size > 0
          ? "unavailable"
          : "unknown",
      confidence,
      matchedSignals: this.#signals,
    });
  }

  #trace(message: string): void {
    this.#mutations.push(message);
    if (this.#mutations.length > 100) this.#mutations.shift();
  }
}
