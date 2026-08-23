import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import type { GlobalSettings } from "../src/types";
import {
  apiPayload,
  globalSettings,
  installAppTestHarness,
  pairingSettings,
  providerHealth,
  snapshot,
} from "./appTestHarness";

installAppTestHarness();

describe("App settings", () => {
  it("switches and persists the shared interface theme immediately", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation(async (input, options) => {
      const path = String(input);
      if (path.endsWith("/api/settings") && options?.method === "PATCH") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...globalSettings, ui_theme: "light" as const }),
        } as Response;
      }
      if (!defaultFetch)
        throw new Error("Missing default fetch test implementation");
      return defaultFetch(input, options);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Light" }));

    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-theme", "light"),
    );
    expect(localStorage.getItem("elsewise-ui-theme")).toBe("light");
    expect(fetch).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ ui_theme: "light" }),
      }),
    );
  });

  it("switches UI language without changing session language", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(await screen.findByLabelText("UI language"), {
      target: { value: "ru" },
    });
    expect(
      screen.getByRole("heading", { name: "Настройки" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Язык сессии")).not.toBeInTheDocument();
    expect(snapshot.sessions[0]?.language).toBe("ru");
    fireEvent.change(screen.getByLabelText("Язык интерфейса"), {
      target: { value: "fr" },
    });
    expect(
      screen.getByRole("heading", { name: "Paramètres" }),
    ).toBeInTheDocument();
  });

  it("saves global Codex permission defaults", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const settingsPanel = await screen.findByRole("heading", {
      name: "Settings",
    });
    const settingsDrawer = settingsPanel.closest("section") as HTMLElement;
    const saveButtons = within(settingsDrawer).getAllByRole("button", {
      name: "Save",
    });
    expect(saveButtons).toHaveLength(6);
    for (const saveButton of saveButtons) {
      expect(saveButton).toHaveClass("settings-save-button");
      expect(saveButton.querySelector("svg")).not.toBeNull();
    }

    const allowWrite = await screen.findByLabelText(
      "Allow writes in the working directory by default",
    );
    const allowNetwork = screen.getByLabelText(
      "Allow network access by default",
    );
    fireEvent.click(allowWrite);
    fireEvent.click(allowNetwork);
    const form = allowWrite.closest("form");
    fireEvent.click(
      within(form as HTMLFormElement).getByRole("button", { name: "Save" }),
    );

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            default_allow_workspace_write: true,
            default_allow_network: true,
          }),
        }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Settings saved.",
    );
    expect(screen.getByLabelText("Initial prompt · FR")).toHaveValue(
      "FR prompt",
    );
  });

  it("copies, regenerates, and manually saves the extension pairing token", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    vi.mocked(fetch).mockImplementation(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const path = String(input);
        let payload: unknown;
        if (path.endsWith("/api/extension/pairing/regenerate")) {
          payload = {
            ...pairingSettings,
            token: "regenerated-pairing-token",
            generation: 2,
          };
        } else if (
          path.endsWith("/api/extension/pairing") &&
          options?.method === "PUT"
        ) {
          const body = JSON.parse(String(options.body)) as { token: string };
          payload = { ...pairingSettings, token: body.token, generation: 3 };
        } else if (path.endsWith("/api/extension/pairing")) {
          payload = pairingSettings;
        } else if (path.endsWith("/api/agent/providers")) {
          payload = providerHealth;
        } else if (path.endsWith("/api/settings")) {
          payload = globalSettings;
        } else {
          payload = apiPayload(path, snapshot);
        }
        return { ok: true, status: 200, json: async () => payload } as Response;
      },
    );

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const token = await screen.findByLabelText("Pairing token");
    expect(token).toHaveValue(pairingSettings.token);
    fireEvent.click(screen.getByRole("button", { name: "Copy token" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(pairingSettings.token),
    );

    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(token).toHaveValue("regenerated-pairing-token"));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/extension/pairing/regenerate",
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.change(token, {
      target: { value: "manual-pairing-token-value" },
    });
    const form = token.closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/extension/pairing",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ token: "manual-pairing-token-value" }),
        }),
      ),
    );
  });

  it("resets all global initial prompts to backend defaults", async () => {
    const resetSettings: GlobalSettings = {
      ...globalSettings,
      initial_prompts: {
        ru: "Default RU prompt",
        en: "Default EN prompt",
        fr: "Default FR prompt",
        es: "Default ES prompt",
        de: "Default DE prompt",
        "pt-BR": "Default PT-BR prompt",
      },
      initial_prompt_version: 2,
    };
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/settings/initial-prompts/reset")
        ? resetSettings
        : path.endsWith("/api/extension/pairing")
          ? pairingSettings
          : path.endsWith("/api/agent/providers")
            ? providerHealth
            : path.endsWith("/api/settings")
              ? globalSettings
              : apiPayload(path, snapshot);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const promptRu = await screen.findByLabelText("Initial prompt · RU");
    const form = promptRu.closest("form") as HTMLFormElement;
    fireEvent.change(promptRu, { target: { value: "Unsaved custom prompt" } });
    const resetButton = within(form).getByRole("button", {
      name: "Reset to defaults",
    });
    expect(resetButton).toHaveClass("settings-reset-button");
    expect(resetButton.querySelector("svg")).not.toBeNull();
    fireEvent.click(resetButton);

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings/initial-prompts/reset",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(promptRu).toHaveValue("Default RU prompt");
    expect(screen.getByLabelText("Initial prompt · EN")).toHaveValue(
      "Default EN prompt",
    );
    expect(screen.getByLabelText("Initial prompt · FR")).toHaveValue(
      "Default FR prompt",
    );
  });

  it("shows both provider health states and saves the default agent", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const defaultAgent = await screen.findByLabelText("Default agent");
    const form = defaultAgent.closest("form") as HTMLFormElement;
    expect(within(form).getAllByText("Codex")).not.toHaveLength(0);
    expect(within(form).getAllByText("Claude Code")).not.toHaveLength(0);
    const cliHint = within(form).getByText(
      "Elsewise uses the locally installed and authenticated Codex and Claude Code CLIs.",
    );
    expect(cliHint.nextElementSibling).toHaveClass("provider-health-tags");
    const codexTag = within(form).getByText("Codex", {
      selector: ".provider-health-tag strong",
    }).parentElement;
    const claudeTag = within(form).getByText("Claude", {
      selector: ".provider-health-tag strong",
    }).parentElement;
    expect(codexTag).toHaveClass("ready");
    expect(codexTag).toHaveTextContent("CodexReady");
    expect(claudeTag).toHaveClass("not-ready");
    expect(claudeTag).toHaveTextContent("ClaudeNot ready");
    expect(claudeTag).toHaveAttribute(
      "title",
      "Claude Code CLI is unavailable.",
    );
    fireEvent.change(defaultAgent, { target: { value: "claude" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            default_agent_provider: "claude",
            default_agent_model: null,
            default_agent_reasoning_effort: null,
            codex_executable: "codex",
            claude_executable: "claude",
          }),
        }),
      ),
    );
  });

  it("saves the global model and reasoning defaults", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const model = await screen.findByLabelText("Model");
    const reasoning = screen.getByLabelText("Effort level");
    expect(model).toHaveValue("gpt-5.6-sol");
    expect(reasoning).toHaveValue("low");
    fireEvent.change(reasoning, { target: { value: "high" } });
    const form = model.closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            default_agent_provider: "codex",
            default_agent_model: "gpt-5.6-sol",
            default_agent_reasoning_effort: "high",
            codex_executable: "codex",
            claude_executable: "claude",
          }),
        }),
      ),
    );
  });

  it("saves the free prompt context settings", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const strategy = await screen.findByLabelText(
      "Free prompt context strategy",
    );
    const value = screen.getByLabelText("Free prompt context amount");
    const cap = screen.getByLabelText("Free prompt character limit");
    expect(value).toBeEnabled();

    fireEvent.change(strategy, { target: { value: "all" } });
    expect(value).toBeDisabled();

    fireEvent.change(strategy, { target: { value: "last_minutes" } });
    expect(value).toBeEnabled();
    fireEvent.change(value, { target: { value: "12" } });
    fireEvent.change(cap, { target: { value: "24000" } });
    const form = strategy.closest("form");
    fireEvent.click(
      within(form as HTMLFormElement).getByRole("button", { name: "Save" }),
    );

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            free_prompt_context_strategy: "last_minutes",
            free_prompt_context_value: 12,
            free_prompt_hard_character_cap: 24_000,
          }),
        }),
      ),
    );
  });

  it("saves the user's caption names for Meet, Teams, and Zoom", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const meetName = await screen.findByLabelText("Your name in Google Meet");
    const teamsName = screen.getByLabelText("Your name in Microsoft Teams");
    const zoomName = screen.getByLabelText("Your name in Zoom");
    fireEvent.change(meetName, { target: { value: "  Alex Meet  " } });
    fireEvent.change(teamsName, { target: { value: "Alex Teams" } });
    fireEvent.change(zoomName, {
      target: { value: "  Evgenii Gerasimenko  " },
    });
    const form = meetName.closest("form");
    fireEvent.click(
      within(form as HTMLFormElement).getByRole("button", { name: "Save" }),
    );

    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            google_meet_own_name: "Alex Meet",
            microsoft_teams_own_name: "Alex Teams",
            zoom_own_name: "Evgenii Gerasimenko",
          }),
        }),
      ),
    );
  });

  it("opens the create session flow", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    expect(
      await screen.findByRole("heading", { name: "New session" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Session language")).toHaveValue("ru");
    expect(screen.getByLabelText("Action preset")).toHaveValue(
      "preset-default",
    );
    expect(screen.getByLabelText("Agent")).toHaveValue("codex");
    expect(screen.getByLabelText("Model")).toHaveValue("gpt-5.6-sol");
    expect(screen.getByLabelText("Effort level")).toHaveValue("low");
    expect(screen.getByLabelText("Initial prompt")).toHaveValue("RU prompt");
    expect(document.querySelector(".session-drawer")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Agent"), {
      target: { value: "claude" },
    });
    expect(
      screen.getByText(/This agent is unavailable or not authenticated/),
    ).toBeInTheDocument();
  });

  it("updates the default prompt with language until the user edits it", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "New session" }));

    const language = screen.getByLabelText("Session language");
    const prompt = screen.getByLabelText("Initial prompt");
    fireEvent.change(language, { target: { value: "fr" } });
    expect(prompt).toHaveValue("FR prompt");
    fireEvent.change(language, { target: { value: "en" } });
    expect(prompt).toHaveValue("EN prompt");
    fireEvent.change(prompt, { target: { value: "Custom prompt" } });
    fireEvent.change(language, { target: { value: "ru" } });
    expect(prompt).toHaveValue("Custom prompt");
  });

  it("copies global Codex permission defaults into a new editable session", async () => {
    const permissionDefaults: GlobalSettings = {
      ...globalSettings,
      default_allow_workspace_write: true,
      default_allow_network: true,
    };
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.endsWith("/api/settings")
        ? permissionDefaults
        : path.endsWith("/api/agent/providers")
          ? providerHealth
          : apiPayload(path, snapshot);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "New session" }));

    const allowWrite = await screen.findByLabelText(
      "Allow writes inside this directory",
    );
    const allowNetwork = screen.getByLabelText("Allow network access");
    expect(allowWrite).toBeChecked();
    expect(allowNetwork).toBeChecked();
    fireEvent.click(allowNetwork);
    expect(allowWrite).toBeChecked();
    expect(allowNetwork).not.toBeChecked();
  });

  it("offers to create a missing Codex working directory before saving", async () => {
    const idleSession = structuredClone(snapshot.sessions[0]!);
    idleSession.recording_status = "idle";
    idleSession.agent_status = "not_started";
    let createAttempts = 0;
    vi.mocked(fetch).mockImplementation(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => globalSettings,
          } as Response;
        }
        if (path.endsWith("/api/agent/providers")) {
          return {
            ok: true,
            status: 200,
            json: async () => providerHealth,
          } as Response;
        }
        if (path.endsWith("/api/sessions") && options?.method === "POST") {
          createAttempts += 1;
          if (createAttempts === 1) {
            return {
              ok: false,
              status: 409,
              statusText: "Conflict",
              json: async () => ({
                error: {
                  code: "agent_cwd_missing",
                  message: "Directory missing",
                },
              }),
            } as Response;
          }
          return {
            ok: true,
            status: 201,
            json: async () => idleSession,
          } as Response;
        }
        return {
          ok: true,
          status: 200,
          json: async () => apiPayload(path, snapshot),
        } as Response;
      },
    );

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Directory test" },
    });
    fireEvent.change(
      screen.getByLabelText("Agent working directory (optional)"),
      {
        target: { value: "/missing/project" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Create session" }));

    expect(
      await screen.findByText("This working directory does not exist."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create directory" }));
    await waitFor(() => expect(createAttempts).toBe(2));
    const createRequests = vi
      .mocked(fetch)
      .mock.calls.filter(
        ([path, options]) =>
          String(path).endsWith("/api/sessions") && options?.method === "POST",
      );
    const secondRequest = createRequests[createRequests.length - 1];
    expect(secondRequest?.[1]?.body).toContain('"create_agent_cwd":true');
    expect(secondRequest?.[1]?.body).toContain('"initial_prompt":null');
  });

  it("edits session data in a drawer only before the first start", async () => {
    const idle = structuredClone(snapshot);
    idle.sessions[0]!.recording_status = "idle";
    idle.sessions[0]!.agent_status = "not_started";
    idle.sessions[0]!.started_at = null;
    idle.sessions[0]!.stopped_at = null;
    idle.agent_threads = [];
    vi.mocked(fetch).mockImplementation(async (input) => {
      const path = String(input);
      const payload = path.endsWith("/api/agent/providers")
        ? providerHealth
        : path.endsWith("/api/settings")
          ? globalSettings
          : apiPayload(path, idle);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Product planning" });
    fireEvent.click(screen.getByRole("button", { name: "Edit session" }));
    expect(
      screen.getByRole("heading", { name: "Edit session" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Product planning");
    expect(screen.getByLabelText("Action preset")).toHaveValue(
      "preset-default",
    );
    expect(screen.getByLabelText("Session language")).toBeEnabled();
    expect(screen.getByLabelText("Agent")).toBeEnabled();
    expect(screen.getByLabelText("Initial prompt")).toBeEnabled();
    expect(
      screen.getByLabelText("Agent working directory (optional)"),
    ).toBeEnabled();
    expect(document.querySelector("[data-lock-reason]")).toBeNull();
    expect(screen.queryByText("Agent actions")).not.toBeInTheDocument();
  });

  it("shows stopped sessions with restart rather than start", async () => {
    const stopped = structuredClone(snapshot);
    stopped.sessions[0]!.recording_status = "stopped";
    stopped.sessions[0]!.stopped_at = "2026-08-13T10:30:00Z";
    vi.mocked(fetch).mockImplementation(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const path = String(input);
        if (
          path.endsWith("/api/sessions/session-1") &&
          options?.method === "PATCH"
        ) {
          const changes = JSON.parse(String(options.body));
          return {
            ok: true,
            status: 200,
            json: async () => ({ ...stopped.sessions[0]!, ...changes }),
          } as Response;
        }
        const payload = path.endsWith("/api/agent/providers")
          ? providerHealth
          : path.endsWith("/api/settings")
            ? globalSettings
            : apiPayload(path, stopped);
        return { ok: true, status: 200, json: async () => payload } as Response;
      },
    );
    render(<App />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Restart session" }),
      ).toBeEnabled(),
    );
    const edit = screen.getByRole("button", { name: "Edit session" });
    expect(edit).toBeEnabled();
    const headerButtons = within(
      document.querySelector(".session-header-actions") as HTMLElement,
    ).getAllByRole("button");
    expect(headerButtons[1]).toBe(edit);
    expect(edit).not.toHaveTextContent(/\S/);
    expect(edit.querySelector("svg")).not.toBeNull();
    fireEvent.click(edit);
    expect(screen.getByRole("heading", { name: "Edit session" })).toBeVisible();
    expect(screen.getByLabelText("Title")).toBeEnabled();
    expect(screen.getByLabelText("Description")).toBeEnabled();
    expect(screen.getByLabelText("Model")).toBeEnabled();
    expect(screen.getByLabelText("Effort level")).toBeEnabled();
    expect(
      screen.getByLabelText("Allow writes inside this directory"),
    ).toBeEnabled();
    expect(screen.getByLabelText("Allow network access")).toBeEnabled();
    expect(screen.getByLabelText("Session language")).toBeDisabled();
    expect(screen.getByLabelText("Action preset")).toBeDisabled();
    expect(screen.getByLabelText("Agent")).toBeDisabled();
    expect(screen.getByLabelText("Initial prompt")).toBeDisabled();
    expect(
      screen.getByLabelText("Agent working directory (optional)"),
    ).toBeDisabled();
    expect(
      document.querySelectorAll(
        '[data-lock-reason="Locked after first start"]',
      ),
    ).toHaveLength(5);

    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Renamed after stop" },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Updated after stop" },
    });
    fireEvent.click(screen.getByLabelText("Allow network access"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", {
          name: "Confirm permission changes",
        }),
      ).getByRole("button", { name: "Continue" }),
    );
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/sessions/session-1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            title: "Renamed after stop",
            description: "Updated after stop",
            agent_model: "gpt-5.6-sol",
            agent_reasoning_effort: "low",
            allow_workspace_write: false,
            allow_network: true,
          }),
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit session" }));
    const sessionDrawer = document.querySelector(
      ".session-drawer",
    ) as HTMLElement;
    fireEvent.click(
      within(sessionDrawer).getByRole("button", { name: "Cancel" }),
    );
    const actions = screen.getByRole("button", { name: "Actions" });
    expect(actions).toBeEnabled();
    fireEvent.click(actions);
    expect(
      await screen.findByRole("tab", { name: "Agent actions" }),
    ).toBeVisible();
  });
});
