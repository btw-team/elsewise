import { sanitizeSubtree, sanitizeUrl } from "../content/diagnostics";
import { captionEvidence, emptySnapshot } from "./base";
import type {
  AdapterStatus,
  AdapterEvidenceEvent,
  DiagnosticBundle,
  DetectionResult,
  SemanticAdapter,
} from "./base";

const extensionVersion = __EXTENSION_VERSION__;

interface UtteranceState {
  revision: number;
  speaker: string | null;
  text: string;
  final: boolean;
}

export class SyntheticAdapter implements SemanticAdapter {
  readonly platform = "synthetic" as const;
  readonly #document: Document;
  #root: Element | null = null;
  #observer: MutationObserver | null = null;
  #utterances = new Map<string, UtteranceState>();
  #mutations: string[] = [];
  #signals: string[] = [];
  #onEvent: ((event: AdapterEvidenceEvent) => void) | null = null;
  #onStatus: ((status: AdapterStatus) => void) | null = null;

  constructor(document: Document) {
    this.#document = document;
  }

  matchesLocation(url: URL): boolean {
    return (
      url.hostname === "127.0.0.1" && url.searchParams.has("elsewise-synthetic")
    );
  }

  capabilities() {
    return new Set(["captions"] as const);
  }

  snapshot() {
    const snapshot = emptySnapshot(this.#root !== null);
    snapshot.participants = [...new Set([...this.#utterances.values()].map((item) => item.speaker))]
      .filter((name): name is string => name !== null)
      .map((displayLabel) => ({
        id: displayLabel,
        displayLabel,
        self: false,
        activeSpeaker: false,
        muted: null,
        handRaised: null,
      }));
    return snapshot;
  }

  detect(document: Document): DetectionResult {
    const root = document.querySelector("[data-elsewise-captions]");
    const matchedSignals = root
      ? ["explicit synthetic caption root", "structured utterance children"]
      : [];
    return { root, confidence: root ? 1 : 0, matchedSignals };
  }

  start(
    onEvent: (event: AdapterEvidenceEvent) => void,
    onStatus: (status: AdapterStatus) => void,
  ): void {
    this.stop();
    this.#onEvent = onEvent;
    this.#onStatus = onStatus;
    const discovery = this.detect(this.#document);
    this.#root = discovery.root;
    this.#signals = discovery.matchedSignals;
    if (!this.#root) {
      this.#publishStatus("off", 0);
      return;
    }
    this.#scan();
    this.#observer = new MutationObserver((records) => {
      for (const record of records) {
        this.#trace(`${record.type}:${record.target.nodeName}`);
        for (const removed of record.removedNodes)
          this.#finalizeRemoved(removed);
      }
      this.#scan();
    });
    this.#observer.observe(this.#root, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["data-final", "data-speaker", "data-utterance-id"],
    });
    this.#publishStatus(
      this.#utterances.size > 0 ? "capturing" : "on_empty",
      1,
    );
  }

  stop(finalize = false): void {
    this.#observer?.disconnect();
    this.#observer = null;
    if (finalize) {
      for (const [utteranceId, state] of this.#utterances) {
        if (state.final) continue;
        state.final = true;
        this.#onEvent?.(
          captionEvidence(this.platform, "finalize", {
            utteranceId,
            revision: state.revision,
            speaker: state.speaker,
            text: state.text,
          }),
        );
      }
    }
  }

  dumpDiagnostics(
    options: { redactText?: boolean; redactNames?: boolean } = {},
  ): DiagnosticBundle {
    return {
      adapter: "synthetic",
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

  #scan(): void {
    if (!this.#root) return;
    const blocks = this.#root.querySelectorAll<HTMLElement>(
      "[data-utterance-id]",
    );
    for (const block of blocks) this.#observeBlock(block);
    this.#publishStatus(blocks.length > 0 ? "capturing" : "on_empty", 1);
  }

  #observeBlock(block: HTMLElement): void {
    const utteranceId = block.dataset.utteranceId;
    if (!utteranceId) return;
    const speaker = block.dataset.speaker?.trim() || null;
    const textNode = block.querySelector("[data-caption-text]");
    const text = textNode?.textContent?.trim() ?? "";
    if (!text) return;
    const final = block.dataset.final === "true";
    const previous = this.#utterances.get(utteranceId);
    if (
      previous?.speaker === speaker &&
      previous.text === text &&
      previous.final === final
    )
      return;
    const revision = (previous?.revision ?? 0) + 1;
    this.#utterances.set(utteranceId, { revision, speaker, text, final });
    this.#onEvent?.(
      captionEvidence(this.platform, final ? "finalize" : "upsert", {
        utteranceId,
        revision,
        speaker,
        text,
      }),
    );
  }

  #finalizeRemoved(node: Node): void {
    if (!(node instanceof Element)) return;
    const blocks = node.matches("[data-utterance-id]")
      ? [node]
      : Array.from(node.querySelectorAll("[data-utterance-id]"));
    for (const block of blocks) {
      const utteranceId = (block as HTMLElement).dataset.utteranceId;
      const state = utteranceId ? this.#utterances.get(utteranceId) : undefined;
      if (!utteranceId || !state || state.final) continue;
      state.final = true;
      this.#onEvent?.(
        captionEvidence(this.platform, "finalize", {
          utteranceId,
          revision: state.revision,
          speaker: state.speaker,
          text: state.text,
        }),
      );
    }
  }

  #publishStatus(
    captionsStatus: AdapterStatus["captionsStatus"],
    confidence: number,
  ): void {
    this.#onStatus?.({
      platform: this.platform,
      captionsStatus,
      speakerDetection: "available",
      confidence,
      matchedSignals: this.#signals,
    });
  }

  #trace(message: string): void {
    this.#mutations.push(message);
    if (this.#mutations.length > 100) this.#mutations.shift();
  }
}
