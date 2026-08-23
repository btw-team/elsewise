import type { TranslationKey } from "../i18n/catalogs";
import type { AgentProviderHealth } from "../types";
import { FieldLabel } from "./FieldLabel";

type Translator = (key: TranslationKey) => string;

export function AgentModelFields({
  provider,
  model,
  reasoningEffort,
  disabled = false,
  lockReason,
  t,
  onChange,
}: {
  provider: AgentProviderHealth;
  model: string | null;
  reasoningEffort: string | null;
  disabled?: boolean;
  lockReason?: string | null;
  t: Translator;
  onChange: (model: string | null, reasoningEffort: string | null) => void;
}) {
  const selectedModel = provider.models.find((option) => option.id === model);
  const controlsDisabled = disabled || provider.status !== "ready";

  return (
    <div className="agent-model-fields">
      <label>
        <FieldLabel lockReason={lockReason}>{t("agentModel")}</FieldLabel>
        <select
          value={model ?? ""}
          disabled={controlsDisabled}
          onChange={(event) => {
            const nextModel = event.target.value || null;
            const option = provider.models.find(
              (candidate) => candidate.id === nextModel,
            );
            onChange(nextModel, option?.default_reasoning_effort ?? null);
          }}
        >
          <option value="">{t("cliDefault")}</option>
          {model && !selectedModel && <option value={model}>{model}</option>}
          {provider.models.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <FieldLabel lockReason={lockReason}>{t("agentReasoning")}</FieldLabel>
        <select
          value={reasoningEffort ?? ""}
          disabled={
            controlsDisabled ||
            model === null ||
            !selectedModel?.reasoning_efforts.length
          }
          onChange={(event) => onChange(model, event.target.value || null)}
        >
          <option value="">{t("modelDefault")}</option>
          {reasoningEffort &&
            !selectedModel?.reasoning_efforts.includes(reasoningEffort) && (
              <option value={reasoningEffort}>{reasoningEffort}</option>
            )}
          {selectedModel?.reasoning_efforts.map((effort) => (
            <option key={effort} value={effort}>
              {effort}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
