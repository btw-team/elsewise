import { FloppyDisk } from "@phosphor-icons/react/FloppyDisk";
import { Plus } from "@phosphor-icons/react/Plus";
import { Trash } from "@phosphor-icons/react/Trash";
import { type FormEvent, useEffect, useState } from "react";

import { api } from "../api/client";
import { apiErrorMessage } from "../api/errors";
import type { TranslationKey } from "../i18n/catalogs";
import type { ActionPreset, ButtonDefinition, ContextStrategy } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import { ModalPortal } from "./ModalPortal";
import { useModalFocus } from "./useModalFocus";

type Translator = (key: TranslationKey) => string;
type Tab = "actions" | "presets";

const MAX_ACTIONS = 288;
const MAX_PRESETS = 24;
const MAX_PRESET_ACTIONS = 12;

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

function ActionEditor({
  action,
  t,
  onSaved,
  onDeleted,
  onError,
}: {
  action: ButtonDefinition | null;
  t: Translator;
  onSaved: (action: ButtonDefinition) => Promise<void>;
  onDeleted: (id: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [strategy, setStrategy] = useState<ContextStrategy>(
    action?.context_strategy ?? "since_previous_turn",
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const usesAmount = strategy !== "all";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const body = {
      enabled: true,
      label: String(values.get("label")).trim(),
      prompt_template: String(values.get("prompt")).trim(),
      context_strategy: strategy,
      context_value: usesAmount ? Number(values.get("value")) : null,
      hard_character_cap: Number(values.get("cap")),
    };
    try {
      const saved = action
        ? await api.updateButton(action.id, body)
        : await api.createButton(body);
      await onSaved(saved);
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function deleteAction() {
    if (!action) return;
    setDeleting(true);
    try {
      await api.deleteButton(action.id);
      setConfirmDelete(false);
      await onDeleted(action.id);
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <form
        className="action-detail-form"
        onSubmit={(event) => void save(event)}
      >
        <div className="editor-toolbar">
          <h3>{action?.label ?? t("newAction")}</h3>
          <div>
            {action && (
              <button
                type="button"
                className="text-danger"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash aria-hidden="true" weight="regular" />
                {t("delete")}
              </button>
            )}
            <button>
              <FloppyDisk aria-hidden="true" weight="regular" />
              {t("save")}
            </button>
          </div>
        </div>
        <div className="action-detail-scroll">
          <label>
            {t("buttonLabel")}
            <input
              name="label"
              defaultValue={action?.label ?? ""}
              required
              autoFocus={!action}
              maxLength={128}
            />
          </label>
          <label>
            {t("prompt")}
            <textarea
              name="prompt"
              defaultValue={action?.prompt_template ?? ""}
              required
              rows={10}
              maxLength={20_000}
            />
          </label>
          <div className="action-field-grid">
            <label>
              {t("contextStrategy")}
              <select
                name="strategy"
                value={strategy}
                onChange={(event) =>
                  setStrategy(event.target.value as ContextStrategy)
                }
              >
                <ContextStrategyOptions t={t} />
              </select>
            </label>
            <label>
              {t("contextValue")}
              <input
                name="value"
                type="number"
                min={1}
                max={100_000}
                disabled={!usesAmount}
                defaultValue={action?.context_value ?? 5}
              />
            </label>
            <label>
              {t("characterLimit")}
              <input
                name="cap"
                type="number"
                min={1_000}
                max={200_000}
                defaultValue={action?.hard_character_cap ?? 50_000}
                required
              />
            </label>
          </div>
        </div>
      </form>
      {confirmDelete && (
        <ConfirmDialog
          title={t("confirmDeletionTitle")}
          message={t("deleteButtonConfirm")}
          confirmLabel={t("delete")}
          cancelLabel={t("cancel")}
          closeLabel={t("close")}
          destructive
          busy={deleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => void deleteAction()}
        />
      )}
    </>
  );
}

function PresetActionCard({
  action,
  mode,
  disabled,
  t,
  onClick,
}: {
  action: ButtonDefinition;
  mode: "add" | "remove";
  disabled?: boolean;
  t: Translator;
  onClick: () => void;
}) {
  return (
    <article
      className={`preset-action-card ${mode === "remove" ? "included" : ""}`}
    >
      <div>
        <strong>{action.label}</strong>
        <p title={action.prompt_template}>{action.prompt_template}</p>
      </div>
      <button type="button" disabled={disabled} onClick={onClick}>
        {mode === "add" ? t("add") : t("remove")}
      </button>
    </article>
  );
}

function PresetEditor({
  preset,
  buttons,
  t,
  onSaved,
  onDeleted,
  onError,
  onSuccess,
}: {
  preset: ActionPreset | null;
  buttons: ButtonDefinition[];
  t: Translator;
  onSaved: (preset: ActionPreset) => Promise<void>;
  onDeleted: (id: string) => Promise<void>;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
}) {
  const [buttonIds, setButtonIds] = useState<string[]>(
    preset?.button_ids ?? [],
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const buttonById = new Map(buttons.map((button) => [button.id, button]));
  const selected = buttonIds.flatMap((id) => {
    const button = buttonById.get(id);
    return button ? [button] : [];
  });
  const selectedIds = new Set(buttonIds);
  const available = buttons.filter((button) => !selectedIds.has(button.id));

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const body = {
      name: preset?.is_default ? "Default" : String(values.get("name")).trim(),
      button_ids: buttonIds,
    };
    try {
      const saved = preset
        ? await api.updateActionPreset(preset.id, body)
        : await api.createActionPreset(body);
      await onSaved(saved);
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    }
  }

  async function deletePreset() {
    if (!preset) return;
    setDeleting(true);
    try {
      await api.deleteActionPreset(preset.id);
      setConfirmDelete(false);
      await onDeleted(preset.id);
    } catch (caught) {
      onError(apiErrorMessage(caught, t));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <form
        className="preset-detail-form"
        onSubmit={(event) => void save(event)}
      >
        <div className="editor-toolbar">
          <h3>{preset?.name ?? t("newPreset")}</h3>
          <div>
            {preset && !preset.is_default && (
              <button
                type="button"
                className="text-danger"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash aria-hidden="true" weight="regular" />
                {t("delete")}
              </button>
            )}
            <button>
              <FloppyDisk aria-hidden="true" weight="regular" />
              {t("save")}
            </button>
          </div>
        </div>
        <div className="preset-detail-scroll">
          <label className="preset-name-field">
            {t("presetName")}
            <input
              name="name"
              defaultValue={preset?.name ?? ""}
              disabled={preset?.is_default}
              required
              autoFocus={!preset}
              maxLength={128}
            />
          </label>
          <section className="preset-action-section">
            <div className="preset-section-heading">
              <h4>{t("presetIncludedActions")}</h4>
              <span>
                {selected.length} / {MAX_PRESET_ACTIONS}
              </span>
            </div>
            <div className="preset-card-list">
              {selected.map((action) => (
                <PresetActionCard
                  key={action.id}
                  action={action}
                  mode="remove"
                  t={t}
                  onClick={() => {
                    setButtonIds((current) =>
                      current.filter((id) => id !== action.id),
                    );
                    onSuccess(t("presetActionRemoved"));
                  }}
                />
              ))}
              {selected.length === 0 && (
                <p className="preset-empty">{t("presetEmpty")}</p>
              )}
            </div>
          </section>
          <section className="preset-action-section available">
            <div className="preset-section-heading">
              <h4>{t("presetAvailableActions")}</h4>
              <span>{available.length}</span>
            </div>
            <div className="preset-card-list">
              {available.map((action) => (
                <PresetActionCard
                  key={action.id}
                  action={action}
                  mode="add"
                  disabled={selected.length >= MAX_PRESET_ACTIONS}
                  t={t}
                  onClick={() =>
                    setButtonIds((current) => [...current, action.id])
                  }
                />
              ))}
              {available.length === 0 && (
                <p className="preset-empty">{t("noAvailableActions")}</p>
              )}
            </div>
          </section>
        </div>
      </form>
      {confirmDelete && (
        <ConfirmDialog
          title={t("confirmDeletionTitle")}
          message={t("deletePresetConfirm")}
          confirmLabel={t("delete")}
          cancelLabel={t("cancel")}
          closeLabel={t("close")}
          destructive
          busy={deleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => void deletePreset()}
        />
      )}
    </>
  );
}

export function ActionsDrawer({
  buttons,
  presets,
  t,
  onClose,
  onChanged,
  onError,
  onSuccess,
}: {
  buttons: ButtonDefinition[];
  presets: ActionPreset[];
  t: Translator;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
}) {
  const dialog = useModalFocus(onClose);
  const [tab, setTab] = useState<Tab>("presets");
  const [selectedActionId, setSelectedActionId] = useState<string | null>(
    buttons[0]?.id ?? null,
  );
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(
    presets[0]?.id ?? null,
  );
  const [creatingAction, setCreatingAction] = useState(false);
  const [creatingPreset, setCreatingPreset] = useState(false);

  useEffect(() => {
    if (
      !creatingAction &&
      !buttons.some((button) => button.id === selectedActionId)
    )
      setSelectedActionId(buttons[0]?.id ?? null);
  }, [buttons, creatingAction, selectedActionId]);

  useEffect(() => {
    if (
      !creatingPreset &&
      !presets.some((preset) => preset.id === selectedPresetId)
    )
      setSelectedPresetId(presets[0]?.id ?? null);
  }, [creatingPreset, presets, selectedPresetId]);

  const selectedAction =
    buttons.find((button) => button.id === selectedActionId) ?? null;
  const selectedPreset =
    presets.find((preset) => preset.id === selectedPresetId) ?? null;

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
          className="actions-drawer"
          role="dialog"
          aria-modal="true"
          aria-label={t("actions")}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="actions-topbar">
            <div className="actions-tabs" role="tablist">
              <button
                role="tab"
                aria-selected={tab === "presets"}
                className={tab === "presets" ? "active" : ""}
                onClick={() => setTab("presets")}
              >
                {t("actionPresets")}
              </button>
              <button
                role="tab"
                aria-selected={tab === "actions"}
                className={tab === "actions" ? "active" : ""}
                onClick={() => setTab("actions")}
              >
                {t("agentActions")}
              </button>
            </div>
            <button
              className="actions-close"
              type="button"
              aria-label={t("close")}
              onClick={onClose}
            >
              ×
            </button>
          </div>
          {tab === "actions" ? (
            <div className="actions-editor-layout">
              <aside className="editor-list-panel">
                <div className="editor-list-count">
                  {buttons.length} / {MAX_ACTIONS}
                </div>
                <nav aria-label={t("agentActions")}>
                  {buttons.map((button) => (
                    <button
                      key={button.id}
                      className={
                        !creatingAction && button.id === selectedActionId
                          ? "selected"
                          : ""
                      }
                      onClick={() => {
                        setCreatingAction(false);
                        setSelectedActionId(button.id);
                      }}
                    >
                      <strong>{button.label}</strong>
                      <span>{button.prompt_template}</span>
                    </button>
                  ))}
                </nav>
                <button
                  className="editor-add-button"
                  disabled={buttons.length >= MAX_ACTIONS}
                  onClick={() => setCreatingAction(true)}
                >
                  <Plus aria-hidden="true" weight="regular" />
                  {t("addAction")}
                </button>
              </aside>
              <ActionEditor
                key={creatingAction ? "new" : selectedAction?.id}
                action={creatingAction ? null : selectedAction}
                t={t}
                onError={onError}
                onSaved={async (saved) => {
                  setCreatingAction(false);
                  setSelectedActionId(saved.id);
                  await onChanged();
                  onSuccess(t("actionSaved"));
                }}
                onDeleted={async (id) => {
                  setSelectedActionId(
                    buttons.find((button) => button.id !== id)?.id ?? null,
                  );
                  await onChanged();
                  onSuccess(t("actionDeleted"));
                }}
              />
            </div>
          ) : (
            <div className="actions-editor-layout">
              <aside className="editor-list-panel">
                <div className="editor-list-count">
                  {presets.length} / {MAX_PRESETS}
                </div>
                <nav aria-label={t("actionPresets")}>
                  {presets.map((preset) => (
                    <button
                      key={preset.id}
                      className={
                        !creatingPreset && preset.id === selectedPresetId
                          ? "selected"
                          : ""
                      }
                      onClick={() => {
                        setCreatingPreset(false);
                        setSelectedPresetId(preset.id);
                      }}
                    >
                      <strong>{preset.name}</strong>
                      <span>
                        {preset.button_ids.length} {t("actionsCount")}
                      </span>
                    </button>
                  ))}
                </nav>
                <button
                  className="editor-add-button"
                  disabled={presets.length >= MAX_PRESETS}
                  onClick={() => setCreatingPreset(true)}
                >
                  <Plus aria-hidden="true" weight="regular" />
                  {t("addPreset")}
                </button>
              </aside>
              <PresetEditor
                key={creatingPreset ? "new" : selectedPreset?.id}
                preset={creatingPreset ? null : selectedPreset}
                buttons={buttons}
                t={t}
                onError={onError}
                onSuccess={onSuccess}
                onSaved={async (saved) => {
                  setCreatingPreset(false);
                  setSelectedPresetId(saved.id);
                  await onChanged();
                  onSuccess(t("presetSaved"));
                }}
                onDeleted={async (id) => {
                  setSelectedPresetId(
                    presets.find((preset) => preset.id !== id)?.id ?? null,
                  );
                  await onChanged();
                  onSuccess(t("presetDeleted"));
                }}
              />
            </div>
          )}
        </section>
      </div>
    </ModalPortal>
  );
}
