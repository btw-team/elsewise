import { ApiError } from "./client";
import type { TranslationKey } from "../i18n/catalogs";
import errorCatalog from "../../../shared/api-errors.json";

export const API_ERROR_CODES = errorCatalog.map((entry) => entry.code);
const ERROR_KEYS = Object.fromEntries(
  errorCatalog.map((entry) => [entry.code, entry.translation_key]),
) as Record<string, TranslationKey>;

export function apiErrorMessage(
  error: unknown,
  t: (key: TranslationKey) => string,
): string {
  if (!(error instanceof ApiError))
    return error instanceof Error ? error.message : t("requestFailed");
  const key = ERROR_KEYS[error.code];
  return key ? t(key) : `${t("requestFailed")} (${error.code})`;
}
