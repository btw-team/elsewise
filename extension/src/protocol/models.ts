export const PROTOCOL_VERSION = 3 as const;
export type Platform = "google_meet" | "microsoft_teams" | "zoom" | "synthetic";
export type BrowserFamily = "chrome" | "firefox" | "safari";

export interface ClientHello { type: "client.hello"; protocol_version: 3; role: "extension"; credential: string; installation_id: string; extension_version: string; capabilities: string[] }
export interface PairingRequest { type: "pairing.request"; protocol_version: 3; nonce: string; installation_id: string; browser_family: BrowserFamily; display_name: string; extension_version: string }
export interface PairingCancel { type: "pairing.cancel"; protocol_version: 3 }
export interface PairingPending { type: "pairing.pending"; protocol_version: 3; request_id: string; expires_at: string }
export interface PairingApproved { type: "pairing.approved"; protocol_version: 3; request_id: string; client_id: string; credential: string }
export interface PairingDenied { type: "pairing.denied"; protocol_version: 3; request_id: string }
export interface PairingExpired { type: "pairing.expired"; protocol_version: 3; request_id: string }
export interface PairingCancelled { type: "pairing.cancelled"; protocol_version: 3; request_id: string }
export interface PairingError { type: "pairing.error"; protocol_version: 3; code: string }
export interface ServerHello { type: "server.hello"; protocol_version: 3; capabilities: string[]; heartbeat_interval_seconds: number; session: Record<string, unknown> | null }
export interface Heartbeat { type: "heartbeat"; protocol_version: 3 }
export interface HeartbeatAck { type: "heartbeat.ack"; protocol_version: 3; session: Record<string, unknown> | null }

export interface SourceDiscovered {
  type: "source.discovered";
  protocol_version: 3;
  event_id: string;
  client_seq: number;
  tab_instance_id: string;
  producer_epoch_id: string;
  platform: Platform;
  activity_key?: string;
  driver_id: string;
  driver_version: string;
  capabilities: string[];
  health_status: "available" | "waiting" | "degraded" | "unavailable" | "failed";
  error_code?: string;
  observed_at: string;
}

export interface SourceHealth {
  type: "source.health";
  protocol_version: 3;
  event_id: string;
  client_seq: number;
  source_id: string;
  source_epoch_id?: string;
  health_status: "available" | "waiting" | "degraded" | "unavailable" | "failed";
  error_code?: string;
  dropped_event_count: number;
  observed_at: string;
}

export interface EvidenceEmit {
  type: "evidence.emit";
  protocol_version: 3;
  event_id: string;
  source_id: string;
  source_epoch_id: string;
  client_seq: number;
  capability: string;
  kind: string;
  interval_start_us: number;
  interval_end_us: number;
  source_time_us: number;
  timing_uncertainty_us: number;
  provenance: string;
  confidence: number;
  payload: Record<string, unknown>;
}

export type BufferedEvidence = SourceDiscovered | SourceHealth | EvidenceEmit;

export interface EventAck {
  type: "event.ack";
  protocol_version: 3;
  event_id: string;
  client_seq: number;
  result: "applied" | "duplicate" | "stale" | "no_active_session" | "source_not_bound" | "rejected";
  reason?: string;
  details?: { source_id?: string; source_epoch_id?: string | null };
}

export interface SourceCommand { type: "source.start" | "source.stop"; protocol_version: 3; command_id: string; source_id: string; source_epoch_id: string; tab_instance_id: string; session_id: string; segment_id: string; deadline_ms: number }
export interface SourceCommandAck { type: "source.command_ack"; protocol_version: 3; command_id: string; source_id: string; source_epoch_id: string; result: "started" | "finalized" | "failed"; error_code?: string }
export interface ProtocolError { type: "protocol.error"; protocol_version: 3; event_id?: string; client_seq?: number; code: string; message: string; recoverable: boolean; details?: Record<string, unknown> }
export interface UiEvent { type: "ui.event"; protocol_version: 3; event_id: number; event_type: string; aggregate_id?: string | null; created_at: string; payload: Record<string, unknown> }

export interface ProtocolMessageMap {
  "pairing.request": PairingRequest;
  "pairing.cancel": PairingCancel;
  "pairing.pending": PairingPending;
  "pairing.approved": PairingApproved;
  "pairing.denied": PairingDenied;
  "pairing.expired": PairingExpired;
  "pairing.cancelled": PairingCancelled;
  "pairing.error": PairingError;
  "client.hello": ClientHello;
  "server.hello": ServerHello;
  heartbeat: Heartbeat;
  "heartbeat.ack": HeartbeatAck;
  "source.discovered": SourceDiscovered;
  "source.health": SourceHealth;
  "evidence.emit": EvidenceEmit;
  "event.ack": EventAck;
  "source.start": SourceCommand;
  "source.stop": SourceCommand;
  "source.command_ack": SourceCommandAck;
  "protocol.error": ProtocolError;
  "ui.event": UiEvent;
}

export type ProtocolMessageType = keyof ProtocolMessageMap;
export type ProtocolMessage = ProtocolMessageMap[ProtocolMessageType];
