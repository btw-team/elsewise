export interface PairingSettings {
  token: string;
  masked_token: string;
  created_at: string;
  generation: number;
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
  recording_status: "idle" | "running" | "stopped";
  capture_status: string;
  agent_status: string;
  enabled_source_id: string | null;
  active_source_id: string | null;
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
  source_id: string;
  utterance_id: string;
  revision: number;
  speaker: string | null;
  speaker_role: "self" | "other" | "unknown";
  text: string;
  final: boolean;
  first_observed_at: string;
  last_observed_at: string;
  first_client_seq: number;
  last_client_seq: number;
}

export interface Segment {
  id: string;
  session_id: string;
  sequence: number;
  source_id: string | null;
  started_at: string;
  stopped_at: string | null;
  stop_reason: string | null;
}

export interface CaptureSource {
  source_id: string;
  platform: string;
  meeting_key: string | null;
  meeting_title: string | null;
  enabled: boolean;
  connected: boolean;
  captions_status: string;
  speaker_detection: string | null;
  last_event_at: string | null;
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
  protocol_version: 1;
  event_id: number;
  event_type: string;
  aggregate_id: string | null;
  created_at: string;
  payload: Record<string, unknown>;
}
