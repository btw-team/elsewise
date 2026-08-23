import { sanitizeSubtree, sanitizeUrl } from "../content/diagnostics";
import type {
  AdapterStatus,
  AdapterUtteranceEvent,
  DiagnosticBundle,
  DiscoveryResult,
  PlatformAdapter,
} from "./base";

const extensionVersion = __EXTENSION_VERSION__;

const REGION_SELECTOR = [
  '[role="region"][aria-label="Captions"]',
  '[role="region"][aria-label="Субтитры"]',
  '[role="region"][aria-label="Untertitel"]',
].join(",");
const ON_CONTROL =
  /turn off captions|выключить субтитры|untertitel deaktivieren/i;
const OFF_CONTROL = /turn on captions|включить субтитры|untertitel aktivieren/i;
const RECONCILIATION_MILLISECONDS = 350;
const IDLE_FINALIZE_MILLISECONDS = 60_000;

interface BlockState {
  id: string;
  revision: number;
  speaker: string | null;
  text: string;
  final: boolean;
  idleTimer: ReturnType<typeof setTimeout> | null;
  removalTimer: ReturnType<typeof setTimeout> | null;
}

interface ExtractedBlock {
  block: HTMLElement;
  speaker: string | null;
  text: string;
}

function normalizedText(node: Element | null): string {
  return node?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function controlLabels(document: Document): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[aria-label]"))
    .map((element) => element.getAttribute("aria-label") ?? "")
    .filter((label) => ON_CONTROL.test(label) || OFF_CONTROL.test(label));
}

function captionTextElement(block: HTMLElement): Element | null {
  const known = block.querySelector(".ygicle, [data-caption-text]");
  if (known && normalizedText(known)) return known;
  const candidates = Array.from(block.querySelectorAll("div")).filter(
    (element) => {
      const text = normalizedText(element);
      return (
        text.length > 0 &&
        !element.querySelector("button, [role=button]") &&
        !/jump to bottom|перейти вниз/i.test(text)
      );
    },
  );
  return candidates.at(-1) ?? null;
}

function speakerElement(
  block: HTMLElement,
  textElement: Element,
): Element | null {
  const known = block.querySelector(".KcIKyf span, [data-speaker-label]");
  if (known && known !== textElement) return known;
  return (
    Array.from(block.querySelectorAll("span")).find(
      (element) =>
        element !== textElement &&
        !textElement.contains(element) &&
        normalizedText(element),
    ) ?? null
  );
}

function extractBlocks(root: Element): ExtractedBlock[] {
  const blocks: ExtractedBlock[] = [];
  for (const child of Array.from(root.children)) {
    if (!(child instanceof HTMLElement)) continue;
    const textElement = captionTextElement(child);
    if (!textElement) continue;
    const text = normalizedText(textElement);
    if (!text) continue;
    const speakerNode = speakerElement(child, textElement);
    const hasShapeSignal =
      Boolean(speakerNode) ||
      Boolean(child.querySelector("img")) ||
      child.classList.contains("nMcdL") ||
      child.hasAttribute("data-caption-block");
    if (!hasShapeSignal) continue;
    blocks.push({
      block: child,
      speaker: normalizedText(speakerNode) || null,
      text,
    });
  }
  return blocks;
}

export class GoogleMeetAdapter implements PlatformAdapter {
  readonly platform = "google_meet" as const;
  readonly #document: Document;
  readonly #documentIdentity = crypto.randomUUID().slice(0, 8);
  #root: Element | null = null;
  #rootObserver: MutationObserver | null = null;
  #lifecycleObserver: MutationObserver | null = null;
  #blocks = new Map<HTMLElement, BlockState>();
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
    return url.hostname === "meet.google.com";
  }

  discover(document: Document): DiscoveryResult {
    const root = document.querySelector(REGION_SELECTOR);
    const labels = controlLabels(document);
    const matchedSignals: string[] = [];
    if (root?.getAttribute("role") === "region")
      matchedSignals.push("caption region role");
    if (root?.getAttribute("aria-label"))
      matchedSignals.push("localized accessible name");
    if (labels.some((label) => ON_CONTROL.test(label)))
      matchedSignals.push("enabled caption control");
    if (root && extractBlocks(root).length > 0)
      matchedSignals.push("speaker/text block structure");
    const confidence = Math.min(1, matchedSignals.length * 0.27);
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
      if (!this.#root?.isConnected) this.#rediscover();
      else if (!this.#root) this.#rediscover();
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
    for (const state of this.#blocks.values()) {
      if (state.idleTimer) clearTimeout(state.idleTimer);
      if (state.removalTimer) clearTimeout(state.removalTimer);
    }
    this.#blocks.clear();
    this.#root = null;
  }

  dumpDiagnostics(
    options: { redactText?: boolean; redactNames?: boolean } = {},
  ): DiagnosticBundle {
    return {
      adapter: "google-meet",
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
      for (const block of this.#blocks.keys()) this.#scheduleRemoval(block);
      const isOff = controlLabels(this.#document).some((label) =>
        OFF_CONTROL.test(label),
      );
      this.#publishStatus(isOff ? "off" : "unknown", discovery.confidence);
      return;
    }
    this.#rootObserver = new MutationObserver((records) => {
      for (const record of records) {
        this.#trace(`${record.type}:${record.target.nodeName}`);
      }
      this.#queueScan();
    });
    this.#rootObserver.observe(this.#root, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["aria-label", "class"],
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
    const currentBlocks = new Set<HTMLElement>();
    for (const extracted of extractBlocks(this.#root)) {
      currentBlocks.add(extracted.block);
      this.#observeBlock(extracted);
    }
    for (const block of this.#blocks.keys()) {
      if (!currentBlocks.has(block)) this.#scheduleRemoval(block);
    }
    this.#publishStatus(currentBlocks.size > 0 ? "capturing" : "on_empty", 1);
  }

  #observeBlock(extracted: ExtractedBlock): void {
    const existing = this.#blocks.get(extracted.block);
    if (existing?.removalTimer) {
      clearTimeout(existing.removalTimer);
      existing.removalTimer = null;
    }
    if (existing && existing.speaker !== extracted.speaker) {
      this.#finalize(existing);
      this.#blocks.delete(extracted.block);
    }
    const state = this.#blocks.get(extracted.block);
    if (!state) {
      const created: BlockState = {
        id: `meet-${this.#documentIdentity}-${++this.#counter}`,
        revision: 1,
        speaker: extracted.speaker,
        text: extracted.text,
        final: false,
        idleTimer: null,
        removalTimer: null,
      };
      this.#blocks.set(extracted.block, created);
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

  #scheduleRemoval(block: HTMLElement): void {
    const state = this.#blocks.get(block);
    if (!state || state.removalTimer) return;
    state.removalTimer = setTimeout(() => {
      state.removalTimer = null;
      if (block.isConnected && this.#root?.contains(block)) return;
      this.#finalize(state);
      this.#blocks.delete(block);
    }, RECONCILIATION_MILLISECONDS);
  }

  #resetIdle(state: BlockState): void {
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = setTimeout(
      () => this.#finalize(state),
      IDLE_FINALIZE_MILLISECONDS,
    );
  }

  #finalize(state: BlockState): void {
    if (state.final) return;
    state.final = true;
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = null;
    this.#emit(state, "finalize");
  }

  #emit(state: BlockState, type: AdapterUtteranceEvent["type"]): void {
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
      speakerDetection: this.#blocks.size > 0 ? "available" : "unknown",
      confidence,
      matchedSignals: this.#signals,
    });
  }

  #trace(message: string): void {
    this.#mutations.push(message);
    if (this.#mutations.length > 100) this.#mutations.shift();
  }
}
