import type {
  ActionPreset,
  AgentProviderHealth,
  AgentRun,
  ButtonDefinition,
  GlobalSettings,
  PairingSettings,
  SessionSummary,
  GlobalSnapshot,
  SessionDetail,
  Page,
  AgentHistoryPage,
  Utterance,
} from "../types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "content-type": "application/json",
      "x-elsewise-request": "web-ui",
      ...options.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: { code?: string; message?: string };
      detail?: string;
    };
    throw new ApiError(
      response.status,
      payload.error?.code ?? payload.detail ?? "request_failed",
      payload.error?.message ?? response.statusText,
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const api = {
  snapshot: () => request<GlobalSnapshot>("/api/snapshot"),
  createSession: (body: {
    title: string;
    description: string;
    language: string;
    initial_prompt: string | null;
    action_preset_id: string | null;
    agent_provider: SessionSummary["agent_provider"];
    agent_model: string | null;
    agent_reasoning_effort: string | null;
    requested_agent_cwd: string | null;
    create_agent_cwd?: boolean;
    allow_workspace_write: boolean;
    allow_network: boolean;
  }) =>
    request<SessionSummary>("/api/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  transition: (sessionId: string, action: "start" | "stop") =>
    request<SessionSummary>(`/api/sessions/${sessionId}/${action}`, {
      method: "POST",
    }),
  deleteSession: (sessionId: string) =>
    request<void>(
      `/api/sessions/${sessionId}?confirm=${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
      },
    ),
  exportSession: (sessionId: string) =>
    request<{ directory: string; captions_path: string; agent_path: string }>(
      `/api/sessions/${sessionId}/export`,
      { method: "POST" },
    ),
  sessionDetail: (sessionId: string) =>
    request<SessionDetail>(`/api/sessions/${sessionId}/detail`),
  utterances: (sessionId: string, cursor?: string, limit = 500) => {
    const query = new URLSearchParams();
    if (cursor) query.set("cursor", cursor);
    query.set("limit", String(limit));
    return request<Page<Utterance>>(
      `/api/sessions/${sessionId}/utterances?${query.toString()}`,
    );
  },
  agentHistory: (sessionId: string, cursor?: string, limit = 50) => {
    const query = new URLSearchParams();
    if (cursor) query.set("cursor", cursor);
    query.set("limit", String(limit));
    return request<AgentHistoryPage>(
      `/api/sessions/${sessionId}/agent-history?${query.toString()}`,
    );
  },
  updateSession: (
    sessionId: string,
    body: Partial<
      Pick<
        SessionSummary,
        | "title"
        | "description"
        | "language"
        | "initial_prompt"
        | "action_preset_id"
        | "agent_provider"
        | "agent_model"
        | "agent_reasoning_effort"
        | "requested_agent_cwd"
        | "allow_workspace_write"
        | "allow_network"
      >
    > & { create_agent_cwd?: boolean },
  ) =>
    request<SessionSummary>(`/api/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  agentProviders: () =>
    request<{ providers: AgentProviderHealth[] }>("/api/agent/providers"),
  runAction: (sessionId: string, buttonId: string) =>
    request<AgentRun>(`/api/sessions/${sessionId}/agent-runs`, {
      method: "POST",
      body: JSON.stringify({ button_id: buttonId }),
    }),
  runPrompt: (sessionId: string, prompt: string) =>
    request<AgentRun>(`/api/sessions/${sessionId}/agent-runs`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  cancelRun: (runId: string) =>
    request<AgentRun>(`/api/agent-runs/${runId}/cancel`, {
      method: "POST",
    }),
  settings: () => request<GlobalSettings>("/api/settings"),
  updateSettings: (body: Partial<GlobalSettings>) =>
    request<GlobalSettings>("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  resetInitialPrompts: () =>
    request<GlobalSettings>("/api/settings/initial-prompts/reset", {
      method: "POST",
    }),
  pairing: () => request<PairingSettings>("/api/extension/pairing"),
  updatePairing: (token: string) =>
    request<PairingSettings>("/api/extension/pairing", {
      method: "PUT",
      body: JSON.stringify({ token }),
    }),
  regeneratePairing: () =>
    request<PairingSettings>("/api/extension/pairing/regenerate", {
      method: "POST",
    }),
  createButton: (
    body: Pick<
      ButtonDefinition,
      | "enabled"
      | "label"
      | "prompt_template"
      | "context_strategy"
      | "context_value"
      | "hard_character_cap"
    >,
  ) =>
    request<ButtonDefinition>("/api/buttons", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateButton: (buttonId: string, body: Partial<ButtonDefinition>) =>
    request<ButtonDefinition>(`/api/buttons/${buttonId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteButton: (buttonId: string) =>
    request<void>(`/api/buttons/${buttonId}`, { method: "DELETE" }),
  createActionPreset: (body: Pick<ActionPreset, "name" | "button_ids">) =>
    request<ActionPreset>("/api/action-presets", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateActionPreset: (
    presetId: string,
    body: Partial<Pick<ActionPreset, "name" | "button_ids">>,
  ) =>
    request<ActionPreset>(`/api/action-presets/${presetId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteActionPreset: (presetId: string) =>
    request<void>(`/api/action-presets/${presetId}`, { method: "DELETE" }),
};
