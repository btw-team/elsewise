import { Diamond } from "@phosphor-icons/react/Diamond";
import { PaperPlaneTilt } from "@phosphor-icons/react/PaperPlaneTilt";
import { lazy, Suspense, type FormEvent, useState } from "react";

import { agentHealthLabel, agentHealthStatus } from "../agentHealth";
import { api } from "../api/client";
import { apiErrorMessage } from "../api/errors";
import type { TranslationKey, UiLanguage } from "../i18n/catalogs";
import type {
  AgentHealth,
  AgentMessage,
  AgentRun,
  SessionSummary,
} from "../types";

type Translator = (key: TranslationKey) => string;
const ACTIVE_RUN_STATUSES = new Set(["queued", "starting", "streaming"]);
const MarkdownAnswer = lazy(() => import("./MarkdownAnswer"));

function runLabel(run: AgentRun, t: Translator): string {
  if (run.button_snapshot.kind === "initial") return t("initialPrompt");
  return String(run.button_snapshot.label ?? t("agentAction"));
}

function runStatusLabel(status: string, t: Translator): string {
  const keys: Record<string, TranslationKey> = {
    queued: "runStatusQueued",
    starting: "runStatusStarting",
    streaming: "runStatusStreaming",
    completed: "runStatusCompleted",
    failed: "runStatusFailed",
    interrupted: "runStatusInterrupted",
    cancelled: "runStatusCancelled",
  };
  const key = keys[status];
  return key ? t(key) : status;
}

function formatTime(value: string, language: UiLanguage): string {
  return new Intl.DateTimeFormat(language, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function directoryName(path: string): string {
  const normalized = path.replace(/[\\/]+$/, "");
  return normalized.split(/[\\/]/).at(-1) || path;
}

export function AgentPanel({
  runs,
  messages,
  health,
  session,
  language,
  t,
  onSubmitPrompt,
  onChanged,
  onError,
  canLoadEarlier,
  loadingEarlier,
  onLoadEarlier,
}: {
  runs: AgentRun[];
  messages: AgentMessage[];
  health: AgentHealth | null;
  session: SessionSummary | null;
  language: UiLanguage;
  t: Translator;
  onSubmitPrompt: (prompt: string) => Promise<boolean>;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
  canLoadEarlier: boolean;
  loadingEarlier: boolean;
  onLoadEarlier: () => Promise<void>;
}) {
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const healthStatus = agentHealthStatus(health);
  const messagesByRun = new Map(
    messages.map((message) => [message.run_id, message]),
  );
  const directoryPath =
    session?.resolved_agent_cwd ?? session?.requested_agent_cwd ?? null;
  const directoryLabel = directoryPath
    ? session?.agent_cwd_fallback
      ? t("cwdFallback")
      : directoryName(directoryPath)
    : null;
  const promptDisabled =
    !session || session.agent_status === "not_started" || sending;

  async function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = prompt.trim();
    if (!normalized || promptDisabled) return;
    setSending(true);
    try {
      if (await onSubmitPrompt(normalized)) setPrompt("");
    } finally {
      setSending(false);
    }
  }

  return (
    <aside className="agent-panel">
      <header>
        <div className="agent-heading-main">
          <Diamond aria-hidden="true" weight="regular" />
          <h2>{t("agent")}</h2>
          <span
            className={`agent-status ${healthStatus}`}
            title={health?.message ?? undefined}
          >
            {agentHealthLabel(health, t)}
          </span>
        </div>
        {directoryLabel && (
          <span
            className={`agent-directory ${session?.agent_cwd_fallback ? "fallback" : ""}`}
            title={directoryPath ?? undefined}
          >
            {directoryLabel}
          </span>
        )}
      </header>
      <div className="agent-scroll">
        {canLoadEarlier && (
          <button
            type="button"
            className="load-earlier"
            disabled={loadingEarlier}
            onClick={() => void onLoadEarlier()}
          >
            {loadingEarlier ? t("loadingEarlier") : t("loadEarlierAgent")}
          </button>
        )}
        {runs.length === 0 ? (
          <div className="agent-empty">
            <Diamond aria-hidden="true" weight="regular" />
            <h3>{t("agentEmpty")}</h3>
            <p>{t("actionsHint")}</p>
          </div>
        ) : (
          runs.map((run) => {
            const message = messagesByRun.get(run.id);
            return (
              <article className={`agent-run ${run.status}`} key={run.id}>
                <div className="agent-run-heading">
                  <div>
                    <strong>{runLabel(run, t)}</strong>
                    <time>{formatTime(run.created_at, language)}</time>
                  </div>
                  <span>{runStatusLabel(run.status, t)}</span>
                </div>
                {message?.text && (
                  <Suspense
                    fallback={<p className="agent-muted">{message.text}</p>}
                  >
                    <MarkdownAnswer text={message.text} />
                  </Suspense>
                )}
                {run.error_message && (
                  <p className="agent-error">{run.error_message}</p>
                )}
                {run.status === "queued" && (
                  <p className="agent-muted">{t("queued")}</p>
                )}
                {run.status === "streaming" && !message?.text && (
                  <p className="agent-muted">{t("thinking")}</p>
                )}
                <div className="agent-run-actions">
                  <details>
                    <summary>{t("details")}</summary>
                    <dl>
                      <dt>{t("context")}</dt>
                      <dd>
                        {run.context_strategy} · {run.context_start ?? "—"} →{" "}
                        {run.context_end ?? "—"}
                      </dd>
                      <dt>{t("cwdShort")}</dt>
                      <dd>{run.cwd}</dd>
                      <dt>{t("request")}</dt>
                      <dd className="prompt-preview">{run.resolved_prompt}</dd>
                    </dl>
                  </details>
                  {ACTIVE_RUN_STATUSES.has(run.status) && (
                    <button
                      onClick={() => {
                        void api
                          .cancelRun(run.id)
                          .then(onChanged)
                          .catch((caught: unknown) =>
                            onError(apiErrorMessage(caught, t)),
                          );
                      }}
                    >
                      {t("cancel")}
                    </button>
                  )}
                </div>
              </article>
            );
          })
        )}
      </div>
      <form className="agent-composer" onSubmit={submitPrompt}>
        <textarea
          rows={1}
          value={prompt}
          aria-label={t("freePrompt")}
          placeholder={t("freePromptPlaceholder")}
          disabled={promptDisabled}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key !== "Enter" ||
              event.shiftKey ||
              event.nativeEvent.isComposing
            )
              return;
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }}
        />
        <button
          type="submit"
          aria-label={t("sendPrompt")}
          title={t("sendPrompt")}
          disabled={promptDisabled || !prompt.trim()}
        >
          <PaperPlaneTilt aria-hidden="true" weight="fill" />
        </button>
      </form>
    </aside>
  );
}
