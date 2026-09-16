import type { Platform } from "../protocol/models";

export type SemanticCapability =
  | "activity_lifecycle"
  | "participants"
  | "self_identity"
  | "active_speaker"
  | "captions"
  | "mute_state"
  | "hand_raise"
  | "presentation"
  | "chat"
  | "reactions"
  | "recording_state";

export interface AdapterStatus {
  platform: Platform;
  captionsStatus:
    | "unknown"
    | "off"
    | "on_empty"
    | "capturing"
    | "unavailable"
    | "error";
  speakerDetection: "unknown" | "available" | "unavailable";
  confidence: number;
  matchedSignals: string[];
  capabilities?: Partial<Record<SemanticCapability, "available" | "unavailable" | "unknown">>;
}

export interface AdapterEvidenceEvent {
  type: "upsert" | "finalize" | "semantic";
  utteranceId: string;
  revision: number;
  speaker: string | null;
  text: string;
  capability: SemanticCapability;
  kind: string;
  observedAt: string;
  sourceTimeUs: number;
  intervalStartUs: number;
  intervalEndUs: number;
  confidence: number;
  provenance: string;
  payload: Record<string, unknown>;
}

export interface ParticipantSnapshot {
  id: string;
  displayLabel: string | null;
  self: boolean;
  activeSpeaker: boolean;
  muted: boolean | null;
  handRaised: boolean | null;
}

export interface AdapterSnapshot {
  activityDetected: boolean;
  participants: ParticipantSnapshot[];
  presentationActive: boolean | null;
  recordingActive: boolean | null;
}

export interface DiagnosticBundle {
  adapter: string;
  adapterVersion: string;
  platform: Platform;
  sanitizedUrl: string;
  matchedSignals: string[];
  subtree: string | null;
  recentMutations: string[];
  warning: string;
}

export interface DetectionResult {
  root: Element | null;
  confidence: number;
  matchedSignals: string[];
}

export interface SemanticAdapter {
  readonly platform: Platform;
  matchesLocation(url: URL): boolean;
  detect(document: Document): DetectionResult;
  capabilities(): ReadonlySet<SemanticCapability>;
  snapshot(): AdapterSnapshot;
  start(
    onEvent: (event: AdapterEvidenceEvent) => void,
    onStatus: (status: AdapterStatus) => void,
  ): void;
  stop(finalize?: boolean): void;
  dumpDiagnostics(options?: {
    redactText?: boolean;
    redactNames?: boolean;
  }): DiagnosticBundle;
}

export function captionEvidence(
  platform: Platform,
  type: "upsert" | "finalize",
  payload: {
    utteranceId: string;
    revision: number;
    speaker: string | null;
    text: string;
  },
): AdapterEvidenceEvent {
  const sourceTimeUs = Math.max(0, Math.round(performance.now() * 1_000));
  return {
    type,
    utteranceId: payload.utteranceId,
    revision: payload.revision,
    speaker: payload.speaker,
    text: payload.text,
    capability: "captions",
    kind: type === "finalize" ? "caption.final" : "caption.partial",
    observedAt: new Date().toISOString(),
    sourceTimeUs,
    intervalStartUs: sourceTimeUs,
    intervalEndUs: sourceTimeUs,
    confidence: 0.95,
    provenance: `${platform}.dom`,
    payload: {
      utterance_id: payload.utteranceId,
      revision: payload.revision,
      speaker: payload.speaker,
      text: payload.text,
    },
  };
}

export function emptySnapshot(activityDetected: boolean): AdapterSnapshot {
  return {
    activityDetected,
    participants: [],
    presentationActive: null,
    recordingActive: null,
  };
}
