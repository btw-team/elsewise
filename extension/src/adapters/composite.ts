import type {
  AdapterEvidenceEvent,
  AdapterSnapshot,
  AdapterStatus,
  DetectionResult,
  DiagnosticBundle,
  SemanticAdapter,
  SemanticCapability,
} from "./base";
import { DomSemanticObserver } from "./dom-semantics";

export class CompositeSemanticAdapter implements SemanticAdapter {
  readonly platform;
  readonly #semantics;

  constructor(readonly captions: SemanticAdapter, document: Document) {
    this.platform = captions.platform;
    this.#semantics = new DomSemanticObserver(this.platform, document);
  }

  matchesLocation(url: URL): boolean {
    return this.captions.matchesLocation(url);
  }

  detect(document: Document): DetectionResult {
    return this.captions.detect(document);
  }

  capabilities(): ReadonlySet<SemanticCapability> {
    return new Set([...this.captions.capabilities(), ...this.#semantics.capabilities()]);
  }

  snapshot(): AdapterSnapshot {
    const captionSnapshot = this.captions.snapshot();
    const semanticSnapshot = this.#semantics.snapshot();
    return {
      ...semanticSnapshot,
      activityDetected:
        semanticSnapshot.activityDetected || captionSnapshot.activityDetected,
      participants:
        semanticSnapshot.participants.length > 0
          ? semanticSnapshot.participants
          : captionSnapshot.participants,
    };
  }

  start(
    emit: (event: AdapterEvidenceEvent) => void,
    status: (status: AdapterStatus) => void,
  ): void {
    this.captions.start(emit, (next) => {
      const available = this.capabilities();
      const capabilityStatus = Object.fromEntries(
        (
          [
            "activity_lifecycle",
            "participants",
            "self_identity",
            "active_speaker",
            "captions",
            "mute_state",
            "hand_raise",
            "presentation",
            "chat",
            "reactions",
            "recording_state",
          ] satisfies SemanticCapability[]
        ).map((capability) => [
          capability,
          available.has(capability) ? "available" : "unavailable",
        ]),
      ) as AdapterStatus["capabilities"];
      status({ ...next, capabilities: capabilityStatus });
    });
    this.#semantics.start(emit);
  }

  stop(finalize = false): void {
    this.#semantics.stop(finalize);
    this.captions.stop(finalize);
  }

  dumpDiagnostics(options?: {
    redactText?: boolean;
    redactNames?: boolean;
  }): DiagnosticBundle {
    return this.captions.dumpDiagnostics(options);
  }
}
