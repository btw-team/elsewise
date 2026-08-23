import type { Platform } from "../protocol/models";

export interface AdapterStatus {
  platform: Platform;
  captionsStatus:
    "unknown" | "off" | "on_empty" | "capturing" | "unavailable" | "error";
  speakerDetection: "unknown" | "available" | "unavailable";
  confidence: number;
  matchedSignals: string[];
}

export interface AdapterUtteranceEvent {
  type: "upsert" | "finalize";
  utteranceId: string;
  revision: number;
  speaker: string | null;
  text: string;
  observedAt: string;
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

export interface DiscoveryResult {
  root: Element | null;
  confidence: number;
  matchedSignals: string[];
}

export interface PlatformAdapter {
  readonly platform: Platform;
  matchesLocation(url: URL): boolean;
  discover(document: Document): DiscoveryResult;
  start(
    onEvent: (event: AdapterUtteranceEvent) => void,
    onStatus: (status: AdapterStatus) => void,
  ): void;
  stop(): void;
  dumpDiagnostics(options?: {
    redactText?: boolean;
    redactNames?: boolean;
  }): DiagnosticBundle;
}
