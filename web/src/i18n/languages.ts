export const SUPPORTED_LANGUAGES = [
  "en",
  "ru",
  "fr",
  "es",
  "de",
  "pt-BR",
] as const;

export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: "English",
  ru: "Русский",
  fr: "Français",
  es: "Español",
  de: "Deutsch",
  "pt-BR": "Português (Brasil)",
};

export function isSupportedLanguage(value: string): value is SupportedLanguage {
  return SUPPORTED_LANGUAGES.includes(value as SupportedLanguage);
}
