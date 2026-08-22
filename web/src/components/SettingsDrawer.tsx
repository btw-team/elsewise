import { ArrowsCounterClockwise } from "@phosphor-icons/react/ArrowsCounterClockwise";
import { Copy } from "@phosphor-icons/react/Copy";
import { FloppyDisk } from "@phosphor-icons/react/FloppyDisk";
import { FormEvent, useEffect, useState } from "react";

import { api } from "../api/client";
import { apiErrorMessage } from "../api/errors";
import { AgentModelFields } from "./AgentModelFields";
import { ModalPortal } from "./ModalPortal";
import { useModalFocus } from "./useModalFocus";
import {
  translate,
  type TranslationKey,
  type UiLanguage,
} from "../i18n/catalogs";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../i18n/languages";
import type {
  ContextStrategy,
  AgentProviderHealth,
  GlobalSettings,
  PairingSettings,
  SupportedLanguage,
} from "../types";

type Translator = (key: TranslationKey) => string;

const emptySettings: GlobalSettings = {
  ui_language: "en",
  default_meeting_language: "ru",
  initial_prompts: { ru: "", en: "", fr: "", es: "", de: "", "pt-BR": "" },
  initial_prompt_version: 1,
  default_agent_provider: "codex",
  default_agent_model: null,
  default_agent_reasoning_effort: null,
  codex_executable: "codex",
  claude_executable: "claude",
  google_meet_own_name: "",
  microsoft_teams_own_name: "",
  zoom_own_name: "",
  free_prompt_context_strategy: "since_previous_turn",
  free_prompt_context_value: 5,
  free_prompt_hard_character_cap: 50_000,
  default_allow_workspace_write: false,
  default_allow_network: false,
};

const emptyPairing: PairingSettings = {
  token: "",
  masked_token: "",
  created_at: "",
  generation: 0,
};

function ContextStrategyOptions({ t }: { t: Translator }) {
  return (
    <>
      <option value="since_previous_turn">{t("sincePreviousTurn")}</option>
      <option value="last_minutes">{t("lastMinutes")}</option>
      <option value="last_utterances">{t("lastUtterances")}</option>
      <option value="all">{t("allTranscript")}</option>
    </>
  );
}

export function SettingsDrawer({
  uiLanguage,
  setUiLanguage,
  t,
  onClose,
  onError,
  onSuccess,
  onSettingsChanged,
}: {
  uiLanguage: UiLanguage;
  setUiLanguage: (language: UiLanguage) => void;
  t: Translator;
  onClose: () => void;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onSettingsChanged: (settings: GlobalSettings) => void;
}) {
  const dialog = useModalFocus(onClose);
  const [settings, setSettings] = useState(emptySettings);
  const [providers, setProviders] = useState<AgentProviderHealth[]>([]);
  const [pairing, setPairing] = useState(emptyPairing);
  const [pairingBusy, setPairingBusy] = useState(false);
  const [resettingInitialPrompts, setResettingInitialPrompts] = useState(false);

  useEffect(() => {
    void api
      .settings()
      .then(setSettings)
      .catch((caught: unknown) => onError(apiErrorMessage(caught, t)));
    void api
      .agentProviders()
      .then((payload) => setProviders(payload.providers))
      .catch(() => setProviders([]));
    void api
      .pairing()
      .then((payload) => setPairing({ ...emptyPairing, ...payload }))
      .catch((caught: unknown) => onError(apiErrorMessage(caught, t)));
  }, [onError, t]);

  async function savePairing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPairingBusy(true);
    try {
      const updated = await api.updatePairing(pairing.token);
      setPairing(updated);
      onSuccess(t("pairingSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    } finally {
      setPairingBusy(false);
    }
  }

  async function regeneratePairing() {
    setPairingBusy(true);
    try {
      const updated = await api.regeneratePairing();
      setPairing(updated);
      onSuccess(t("pairingRegenerated"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    } finally {
      setPairingBusy(false);
    }
  }

  async function copyPairingToken() {
    try {
      await navigator.clipboard.writeText(pairing.token);
      onSuccess(t("pairingCopied"));
    } catch {
      onError(t("requestFailed"));
    }
  }

  async function saveGlobal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    try {
      const updated = await api.updateSettings({
        default_meeting_language: String(
          values.get("defaultLanguage"),
        ) as SupportedLanguage,
        initial_prompts: Object.fromEntries(
          SUPPORTED_LANGUAGES.map((language) => [
            language,
            String(values.get(`prompt-${language}`)),
          ]),
        ) as GlobalSettings["initial_prompts"],
      });
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("settingsSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function saveAgents(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await api.updateSettings({
        default_agent_provider: settings.default_agent_provider,
        default_agent_model: settings.default_agent_model,
        default_agent_reasoning_effort: settings.default_agent_reasoning_effort,
        codex_executable: settings.codex_executable.trim() || "codex",
        claude_executable: settings.claude_executable.trim() || "claude",
      });
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("settingsSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function resetInitialPrompts() {
    setResettingInitialPrompts(true);
    try {
      const updated = await api.resetInitialPrompts();
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("initialPromptsReset"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    } finally {
      setResettingInitialPrompts(false);
    }
  }

  async function saveFreePromptContext(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await api.updateSettings({
        free_prompt_context_strategy: settings.free_prompt_context_strategy,
        free_prompt_context_value: settings.free_prompt_context_value,
        free_prompt_hard_character_cap: settings.free_prompt_hard_character_cap,
      });
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("settingsSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function saveSpeakerIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const updated = await api.updateSettings({
        google_meet_own_name: settings.google_meet_own_name.trim(),
        microsoft_teams_own_name: settings.microsoft_teams_own_name.trim(),
        zoom_own_name: settings.zoom_own_name.trim(),
      });
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("settingsSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function saveCodexPermissionDefaults(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    try {
      const updated = await api.updateSettings({
        default_allow_workspace_write: settings.default_allow_workspace_write,
        default_allow_network: settings.default_allow_network,
      });
      setSettings(updated);
      onSettingsChanged(updated);
      onSuccess(t("settingsSaved"));
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  const freePromptUsesValue = settings.free_prompt_context_strategy !== "all";
  const selectedDefaultProvider = providers.find(
    (provider) => provider.id === settings.default_agent_provider,
  );

  return (
    <ModalPortal>
      <div
        className="dialog-backdrop"
        role="presentation"
        onMouseDown={onClose}
      >
        <section
          ref={dialog}
          tabIndex={-1}
          className="settings-drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-drawer-title"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="dialog-heading">
            <h2 id="settings-drawer-title">{t("settings")}</h2>
            <button type="button" aria-label={t("close")} onClick={onClose}>
              ×
            </button>
          </div>
          <div className="settings-scroll">
            <section>
              <h3>{t("interface")}</h3>
              <label>
                {t("uiLanguage")}
                <select
                  value={uiLanguage}
                  onChange={(event) => {
                    const next = event.target.value as UiLanguage;
                    setUiLanguage(next);
                    localStorage.setItem("elsewise-ui-language", next);
                    void api
                      .updateSettings({ ui_language: next })
                      .then((updated) => {
                        setSettings(updated);
                        onSettingsChanged(updated);
                        onSuccess(translate(next, "settingsSaved"));
                      })
                      .catch((caught: unknown) =>
                        onError(apiErrorMessage(caught, t)),
                      );
                  }}
                >
                  {SUPPORTED_LANGUAGES.map((language) => (
                    <option key={language} value={language}>
                      {LANGUAGE_LABELS[language]}
                    </option>
                  ))}
                </select>
              </label>
            </section>
            <form
              className="pairing-settings"
              onSubmit={(event) => void savePairing(event)}
            >
              <h3>{t("browserExtensionPairing")}</h3>
              <p className="settings-hint">{t("pairingHint")}</p>
              <label>
                {t("pairingToken")}
                <input
                  className="pairing-token-input"
                  autoComplete="off"
                  spellCheck={false}
                  minLength={16}
                  maxLength={4096}
                  value={pairing.token}
                  onChange={(event) =>
                    setPairing((current) => ({
                      ...current,
                      token: event.target.value,
                    }))
                  }
                />
              </label>
              <div className="pairing-token-actions">
                <button
                  type="button"
                  disabled={pairingBusy || !pairing.token}
                  onClick={() => void copyPairingToken()}
                >
                  <Copy aria-hidden="true" weight="regular" />
                  {t("copyToken")}
                </button>
                <button
                  type="button"
                  disabled={pairingBusy}
                  onClick={() => void regeneratePairing()}
                >
                  <ArrowsCounterClockwise aria-hidden="true" weight="regular" />
                  {t("regenerateToken")}
                </button>
                <button
                  className="settings-save-button"
                  disabled={pairingBusy || pairing.token.trim().length < 16}
                >
                  <FloppyDisk aria-hidden="true" weight="regular" />
                  {t("save")}
                </button>
              </div>
            </form>
            <form
              className="agent-settings"
              onSubmit={(event) => void saveAgents(event)}
            >
              <h3>{t("agents")}</h3>
              <p className="settings-hint">{t("localCliAuthHint")}</p>
              <div className="provider-health-tags">
                {providers.map((provider) => {
                  const ready = provider.status === "ready";
                  const name = provider.id === "claude" ? "Claude" : "Codex";
                  return (
                    <span
                      key={provider.id}
                      className={`provider-health-tag ${ready ? "ready" : "not-ready"}`}
                      title={provider.message ?? undefined}
                    >
                      <strong>{name}</strong>
                      <span>{ready ? t("ready") : t("notReady")}</span>
                    </span>
                  );
                })}
              </div>
              <label>
                {t("codexExecutable")}
                <input
                  value={settings.codex_executable}
                  spellCheck={false}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      codex_executable: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                {t("claudeExecutable")}
                <input
                  value={settings.claude_executable}
                  spellCheck={false}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      claude_executable: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                {t("defaultAgent")}
                <select
                  value={settings.default_agent_provider}
                  onChange={(event) =>
                    setSettings((current) => {
                      const providerId = event.target
                        .value as GlobalSettings["default_agent_provider"];
                      const provider = providers.find(
                        (candidate) => candidate.id === providerId,
                      );
                      const model = provider?.models[0] ?? null;
                      return {
                        ...current,
                        default_agent_provider: providerId,
                        default_agent_model: model?.id ?? null,
                        default_agent_reasoning_effort:
                          model?.default_reasoning_effort ?? null,
                      };
                    })
                  }
                >
                  <option value="codex">Codex</option>
                  <option value="claude">Claude Code</option>
                </select>
              </label>
              {selectedDefaultProvider?.status === "ready" && (
                <AgentModelFields
                  provider={selectedDefaultProvider}
                  model={settings.default_agent_model}
                  reasoningEffort={settings.default_agent_reasoning_effort}
                  t={t}
                  onChange={(model, reasoningEffort) =>
                    setSettings((current) => ({
                      ...current,
                      default_agent_model: model,
                      default_agent_reasoning_effort: reasoningEffort,
                    }))
                  }
                />
              )}
              <button className="settings-save-button">
                <FloppyDisk aria-hidden="true" weight="regular" />
                {t("save")}
              </button>
            </form>
            <form
              className="speaker-identity-settings"
              onSubmit={(event) => void saveSpeakerIdentity(event)}
            >
              <h3>{t("speakerIdentity")}</h3>
              <p className="settings-hint">{t("speakerIdentityHint")}</p>
              <div className="speaker-identity-grid">
                <label>
                  {t("googleMeetOwnName")}
                  <input
                    value={settings.google_meet_own_name}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        google_meet_own_name: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  {t("microsoftTeamsOwnName")}
                  <input
                    value={settings.microsoft_teams_own_name}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        microsoft_teams_own_name: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  {t("zoomOwnName")}
                  <input
                    value={settings.zoom_own_name}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        zoom_own_name: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              <button className="settings-save-button">
                <FloppyDisk aria-hidden="true" weight="regular" />
                {t("save")}
              </button>
            </form>
            <form onSubmit={(event) => void saveGlobal(event)}>
              <h3>{t("globalPrompts")}</h3>
              <label>
                {t("defaultLanguage")}
                <select
                  name="defaultLanguage"
                  value={settings.default_meeting_language}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      default_meeting_language: event.target
                        .value as SupportedLanguage,
                    })
                  }
                >
                  {SUPPORTED_LANGUAGES.map((language) => (
                    <option key={language} value={language}>
                      {LANGUAGE_LABELS[language]}
                    </option>
                  ))}
                </select>
              </label>
              {SUPPORTED_LANGUAGES.map((language) => (
                <label key={language}>
                  {t("sessionInitialPrompt")} · {language.toUpperCase()}
                  <textarea
                    name={`prompt-${language}`}
                    rows={4}
                    value={settings.initial_prompts[language]}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        initial_prompts: {
                          ...settings.initial_prompts,
                          [language]: event.target.value,
                        },
                      })
                    }
                  />
                </label>
              ))}
              <div className="settings-form-actions">
                <button className="settings-save-button">
                  <FloppyDisk aria-hidden="true" weight="regular" />
                  {t("save")}
                </button>
                <button
                  className="settings-reset-button"
                  type="button"
                  disabled={resettingInitialPrompts}
                  onClick={() => void resetInitialPrompts()}
                >
                  <ArrowsCounterClockwise aria-hidden="true" weight="regular" />
                  {t("resetToDefaults")}
                </button>
              </div>
            </form>
            <form
              className="codex-permission-settings"
              onSubmit={(event) => void saveCodexPermissionDefaults(event)}
            >
              <h3>{t("codexPermissionDefaults")}</h3>
              <p className="settings-hint">
                {t("codexPermissionDefaultsHint")}
              </p>
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={settings.default_allow_workspace_write}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      default_allow_workspace_write: event.target.checked,
                    })
                  }
                />
                {t("defaultAllowWrite")}
              </label>
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={settings.default_allow_network}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      default_allow_network: event.target.checked,
                    })
                  }
                />
                {t("defaultAllowNetwork")}
              </label>
              <button className="settings-save-button">
                <FloppyDisk aria-hidden="true" weight="regular" />
                {t("save")}
              </button>
            </form>
            <form
              className="free-prompt-settings"
              onSubmit={(event) => void saveFreePromptContext(event)}
            >
              <h3>{t("freePromptContext")}</h3>
              <p className="settings-hint">{t("freePromptContextHint")}</p>
              <div className="button-grid">
                <label>
                  {t("contextStrategy")}
                  <select
                    aria-label={t("freePromptContextStrategy")}
                    value={settings.free_prompt_context_strategy}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        free_prompt_context_strategy: event.target
                          .value as ContextStrategy,
                      })
                    }
                  >
                    <ContextStrategyOptions t={t} />
                  </select>
                </label>
                <label>
                  {t("contextValue")}
                  <input
                    aria-label={t("freePromptContextValue")}
                    type="number"
                    min={1}
                    max={100_000}
                    disabled={!freePromptUsesValue}
                    value={settings.free_prompt_context_value ?? 5}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        free_prompt_context_value: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  {t("characterLimit")}
                  <input
                    aria-label={t("freePromptCharacterLimit")}
                    type="number"
                    min={1_000}
                    max={200_000}
                    value={settings.free_prompt_hard_character_cap}
                    onChange={(event) =>
                      setSettings({
                        ...settings,
                        free_prompt_hard_character_cap: Number(
                          event.target.value,
                        ),
                      })
                    }
                  />
                </label>
              </div>
              <button className="settings-save-button">
                <FloppyDisk aria-hidden="true" weight="regular" />
                {t("save")}
              </button>
            </form>
          </div>
        </section>
      </div>
    </ModalPortal>
  );
}
