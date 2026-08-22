export type Platform = "google_meet" | "microsoft_teams" | "zoom" | "synthetic";

export interface ClientHello {
  type: "client.hello";
  protocol_version: 1;
  role: "extension";
  token: string;
  installation_id: string;
  extension_version: string;
}

export interface SourceStatus {
  type: "source.status";
  protocol_version: 1;
  event_id: string;
  source_id: string;
  tab_id?: number;
  document_id?: string;
  client_seq: number;
  platform: Platform;
  enabled: boolean;
  captions_status:
    "unknown" | "off" | "on_empty" | "capturing" | "unavailable" | "error";
  speaker_detection?: "unknown" | "available" | "unavailable";
  meeting_key?: string;
  meeting_title?: string;
  last_caption_at?: string;
  observed_at: string;
  diagnostic_code?: string;
}

export interface CaptionMessage {
  protocol_version: 1;
  event_id: string;
  source_id: string;
  client_seq: number;
  platform: Platform;
  meeting_key: string;
  utterance_id: string;
  revision: number;
  speaker?: string | null;
  text: string;
  observed_at: string;
}

export interface UtteranceUpsert extends CaptionMessage {
  type: "utterance.upsert";
}

export interface UtteranceFinalize extends CaptionMessage {
  type: "utterance.finalize";
}

export type AckResult =
  | "applied"
  | "duplicate"
  | "stale"
  | "no_active_session"
  | "source_not_bound"
  | "grace_finalize_applied"
  | "rejected";

export interface EventAck {
  type: "event.ack";
  protocol_version: 1;
  event_id: string;
  client_seq: number;
  result: AckResult;
  reason?: string;
}

export interface UiEvent {
  type: "ui.event";
  protocol_version: 1;
  event_id: number;
  event_type:
    | "session.state"
    | "source.status"
    | "utterance.created"
    | "utterance.updated"
    | "utterance.finalized"
    | "agent.queued"
    | "agent.started"
    | "agent.delta"
    | "agent.completed"
    | "agent.failed"
    | "agent.cancelled"
    | "settings.changed"
    | "export.completed"
    | "export.failed"
    | "resync_required";
  aggregate_id?: string | null;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface ProtocolError {
  type: "protocol.error";
  protocol_version: 1;
  event_id?: string;
  client_seq?: number;
  code:
    | "invalid_json"
    | "invalid_message"
    | "unsupported_protocol_version"
    | "unauthorized"
    | "hello_required"
    | "unknown_message_type"
    | "message_too_large"
    | "rate_limited"
    | "source_switch_rejected"
    | "internal_error";
  message: string;
  recoverable: boolean;
  details?: Record<string, unknown>;
}

export interface ProtocolMessageMap {
  "client.hello": ClientHello;
  "source.status": SourceStatus;
  "utterance.upsert": UtteranceUpsert;
  "utterance.finalize": UtteranceFinalize;
  "event.ack": EventAck;
  "ui.event": UiEvent;
  "protocol.error": ProtocolError;
}

export type ProtocolMessageType = keyof ProtocolMessageMap;
export type ProtocolMessage = ProtocolMessageMap[ProtocolMessageType];
