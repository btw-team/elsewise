import re
import unicodedata
from collections.abc import Mapping
from typing import Literal

from elsewise.settings.config import GlobalSettings

SpeakerRole = Literal["self", "other", "unknown"]


def normalize_speaker_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def own_speaker_names(settings: GlobalSettings) -> dict[str, str]:
    return {
        "google_meet": settings.google_meet_own_name,
        "microsoft_teams": settings.microsoft_teams_own_name,
        "zoom": settings.zoom_own_name,
    }


def classify_speaker(
    speaker: str | None,
    platform: str | None,
    configured_names: Mapping[str, str],
) -> SpeakerRole:
    if not speaker or not platform:
        return "unknown"
    own_name = normalize_speaker_name(configured_names.get(platform, ""))
    if not own_name:
        return "unknown"
    return "self" if normalize_speaker_name(speaker) == own_name else "other"
