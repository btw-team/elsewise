import type { TranslationKey } from "./i18n/catalogs";
import type { AgentHealth } from "./types";

type Translator = (key: TranslationKey) => string;

export type AgentHealthStatus = AgentHealth["status"];

export function agentHealthStatus(
  health: AgentHealth | null,
): AgentHealthStatus {
  return health?.status ?? "unavailable";
}

export function agentHealthLabel(
  health: AgentHealth | null,
  t: Translator,
): string {
  switch (agentHealthStatus(health)) {
    case "stopped":
      return t("codexStopped");
    case "starting":
      return t("codexStarting");
    case "ready":
      return t("ready");
    case "error":
      return t("codexError");
    case "unavailable":
      return t("unavailable");
  }
}
