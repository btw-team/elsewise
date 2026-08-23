import { sanitizeSubtree, sanitizeUrl } from "../content/diagnostics";
import type {
  AdapterStatus,
  AdapterUtteranceEvent,
  DiagnosticBundle,
  DiscoveryResult,
  PlatformAdapter,
} from "./base";

const extensionVersion = __EXTENSION_VERSION__;

const ROOT_SELECTOR = '[data-tid="closed-caption-renderer-wrapper"]';
const WINDOW_SELECTOR = '[data-tid="closed-caption-v2-window-wrapper"]';
const LIST_SELECTOR = '[data-tid="closed-caption-v2-virtual-list-content"]';
const AUTHOR_SELECTOR = '[data-tid="author"]';
const TEXT_SELECTOR = '[data-tid="closed-caption-text"]';
const RECONCILIATION_MILLISECONDS = 350;
const IDLE_FINALIZE_MILLISECONDS = 60_000;
const UNKNOWN_SPEAKER = /^unknown(?:\s+user)?$/iu;

interface SegmentState {
  id: string;
  revision: number;
  speaker: string | null;
  text: string;
  final: boolean;
  idleTimer: ReturnType<typeof setTimeout> | null;
  removalTimer: ReturnType<typeof setTimeout> | null;
}

interface ExtractedSegment {
  textNode: HTMLElement;
  speaker: string | null;
  text: string;
}

function normalizedText(node: Element | null): string {
  return node?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function comparableText(text: string): string {
  return (text.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).join("");
}

function editDistance(left: string, right: string): number {
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  let current = new Array<number>(right.length + 1);

  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    current[0] = leftIndex;
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const substitutionCost =
        left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
      current[rightIndex] = Math.min(
        current[rightIndex - 1]! + 1,
        previous[rightIndex]! + 1,
        previous[rightIndex - 1]! + substitutionCost,
      );
    }
    [previous, current] = [current, previous];
  }

  return previous[right.length]!;
}

function continuousTextRevision(previous: string, next: string): boolean {
  const left = comparableText(previous);
  const right = comparableText(next);
  if (!left || !right) return false;
  if (left === right) return true;
  const shorter = left.length <= right.length ? left : right;
  const longer = left.length <= right.length ? right : left;
  if (shorter.length / longer.length < 0.8) return false;
  if (longer.startsWith(shorter)) return true;
  return editDistance(shorter, longer) / longer.length <= 0.2;
}

function isPlaceholderSpeaker(speaker: string | null): boolean {
  return speaker === null || UNKNOWN_SPEAKER.test(speaker.trim());
}

function isLateSpeakerResolution(
  existing: SegmentState,
  extracted: ExtractedSegment,
): boolean {
  // Teams may replace its guest placeholder after it has already emitted most
  // of the caption. Keep that correction on the original utterance identity.
  return (
    !existing.final &&
    isPlaceholderSpeaker(existing.speaker) &&
    !isPlaceholderSpeaker(extracted.speaker) &&
    continuousTextRevision(existing.text, extracted.text)
  );
}

function messageFor(textNode: HTMLElement, root: Element): Element | null {
  let candidate = textNode.parentElement;
  while (candidate && candidate !== root) {
    if (
      candidate.querySelectorAll(TEXT_SELECTOR).length === 1 &&
      candidate.querySelector(AUTHOR_SELECTOR)
    ) {
      return candidate;
    }
    candidate = candidate.parentElement;
  }
  return null;
}

function extractSegments(root: Element): ExtractedSegment[] {
  return Array.from(root.querySelectorAll<HTMLElement>(TEXT_SELECTOR)).flatMap(
    (textNode) => {
      const text = normalizedText(textNode);
      const message = messageFor(textNode, root);
      if (!text || !message) return [];
      return [
        {
          textNode,
          speaker:
            normalizedText(message.querySelector(AUTHOR_SELECTOR)) || null,
          text,
        },
      ];
    },
  );
}

export class MicrosoftTeamsAdapter implements PlatformAdapter {
  readonly platform = "microsoft_teams" as const;
  readonly #document: Document;
  readonly #documentIdentity = crypto.randomUUID().slice(0, 8);
  #root: Element | null = null;
  #rootObserver: MutationObserver | null = null;
  #lifecycleObserver: MutationObserver | null = null;
  #segments = new Map<HTMLElement, SegmentState>();
  #counter = 0;
  #signals: string[] = [];
  #mutations: string[] = [];
  #scanQueued = false;
  #onEvent: ((event: AdapterUtteranceEvent) => void) | null = null;
  #onStatus: ((status: AdapterStatus) => void) | null = null;

  constructor(document: Document) {
    this.#document = document;
  }

  matchesLocation(url: URL): boolean {
    return (
      url.hostname === "teams.live.com" ||
      url.hostname === "teams.microsoft.com" ||
      url.hostname.endsWith(".teams.microsoft.com")
    );
  }

  discover(document: Document): DiscoveryResult {
    const root = document.querySelector(ROOT_SELECTOR);
    const matchedSignals: string[] = [];
    if (root) matchedSignals.push("closed-caption renderer data-tid");
    if (root?.getAttribute("aria-label"))
      matchedSignals.push("accessible caption name");
    if (root?.querySelector(WINDOW_SELECTOR))
      matchedSignals.push("caption window data-tid");
    if (root?.querySelector(LIST_SELECTOR))
      matchedSignals.push("virtual list data-tid");
    if (root && extractSegments(root).length > 0)
      matchedSignals.push("author and caption text fields");
    return {
      root,
      confidence: Math.min(1, matchedSignals.length * 0.25),
      matchedSignals,
    };
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
      if (!this.#root?.isConnected || !this.#root) this.#rediscover();
    });
    if (this.#document.body) {
      this.#lifecycleObserver.observe(this.#document.body, {
        childList: true,
        subtree: true,
      });
    }
  }

  stop(): void {
    this.#rootObserver?.disconnect();
    this.#lifecycleObserver?.disconnect();
    this.#rootObserver = null;
    this.#lifecycleObserver = null;
    for (const state of this.#segments.values()) {
      if (state.idleTimer) clearTimeout(state.idleTimer);
      if (state.removalTimer) clearTimeout(state.removalTimer);
    }
    this.#segments.clear();
    this.#root = null;
  }

  dumpDiagnostics(
    options: { redactText?: boolean; redactNames?: boolean } = {},
  ): DiagnosticBundle {
    return {
      adapter: "microsoft-teams",
      adapterVersion: extensionVersion,
      platform: this.platform,
      sanitizedUrl: sanitizeUrl(this.#document.location.href),
      matchedSignals: this.#signals,
      subtree: this.#root ? sanitizeSubtree(this.#root, options) : null,
      recentMutations: [...this.#mutations],
      warning:
        "Caption text and speaker names may be sensitive. Review before sharing.",
    };
  }

  #rediscover(): void {
    const previousRoot = this.#root;
    const discovery = this.discover(this.#document);
    this.#signals = discovery.matchedSignals;
    if (previousRoot === discovery.root && discovery.root) {
      this.#scan();
      return;
    }
    this.#rootObserver?.disconnect();
    this.#rootObserver = null;
    this.#root = discovery.root;
    if (!this.#root) {
      for (const node of this.#segments.keys()) this.#scheduleRemoval(node);
      this.#publishStatus("off", discovery.confidence);
      return;
    }
    this.#rootObserver = new MutationObserver((records) => {
      for (const record of records)
        this.#trace(`${record.type}:${record.target.nodeName}`);
      this.#queueScan();
    });
    this.#rootObserver.observe(this.#root, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    this.#scan();
  }

  #queueScan(): void {
    if (this.#scanQueued) return;
    this.#scanQueued = true;
    queueMicrotask(() => {
      this.#scanQueued = false;
      this.#scan();
    });
  }

  #scan(): void {
    if (!this.#root?.isConnected) {
      this.#rediscover();
      return;
    }
    const current = new Set<HTMLElement>();
    for (const extracted of extractSegments(this.#root)) {
      current.add(extracted.textNode);
      this.#observeSegment(extracted);
    }
    for (const node of this.#segments.keys()) {
      if (!current.has(node)) this.#scheduleRemoval(node);
    }
    this.#publishStatus(current.size > 0 ? "capturing" : "on_empty", 1);
  }

  #observeSegment(extracted: ExtractedSegment): void {
    const existing = this.#segments.get(extracted.textNode);
    if (existing?.removalTimer) {
      clearTimeout(existing.removalTimer);
      existing.removalTimer = null;
    }
    if (existing && existing.speaker !== extracted.speaker) {
      if (isLateSpeakerResolution(existing, extracted)) {
        existing.revision += 1;
        existing.speaker = extracted.speaker;
        existing.text = extracted.text;
        this.#emit(existing, "upsert");
        this.#resetIdle(existing);
        return;
      }
      this.#finalize(existing);
      this.#segments.delete(extracted.textNode);
    }
    const state = this.#segments.get(extracted.textNode);
    if (!state) {
      const created: SegmentState = {
        id: `teams-${this.#documentIdentity}-${++this.#counter}`,
        revision: 1,
        speaker: extracted.speaker,
        text: extracted.text,
        final: false,
        idleTimer: null,
        removalTimer: null,
      };
      this.#segments.set(extracted.textNode, created);
      this.#emit(created, "upsert");
      this.#resetIdle(created);
      return;
    }
    if (state.final || state.text === extracted.text) return;
    state.revision += 1;
    state.text = extracted.text;
    this.#emit(state, "upsert");
    this.#resetIdle(state);
  }

  #scheduleRemoval(node: HTMLElement): void {
    const state = this.#segments.get(node);
    if (!state || state.removalTimer) return;
    state.removalTimer = setTimeout(() => {
      state.removalTimer = null;
      if (node.isConnected && this.#root?.contains(node)) return;
      this.#finalize(state);
      this.#segments.delete(node);
    }, RECONCILIATION_MILLISECONDS);
  }

  #resetIdle(state: SegmentState): void {
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = setTimeout(
      () => this.#finalize(state),
      IDLE_FINALIZE_MILLISECONDS,
    );
  }

  #finalize(state: SegmentState): void {
    if (state.final) return;
    state.final = true;
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = null;
    this.#emit(state, "finalize");
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
    this.#onStatus?.({
      platform: this.platform,
      captionsStatus,
      speakerDetection: this.#segments.size > 0 ? "available" : "unknown",
      confidence,
      matchedSignals: this.#signals,
    });
  }

  #trace(message: string): void {
    this.#mutations.push(message);
    if (this.#mutations.length > 100) this.#mutations.shift();
  }
}
