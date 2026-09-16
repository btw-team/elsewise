import type { Platform } from "../protocol/models";
import type {
  AdapterEvidenceEvent,
  AdapterSnapshot,
  ParticipantSnapshot,
  SemanticCapability,
} from "./base";
import { emptySnapshot } from "./base";

interface ProviderDomConfig {
  activity: string;
  participant: string;
  participantIdAttributes: string[];
}

const CONFIG: Record<Platform, ProviderDomConfig> = {
  google_meet: {
    activity:
      '[data-meeting-code], [data-call-started="true"], [data-elsewise-activity]',
    participant: '[data-participant-id], [data-elsewise-participant-id]',
    participantIdAttributes: ["data-participant-id", "data-elsewise-participant-id"],
  },
  microsoft_teams: {
    activity:
      '[data-tid="calling-screen"], [data-calling-state="connected"], [data-elsewise-activity]',
    participant: '[data-participant-id], [data-elsewise-participant-id]',
    participantIdAttributes: ["data-participant-id", "data-elsewise-participant-id"],
  },
  zoom: {
    activity: '.meeting-app, [data-meeting-id], [data-elsewise-activity]',
    participant: '[data-user-id], [data-participant-id], [data-elsewise-participant-id]',
    participantIdAttributes: [
      "data-user-id",
      "data-participant-id",
      "data-elsewise-participant-id",
    ],
  },
  synthetic: {
    activity: '[data-elsewise-activity], [data-elsewise-captions]',
    participant: '[data-elsewise-participant-id]',
    participantIdAttributes: ["data-elsewise-participant-id"],
  },
};

function booleanAttribute(element: Element, name: string): boolean | null {
  const value = element.getAttribute(name);
  if (value === null) return null;
  return value === "" || value === "true" || value === "1";
}

function participantId(element: Element, config: ProviderDomConfig): string | null {
  for (const attribute of config.participantIdAttributes) {
    const value = element.getAttribute(attribute)?.trim();
    if (value) return value.slice(0, 256);
  }
  return null;
}

function participantLabel(element: Element): string | null {
  const value =
    element.getAttribute("data-display-name") ??
    element.getAttribute("aria-label") ??
    element.querySelector<HTMLElement>("[data-display-name]")?.dataset.displayName ??
    null;
  const normalized = value?.replace(/\s+/g, " ").trim() ?? "";
  return normalized ? normalized.slice(0, 512) : null;
}

function readParticipants(document: Document, config: ProviderDomConfig): ParticipantSnapshot[] {
  const participants = new Map<string, ParticipantSnapshot>();
  for (const element of document.querySelectorAll(config.participant)) {
    const id = participantId(element, config);
    if (!id) continue;
    participants.set(id, {
      id,
      displayLabel: participantLabel(element),
      self: booleanAttribute(element, "data-is-self") === true,
      activeSpeaker: booleanAttribute(element, "data-active-speaker") === true,
      muted: booleanAttribute(element, "data-muted"),
      handRaised: booleanAttribute(element, "data-hand-raised"),
    });
  }
  return [...participants.values()];
}

function semanticEvent(
  platform: Platform,
  capability: SemanticCapability,
  kind: string,
  payload: Record<string, unknown>,
  confidence: number,
): AdapterEvidenceEvent {
  const sourceTimeUs = Math.max(0, Math.round(performance.now() * 1_000));
  return {
    type: "semantic",
    utteranceId: "",
    revision: 0,
    speaker: null,
    text: "",
    capability,
    kind,
    observedAt: new Date().toISOString(),
    sourceTimeUs,
    intervalStartUs: sourceTimeUs,
    intervalEndUs: sourceTimeUs,
    confidence,
    provenance: `${platform}.dom`,
    payload,
  };
}

export class DomSemanticObserver {
  readonly #config: ProviderDomConfig;
  #observer: MutationObserver | null = null;
  #snapshot: AdapterSnapshot;
  #emit: ((event: AdapterEvidenceEvent) => void) | null = null;
  #scanQueued = false;

  constructor(
    readonly platform: Platform,
    readonly document: Document,
  ) {
    this.#config = CONFIG[platform];
    this.#snapshot = this.readSnapshot();
  }

  capabilities(): ReadonlySet<SemanticCapability> {
    const result = new Set<SemanticCapability>();
    if (this.document.querySelector(this.#config.activity)) {
      result.add("activity_lifecycle");
    }
    const participants = this.#snapshot.participants;
    if (participants.length > 0) result.add("participants");
    if (participants.some((item) => item.self)) result.add("self_identity");
    if (participants.some((item) => item.activeSpeaker)) result.add("active_speaker");
    if (participants.some((item) => item.muted !== null)) result.add("mute_state");
    if (participants.some((item) => item.handRaised !== null)) result.add("hand_raise");
    return result;
  }

  snapshot(): AdapterSnapshot {
    return {
      ...this.#snapshot,
      participants: this.#snapshot.participants.map((item) => ({ ...item })),
    };
  }

  start(emit: (event: AdapterEvidenceEvent) => void): void {
    this.stop(false);
    this.#emit = emit;
    this.#snapshot = emptySnapshot(false);
    this.#reconcile();
    if (!this.document.body) return;
    this.#observer = new MutationObserver(() => this.#queueScan());
    this.#observer.observe(this.document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "data-active-speaker",
        "data-display-name",
        "data-hand-raised",
        "data-is-self",
        "data-muted",
        "data-participant-id",
        "data-user-id",
        "data-elsewise-participant-id",
      ],
    });
  }

  stop(emitEnded = true): void {
    this.#observer?.disconnect();
    this.#observer = null;
    if (emitEnded && this.#snapshot.activityDetected) {
      this.#emit?.(
        semanticEvent(this.platform, "activity_lifecycle", "activity.ended", {}, 0.8),
      );
    }
    this.#emit = null;
  }

  readSnapshot(): AdapterSnapshot {
    return {
      ...emptySnapshot(Boolean(this.document.querySelector(this.#config.activity))),
      participants: readParticipants(this.document, this.#config),
    };
  }

  #queueScan(): void {
    if (this.#scanQueued) return;
    this.#scanQueued = true;
    queueMicrotask(() => {
      this.#scanQueued = false;
      this.#reconcile();
    });
  }

  #reconcile(): void {
    const previous = this.#snapshot;
    const next = this.readSnapshot();
    if (!previous.activityDetected && next.activityDetected) {
      this.#emit?.(
        semanticEvent(this.platform, "activity_lifecycle", "activity.started", {}, 0.8),
      );
    } else if (previous.activityDetected && !next.activityDetected) {
      this.#emit?.(
        semanticEvent(this.platform, "activity_lifecycle", "activity.ended", {}, 0.8),
      );
    }

    const oldParticipants = new Map(previous.participants.map((item) => [item.id, item]));
    const newParticipants = new Map(next.participants.map((item) => [item.id, item]));
    for (const participant of next.participants) {
      const old = oldParticipants.get(participant.id);
      if (!old || old.displayLabel !== participant.displayLabel) {
        this.#emitParticipant("participants", "participant.upsert", participant, 0.85);
      }
      if (participant.self && !old?.self) {
        this.#emitParticipant("self_identity", "participant.self", participant, 0.9);
      }
      if (participant.activeSpeaker !== (old?.activeSpeaker ?? false)) {
        this.#emitParticipant(
          "active_speaker",
          participant.activeSpeaker ? "speaker.started" : "speaker.stopped",
          participant,
          0.8,
        );
      }
      if (participant.muted !== null && participant.muted !== old?.muted) {
        this.#emitParticipant(
          "mute_state",
          participant.muted ? "participant.muted" : "participant.unmuted",
          participant,
          0.75,
        );
      }
      if (participant.handRaised !== null && participant.handRaised !== old?.handRaised) {
        this.#emitParticipant(
          "hand_raise",
          participant.handRaised ? "participant.hand_raised" : "participant.hand_lowered",
          participant,
          0.75,
        );
      }
    }
    for (const participant of previous.participants) {
      if (!newParticipants.has(participant.id)) {
        this.#emitParticipant("participants", "participant.left", participant, 0.8);
      }
    }
    this.#snapshot = next;
  }

  #emitParticipant(
    capability: SemanticCapability,
    kind: string,
    participant: ParticipantSnapshot,
    confidence: number,
  ): void {
    this.#emit?.(
      semanticEvent(
        this.platform,
        capability,
        kind,
        {
          participant_id: participant.id,
          display_label: participant.displayLabel,
        },
        confidence,
      ),
    );
  }
}
