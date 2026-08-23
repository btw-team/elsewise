from typing import Literal

type SupportedLanguage = Literal["en", "ru", "fr", "es", "de", "pt-BR"]
SUPPORTED_LANGUAGES: tuple[SupportedLanguage, ...] = (
    "en",
    "ru",
    "fr",
    "es",
    "de",
    "pt-BR",
)
SUPPORTED_LANGUAGE_SET = frozenset(SUPPORTED_LANGUAGES)
LANGUAGE_DISPLAY_NAMES: dict[SupportedLanguage, str] = {
    "en": "English",
    "ru": "Русский",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "pt-BR": "Português (Brasil)",
}
