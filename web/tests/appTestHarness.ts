import { afterEach, beforeEach, vi } from "vitest";

import type {
  AgentMessage,
  AgentRun,
  AgentThread,
  GlobalSettings,
  GlobalSnapshot,
  Segment,
  Utterance,
} from "../src/types";

export interface TestSnapshot extends GlobalSnapshot {
  utterances: Utterance[];
  utterances_truncated?: boolean;
  segments: Segment[];
  agent_threads: AgentThread[];
  agent_runs: AgentRun[];
  agent_messages: AgentMessage[];
}

export const snapshot: TestSnapshot = {
  sessions: [
    {
      id: "session-1",
      title: "Product planning",
      description: "Weekly planning call",
      language: "ru",
      initial_prompt: "RU prompt",
      action_preset_id: "preset-default",
      agent_provider: "codex",
      agent_model: "gpt-5.6-sol",
      agent_reasoning_effort: "low",
      recording_status: "running",
      source_status: "capturing",
      self_audio_enabled: true,
      remote_audio_enabled: true,
      secondary_fallback_enabled: true,
      requested_speech_profile: "auto",
      remote_target_key: null,
      agent_status: "ready",
      source_bindings: [
        {
          id: "binding-1",
          session_id: "session-1",
          segment_id: "segment-1",
          role: "secondary",
          source_id: "source-1",
          requested_mode: "explicit",
          effective_mode: "captions",
          fallback_priority: 0,
          state: "active",
          reason: null,
          activated_at: "2026-08-13T10:00:00Z",
          stopped_at: null,
        },
      ],
      allow_workspace_write: false,
      allow_network: false,
      requested_agent_cwd: null,
      resolved_agent_cwd: "/tmp/elsewise",
      agent_cwd_fallback: true,
      permissions_updated_at: null,
      created_at: "2026-08-13T10:00:00Z",
      updated_at: "2026-08-13T10:00:00Z",
      started_at: "2026-08-13T10:00:00Z",
      stopped_at: null,
      version: 1,
    },
  ],
  utterances: [
    {
      id: "utterance-1",
      session_id: "session-1",
      segment_id: "segment-1",
      source_epoch_id: "epoch-1",
      utterance_id: "caption-1",
      revision: 2,
      speaker: "Speaker A",
      speaker_role: "self",
      text: '<img src=x onerror="alert(1)"> Safe transcript',
      final: false,
      first_session_offset_us: 60_000_000,
      last_session_offset_us: 62_000_000,
      first_received_at: "2026-08-13T10:01:00Z",
      last_received_at: "2026-08-13T10:01:02Z",
      first_client_seq: 1,
      last_client_seq: 2,
      first_audio_sample_position: null,
      last_audio_sample_position: null,
      finalization_state: "partial",
      asr_backend: null,
      asr_model_id: null,
      asr_model_version: null,
      transcript_confidence: null,
    },
  ],
  segments: [
    {
      id: "segment-1",
      session_id: "session-1",
      sequence: 1,
      started_at: "2026-08-13T10:00:00Z",
      stopped_at: null,
      stop_reason: null,
    },
  ],
  sources: [
    {
      id: "source-1",
      paired_client_id: "client-1",
      source_kind: "browser_captions",
      source_category: "captions",
      source_role: "secondary",
      target_key: null,
      platform: "google_meet",
      driver_id: "google_meet_captions",
      driver_version: "1.0.0",
      tab_instance_id: "tab-1",
      capabilities: ["captions"],
      available: true,
      connected: true,
      health_status: "capturing",
      last_error_code: null,
      last_event_at: "2026-08-13T10:01:02Z",
    },
  ],
  agent_threads: [
    {
      id: "thread-1",
      session_id: "session-1",
      provider: "codex",
      external_thread_id: "external-1",
      status: "ready",
      created_at: "2026-08-13T10:00:00Z",
      resumed_at: null,
      last_turn_at: null,
    },
  ],
  agent_runs: [
    {
      id: "run-1",
      session_id: "session-1",
      thread_id: "thread-1",
      button_id: "button-1",
      queue_sequence: 2,
      status: "streaming",
      button_snapshot: { label: "Summary" },
      resolved_prompt: "Frozen request",
      frozen_context: "Transcript",
      context_strategy: "all",
      context_start: "utterance-1",
      context_end: "utterance-1",
      session_language: "ru",
      provider: "codex",
      model: null,
      reasoning_effort: null,
      cwd: "/tmp/elsewise",
      permissions_snapshot: {},
      external_turn_id: "turn-1",
      created_at: "2026-08-13T10:02:00Z",
      started_at: "2026-08-13T10:02:00Z",
      completed_at: null,
      error_type: null,
      error_message: null,
    },
  ],
  agent_messages: [
    {
      id: "message-1",
      run_id: "run-1",
      role: "assistant",
      message_type: "answer",
      text: "<script>alert(1)</script> Streaming answer",
      sequence: 1,
      status: "streaming",
      created_at: "2026-08-13T10:02:00Z",
      updated_at: "2026-08-13T10:02:01Z",
    },
  ],
  buttons: [
    {
      id: "button-1",
      key: "summary",
      enabled: true,
      label: "Summary",
      prompt_template: "Summarize",
      context_strategy: "all",
      context_value: 5,
      hard_character_cap: 50_000,
      definition_version: 1,
      created_at: "2026-08-13T10:00:00Z",
      updated_at: "2026-08-13T10:00:00Z",
    },
    {
      id: "button-2",
      key: "risks",
      enabled: true,
      label: "Risks",
      prompt_template: "Find the most important risks in this discussion.",
      context_strategy: "since_previous_turn",
      context_value: null,
      hard_character_cap: 50_000,
      definition_version: 1,
      created_at: "2026-08-13T10:00:01Z",
      updated_at: "2026-08-13T10:00:01Z",
    },
  ],
  action_presets: [
    {
      id: "preset-default",
      name: "Default",
      is_default: true,
      button_ids: ["button-1"],
      created_at: "2026-08-13T10:00:00Z",
      updated_at: "2026-08-13T10:00:00Z",
    },
    {
      id: "preset-release",
      name: "Release",
      is_default: false,
      button_ids: ["button-2"],
      created_at: "2026-08-13T10:00:01Z",
      updated_at: "2026-08-13T10:00:01Z",
    },
  ],
  last_event_id: 4,
};

function globalSnapshot(value: TestSnapshot) {
  return {
    sessions: value.sessions,
    sources: value.sources,
    buttons: value.buttons,
    action_presets: value.action_presets,
    last_event_id: value.last_event_id,
    pruned_through: value.pruned_through ?? 0,
  };
}

function sessionDetail(value: TestSnapshot, sessionId: string) {
  const session = value.sessions.find((item) => item.id === sessionId);
  if (!session) throw new Error(`Unknown session fixture: ${sessionId}`);
  const runs = value.agent_runs.filter((run) => run.session_id === sessionId);
  const runIds = new Set(runs.map((run) => run.id));
  return {
    session,
    segments: value.segments.filter(
      (segment) => segment.session_id === sessionId,
    ),
    agent_thread:
      value.agent_threads.find((thread) => thread.session_id === sessionId) ??
      null,
    utterances: {
      items: value.utterances.filter((item) => item.session_id === sessionId),
      next_cursor: value.utterances_truncated ? "older-utterances" : null,
      has_more: Boolean(value.utterances_truncated),
    },
    agent_history: {
      runs,
      messages: value.agent_messages.filter((message) =>
        runIds.has(message.run_id),
      ),
      next_cursor: null,
      has_more: false,
    },
    last_event_id: value.last_event_id,
    pruned_through: value.pruned_through ?? 0,
  };
}

export function apiPayload(path: string, value: TestSnapshot): unknown {
  if (path.includes("/api/snapshot")) return globalSnapshot(value);
  const detail = path.match(/\/api\/sessions\/([^/]+)\/detail/);
  if (detail?.[1]) return sessionDetail(value, detail[1]);
  return value;
}

export const globalSettings: GlobalSettings = {
  ui_language: "en",
  ui_theme: "dark",
  default_meeting_language: "ru",
  initial_prompts: {
    ru: "RU prompt",
    en: "EN prompt",
    fr: "FR prompt",
    es: "ES prompt",
    de: "DE prompt",
    "pt-BR": "PT-BR prompt",
  },
  initial_prompt_version: 1,
  default_agent_provider: "codex",
  default_agent_model: "gpt-5.6-sol",
  default_agent_reasoning_effort: "low",
  codex_executable: "codex",
  claude_executable: "claude",
  google_meet_own_name: "Speaker A",
  microsoft_teams_own_name: "",
  zoom_own_name: "",
  free_prompt_context_strategy: "since_previous_turn",
  free_prompt_context_value: 5,
  free_prompt_hard_character_cap: 50_000,
  default_allow_workspace_write: false,
  default_allow_network: false,
  default_self_audio_enabled: true,
  default_remote_audio_enabled: true,
  default_secondary_fallback_enabled: true,
  default_speech_profile: "auto",
  default_remote_target_key: "",
};

export const providerHealth = {
  providers: [
    {
      id: "codex",
      name: "Codex",
      status: "ready",
      version: "test",
      authenticated: true,
      message: null,
      models: [
        {
          id: "gpt-5.6-sol",
          name: "GPT-5.6 Sol",
          description: "",
          reasoning_efforts: ["low", "medium", "high"],
          default_reasoning_effort: "low",
        },
      ],
    },
    {
      id: "claude",
      name: "Claude Code",
      status: "unavailable",
      version: null,
      authenticated: false,
      message: "Claude Code CLI is unavailable.",
      models: [],
    },
  ],
};

export class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  close(): void {}
  receive(event: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

export function installAppTestHarness(): void {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    globalSettings.ui_language = "en";
    globalSettings.ui_theme = "dark";
    localStorage.clear();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const payload = path.endsWith("/export")
          ? {
              directory: "/safe/exports/session-1",
              captions_path: "/safe/exports/session-1/captions.md",
              agent_path: "/safe/exports/session-1/agent.md",
            }
          : path.endsWith("/api/pairing/requests") ||
              path.endsWith("/api/paired-clients")
            ? []
            : path.endsWith("/api/agent/providers")
              ? providerHealth
              : path.endsWith("/api/settings")
                ? globalSettings
                : apiPayload(path, snapshot);
        return { ok: true, status: 200, json: async () => payload };
      }) as unknown as typeof fetch,
    );
  });

  afterEach(() => vi.unstubAllGlobals());
}
