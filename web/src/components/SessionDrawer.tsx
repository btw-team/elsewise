import { FormEvent, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import { apiErrorMessage } from "../api/errors";
import { AgentModelFields } from "./AgentModelFields";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldLabel } from "./FieldLabel";
import { ModalPortal } from "./ModalPortal";
import { useModalFocus } from "./useModalFocus";
import type { TranslationKey } from "../i18n/catalogs";
import {
  isSupportedLanguage,
  LANGUAGE_LABELS,
  SUPPORTED_LANGUAGES,
} from "../i18n/languages";
import type {
  ActionPreset,
  AgentProviderHealth,
  GlobalSettings,
  SessionSummary,
  SupportedLanguage,
} from "../types";

type Translator = (key: TranslationKey) => string;

interface SessionDraft {
  title: string;
  description: string;
  language: SupportedLanguage;
  initialPrompt: string;
  actionPresetId: string;
  agentProvider: SessionSummary["agent_provider"];
  agentModel: string | null;
  agentReasoningEffort: string | null;
  cwd: string;
  allowWrite: boolean;
  allowNetwork: boolean;
}

function initialDraft(
  mode: "create" | "edit",
  session: SessionSummary | null,
  defaults: GlobalSettings,
  presets: ActionPreset[],
): SessionDraft {
  const defaultPresetId = presets.find((preset) => preset.is_default)?.id ?? "";
  if (mode === "edit" && session) {
    const language = isSupportedLanguage(session.language)
      ? session.language
      : defaults.default_meeting_language;
    return {
      title: session.title,
      description: session.description,
      language,
      initialPrompt:
        session.initial_prompt || defaults.initial_prompts[language],
      actionPresetId: presets.some(
        (preset) => preset.id === session.action_preset_id,
      )
        ? (session.action_preset_id ?? defaultPresetId)
        : defaultPresetId,
      agentProvider: session.agent_provider,
      agentModel: session.agent_model,
      agentReasoningEffort: session.agent_reasoning_effort,
      cwd: session.requested_agent_cwd ?? "",
      allowWrite: session.allow_workspace_write,
      allowNetwork: session.allow_network,
    };
  }
  const language = defaults.default_meeting_language;
  return {
    title: "",
    description: "",
    language,
    initialPrompt: defaults.initial_prompts[language],
    actionPresetId: defaultPresetId,
    agentProvider: defaults.default_agent_provider,
    agentModel: defaults.default_agent_model,
    agentReasoningEffort: defaults.default_agent_reasoning_effort,
    cwd: "",
    allowWrite: defaults.default_allow_workspace_write,
    allowNetwork: defaults.default_allow_network,
  };
}

export function SessionDrawer({
  mode,
  session,
  defaults,
  presets,
  providers,
  providerLocked,
  t,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  session: SessionSummary | null;
  defaults: GlobalSettings;
  presets: ActionPreset[];
  providers: AgentProviderHealth[];
  providerLocked: boolean;
  t: Translator;
  onClose: () => void;
  onSaved: (session: SessionSummary) => void;
}) {
  const [draft, setDraft] = useState(() =>
    initialDraft(mode, session, defaults, presets),
  );
  const [promptCustomized, setPromptCustomized] = useState(mode === "edit");
  const [missingDirectory, setMissingDirectory] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useModalFocus(onClose, busy);
  const [confirmPermissions, setConfirmPermissions] = useState(false);
  const cwdInput = useRef<HTMLInputElement>(null);
  const fallbackActionPresetId =
    presets.find((preset) => preset.is_default)?.id ?? "";
  const selectedActionPresetId = presets.some(
    (preset) => preset.id === draft.actionPresetId,
  )
    ? draft.actionPresetId
    : fallbackActionPresetId;
  const selectedProvider = providers.find(
    (provider) => provider.id === draft.agentProvider,
  );
  const editing = mode === "edit" && session !== null;
  const sessionRunning = editing && session.recording_status === "running";
  const sessionHasStarted =
    editing &&
    (session.started_at !== null || session.recording_status === "stopped");
  const temporarilyLockedReason = sessionRunning
    ? t("stopSessionToEdit")
    : null;
  const permanentlyLockedReason = sessionHasStarted
    ? t("lockedAfterFirstStart")
    : null;
  const prestartLockReason = temporarilyLockedReason ?? permanentlyLockedReason;
  const prestartFieldsDisabled = Boolean(prestartLockReason);

  async function persist(createAgentCwd: boolean) {
    if (sessionRunning) return;
    setBusy(true);
    setError("");
    try {
      const saved =
        mode === "edit" && session
          ? await api.updateSession(
              session.id,
              sessionHasStarted
                ? {
                    title: draft.title,
                    description: draft.description,
                    agent_model: draft.agentModel,
                    agent_reasoning_effort: draft.agentReasoningEffort,
                    allow_workspace_write: draft.allowWrite,
                    allow_network: draft.allowNetwork,
                  }
                : {
                    title: draft.title,
                    description: draft.description,
                    language: draft.language,
                    initial_prompt: draft.initialPrompt,
                    action_preset_id: selectedActionPresetId || null,
                    agent_provider: draft.agentProvider,
                    agent_model: draft.agentModel,
                    agent_reasoning_effort: draft.agentReasoningEffort,
                    requested_agent_cwd: draft.cwd || null,
                    create_agent_cwd: createAgentCwd,
                    allow_workspace_write: draft.allowWrite,
                    allow_network: draft.allowNetwork,
                  },
            )
          : await api.createSession({
              title: draft.title,
              description: draft.description,
              language: draft.language,
              initial_prompt: promptCustomized ? draft.initialPrompt : null,
              action_preset_id: selectedActionPresetId || null,
              agent_provider: draft.agentProvider,
              agent_model: draft.agentModel,
              agent_reasoning_effort: draft.agentReasoningEffort,
              requested_agent_cwd: draft.cwd || null,
              create_agent_cwd: createAgentCwd,
              allow_workspace_write: draft.allowWrite,
              allow_network: draft.allowNetwork,
            });
      onSaved(saved);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "agent_cwd_missing") {
        setMissingDirectory(draft.cwd);
      } else {
        setError(apiErrorMessage(caught, t));
      }
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const baselineWrite =
      mode === "edit"
        ? Boolean(session?.allow_workspace_write)
        : defaults.default_allow_workspace_write;
    const baselineNetwork =
      mode === "edit"
        ? Boolean(session?.allow_network)
        : defaults.default_allow_network;
    if (
      (draft.allowWrite && !baselineWrite) ||
      (draft.allowNetwork && !baselineNetwork)
    ) {
      setConfirmPermissions(true);
      return;
    }
    void persist(false);
  }

  return (
    <ModalPortal>
      <>
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={onClose}
        >
          <section
            ref={dialog}
            tabIndex={-1}
            className="settings-drawer session-drawer"
            role="dialog"
            aria-modal="true"
            aria-busy={busy}
            aria-labelledby="session-drawer-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-heading">
              <h2 id="session-drawer-title">
                {mode === "create" ? t("newSession") : t("editSession")}
              </h2>
              <button type="button" aria-label={t("close")} onClick={onClose}>
                ×
              </button>
            </div>
            <form className="session-editor-form" onSubmit={submit}>
              <label>
                <FieldLabel lockReason={temporarilyLockedReason}>
                  {t("title")}
                </FieldLabel>
                <input
                  required
                  autoFocus
                  disabled={sessionRunning}
                  maxLength={512}
                  value={draft.title}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <FieldLabel lockReason={temporarilyLockedReason}>
                  {t("description")}
                </FieldLabel>
                <textarea
                  rows={3}
                  disabled={sessionRunning}
                  maxLength={20_000}
                  value={draft.description}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <FieldLabel lockReason={prestartLockReason}>
                  {t("sessionLanguage")}
                </FieldLabel>
                <select
                  disabled={prestartFieldsDisabled}
                  value={draft.language}
                  onChange={(event) => {
                    const language = event.target.value as SupportedLanguage;
                    setDraft((current) => ({
                      ...current,
                      language,
                      initialPrompt: promptCustomized
                        ? current.initialPrompt
                        : defaults.initial_prompts[language],
                    }));
                  }}
                >
                  {SUPPORTED_LANGUAGES.map((language) => (
                    <option key={language} value={language}>
                      {LANGUAGE_LABELS[language]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <FieldLabel lockReason={prestartLockReason}>
                  {t("sessionActionPreset")}
                </FieldLabel>
                <select
                  required
                  disabled={prestartFieldsDisabled}
                  value={selectedActionPresetId}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      actionPresetId: event.target.value,
                    }))
                  }
                >
                  {presets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <FieldLabel
                  lockReason={
                    temporarilyLockedReason ??
                    (providerLocked || sessionHasStarted
                      ? t("lockedAfterFirstStart")
                      : null)
                  }
                >
                  {t("sessionAgent")}
                </FieldLabel>
                <select
                  value={draft.agentProvider}
                  disabled={providerLocked || prestartFieldsDisabled}
                  onChange={(event) => {
                    const providerId = event.target
                      .value as SessionSummary["agent_provider"];
                    const provider = providers.find(
                      (candidate) => candidate.id === providerId,
                    );
                    const useGlobalDefaults =
                      providerId === defaults.default_agent_provider;
                    const model = useGlobalDefaults
                      ? provider?.models.find(
                          (option) =>
                            option.id === defaults.default_agent_model,
                        )
                      : provider?.models[0];
                    setDraft((current) => ({
                      ...current,
                      agentProvider: providerId,
                      agentModel: model?.id ?? null,
                      agentReasoningEffort: useGlobalDefaults
                        ? defaults.default_agent_reasoning_effort
                        : (model?.default_reasoning_effort ?? null),
                    }));
                  }}
                >
                  <option value="codex">Codex</option>
                  <option value="claude">Claude Code</option>
                </select>
              </label>
              {selectedProvider && selectedProvider.status !== "ready" && (
                <p className="settings-hint warning">
                  {t("agentUnavailableHint")}
                </p>
              )}
              {selectedProvider?.status === "ready" && (
                <AgentModelFields
                  provider={selectedProvider}
                  model={draft.agentModel}
                  reasoningEffort={draft.agentReasoningEffort}
                  disabled={sessionRunning}
                  lockReason={temporarilyLockedReason}
                  t={t}
                  onChange={(model, reasoningEffort) =>
                    setDraft((current) => ({
                      ...current,
                      agentModel: model,
                      agentReasoningEffort: reasoningEffort,
                    }))
                  }
                />
              )}
              <label>
                <FieldLabel lockReason={prestartLockReason}>
                  {t("sessionInitialPrompt")}
                </FieldLabel>
                <textarea
                  required
                  rows={7}
                  disabled={prestartFieldsDisabled}
                  maxLength={20_000}
                  value={draft.initialPrompt}
                  onChange={(event) => {
                    setPromptCustomized(true);
                    setDraft((current) => ({
                      ...current,
                      initialPrompt: event.target.value,
                    }));
                  }}
                />
              </label>
              <label>
                <FieldLabel lockReason={prestartLockReason}>
                  {t("cwd")}
                </FieldLabel>
                <input
                  ref={cwdInput}
                  disabled={prestartFieldsDisabled}
                  maxLength={4096}
                  value={draft.cwd}
                  onChange={(event) => {
                    setMissingDirectory("");
                    setDraft((current) => ({
                      ...current,
                      cwd: event.target.value,
                    }));
                  }}
                />
              </label>
              <label className="inline-check">
                <input
                  type="checkbox"
                  disabled={sessionRunning}
                  checked={draft.allowWrite}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      allowWrite: event.target.checked,
                    }))
                  }
                />
                <FieldLabel lockReason={temporarilyLockedReason}>
                  {t("allowWrite")}
                </FieldLabel>
              </label>
              <label className="inline-check">
                <input
                  type="checkbox"
                  disabled={sessionRunning}
                  checked={draft.allowNetwork}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      allowNetwork: event.target.checked,
                    }))
                  }
                />
                <FieldLabel lockReason={temporarilyLockedReason}>
                  {t("allowNetwork")}
                </FieldLabel>
              </label>
              {missingDirectory && (
                <div className="directory-confirmation" role="alert">
                  <strong>{t("directoryMissing")}</strong>
                  <code>{missingDirectory}</code>
                  <p>{t("directoryCreateQuestion")}</p>
                  <div>
                    <button
                      type="button"
                      onClick={() => {
                        setMissingDirectory("");
                        cwdInput.current?.focus();
                      }}
                    >
                      {t("cancel")}
                    </button>
                    <button
                      type="button"
                      className="primary"
                      disabled={busy || sessionRunning}
                      onClick={() => void persist(true)}
                    >
                      {t("createDirectory")}
                    </button>
                  </div>
                </div>
              )}
              {error && <p className="form-error">{error}</p>}
              <div className="session-editor-actions">
                <button type="button" onClick={onClose}>
                  {t("cancel")}
                </button>
                <button className="primary" disabled={busy || sessionRunning}>
                  {mode === "create" ? t("createSession") : t("saveChanges")}
                </button>
              </div>
            </form>
          </section>
        </div>
        {confirmPermissions && (
          <ConfirmDialog
            title={t("confirmPermissionsTitle")}
            message={t("permissionsWarning")}
            confirmLabel={t("continue")}
            cancelLabel={t("cancel")}
            closeLabel={t("close")}
            busy={busy}
            onCancel={() => setConfirmPermissions(false)}
            onConfirm={() => {
              setConfirmPermissions(false);
              void persist(false);
            }}
          />
        )}
      </>
    </ModalPortal>
  );
}
