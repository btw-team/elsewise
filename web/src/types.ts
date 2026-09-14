export interface PairingRequest {
  id: string;
  installation_id: string;
  browser_family: string;
  display_name: string;
  extension_version: string;
  state: string;
  created_at: string;
  expires_at: string;
}

export interface PairedClient {
  id: string;
  installation_id: string;
  browser_family: string;
  display_name: string;
  status: string;
  created_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
}

export interface SessionSummary {
  id: string;
  title: string;
  description: string;
  language: string;
  initial_prompt: string;
  action_preset_id: string | null;
  agent_provider: AgentProviderId;
  agent_model: string | null;
  agent_reasoning_effort: string | null;
  recording_status: "starting" | "running" | "stopping" | "stopped";
  source_status: string;
  self_audio_enabled: boolean;
  remote_audio_enabled: boolean;
  secondary_fallback_enabled: boolean;
  requested_speech_profile: "auto" | "conservative" | "standard" | "best";
  remote_target_key: string | null;
  agent_status: string;
  source_bindings: SessionSourceBinding[];
  allow_workspace_write: boolean;
  allow_network: boolean;
  requested_agent_cwd: string | null;
  resolved_agent_cwd: string | null;
  agent_cwd_fallback: boolean;
  permissions_updated_at: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  stopped_at: string | null;
  version: number;
}

export interface Utterance {
  id: string;
  session_id: string;
  segment_id: string;
  source_epoch_id: string;
  utterance_id: string;
  revision: number;
  speaker: string | null;
  speaker_role: "self" | "remote" | "unknown";
  text: string;
  final: boolean;
  first_session_offset_us: number;
  last_session_offset_us: number;
  first_received_at: string;
  last_received_at: string;
  first_client_seq: number | null;
  last_client_seq: number | null;
  first_audio_sample_position: number | null;
  last_audio_sample_position: number | null;
  finalization_state: "partial" | "live_final" | "durable_final";
  asr_backend: string | null;
  asr_model_id: string | null;
  asr_model_version: string | null;
  transcript_confidence: number | null;
}

export interface Segment {
  id: string;
  session_id: string;
  sequence: number;
  started_at: string;
  stopped_at: string | null;
  stop_reason: string | null;
}

export interface CaptureSource {
  id: string;
  paired_client_id: string | null;
  source_kind: string;
  source_category: "audio" | "captions" | "semantic" | "synthetic";
  source_role: "self" | "remote" | "secondary";
  target_key: string | null;
  platform: string;
  driver_id: string;
  driver_version: string;
  tab_instance_id: string | null;
  capabilities: string[];
  available: boolean;
  connected: boolean;
  health_status: string;
  last_error_code: string | null;
  last_event_at: string | null;
  client_display_name?: string | null;
  browser_family?: string | null;
  tab_ordinal?: number | null;
}

export interface AudioSourceCandidate {
  source_kind:
    | "synthetic_audio"
    | "native_microphone"
    | "native_process_audio"
    | "native_system_audio";
  target_key: string;
  display_name: string;
  available: boolean;
  is_default: boolean;
  active?: boolean;
}

export interface AudioSourceInventory {
  status: "ready" | "unavailable";
  error_code: string | null;
  items: AudioSourceCandidate[];
}

export interface SessionSourceBinding {
  id: string;
  session_id: string;
  segment_id: string | null;
  role: "self" | "remote" | "secondary";
  source_id: string | null;
  requested_mode: "auto" | "explicit" | "disabled";
  effective_mode:
    "native" | "captions" | "synthetic" | "unavailable" | "disabled";
  fallback_priority: number;
  state: string;
  reason: string | null;
  activated_at: string | null;
  stopped_at: string | null;
}

export interface GlobalSnapshot {
  sessions: SessionSummary[];
  sources: CaptureSource[];
  buttons: ButtonDefinition[];
  action_presets: ActionPreset[];
  last_event_id: number;
  pruned_through?: number;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface AgentHistoryPage {
  runs: AgentRun[];
  messages: AgentMessage[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface SessionDetail {
  session: SessionSummary;
  segments: Segment[];
  agent_thread: AgentThread | null;
  utterances: Page<Utterance>;
  agent_history: AgentHistoryPage;
  last_event_id: number;
  pruned_through: number;
}

export interface AgentThread {
  id: string;
  session_id: string;
  provider: string;
  external_thread_id: string | null;
  status: string;
  created_at: string;
  resumed_at: string | null;
  last_turn_at: string | null;
}

export interface AgentRun {
  id: string;
  session_id: string;
  thread_id: string;
  button_id: string | null;
  queue_sequence: number;
  status: string;
  button_snapshot: Record<string, unknown>;
  resolved_prompt: string;
  frozen_context: string;
  context_strategy: string;
  context_start: string | null;
  context_end: string | null;
  session_language: string;
  provider: string;
  model: string | null;
  reasoning_effort: string | null;
  cwd: string;
  permissions_snapshot: Record<string, unknown>;
  external_turn_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_type: string | null;
  error_message: string | null;
}

export interface AgentMessage {
  id: string;
  run_id: string;
  role: string;
  message_type: string;
  text: string;
  sequence: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ButtonDefinition {
  id: string;
  key: string;
  enabled: boolean;
  label: string;
  prompt_template: string;
  context_strategy:
    "since_previous_turn" | "last_minutes" | "last_utterances" | "all";
  context_value: number | null;
  hard_character_cap: number;
  definition_version: number;
  created_at: string;
  updated_at: string;
}

export interface ActionPreset {
  id: string;
  name: string;
  is_default: boolean;
  button_ids: string[];
  created_at: string;
  updated_at: string;
}

export type ContextStrategy = ButtonDefinition["context_strategy"];
export type { SupportedLanguage } from "./i18n/languages";
import type { SupportedLanguage } from "./i18n/languages";
export type AgentProviderId = "codex" | "claude";

export interface GlobalSettings {
  ui_language: SupportedLanguage;
  ui_theme: "dark" | "light";
  default_meeting_language: SupportedLanguage;
  initial_prompts: Record<SupportedLanguage, string>;
  initial_prompt_version: number;
  default_agent_provider: AgentProviderId;
  default_agent_model: string | null;
  default_agent_reasoning_effort: string | null;
  codex_executable: string;
  claude_executable: string;
  google_meet_own_name: string;
  microsoft_teams_own_name: string;
  zoom_own_name: string;
  free_prompt_context_strategy: ContextStrategy;
  free_prompt_context_value: number | null;
  free_prompt_hard_character_cap: number;
  default_allow_workspace_write: boolean;
  default_allow_network: boolean;
  default_self_audio_enabled: boolean;
  default_remote_audio_enabled: boolean;
  default_secondary_fallback_enabled: boolean;
  default_speech_profile: "auto" | "conservative" | "standard" | "best";
  default_remote_target_key: string;
  recovery?: {
    file_name: string;
    source: "backup" | "defaults";
  } | null;
}

export interface AgentHealth {
  provider?: AgentProviderId;
  status: "stopped" | "starting" | "ready" | "unavailable" | "error";
  version: string | null;
  authenticated: boolean | null;
  message: string | null;
}

export interface AgentProviderHealth extends AgentHealth {
  id: AgentProviderId;
  name: string;
  models: AgentModelOption[];
}

export interface AgentModelOption {
  id: string;
  name: string;
  description: string;
  reasoning_efforts: string[];
  default_reasoning_effort: string | null;
}

export interface UiEvent {
  type: "ui.event";
  protocol_version: 2;
  event_id: number;
  event_type: string;
  aggregate_id: string | null;
  created_at: string;
  payload: Record<string, unknown>;
}
