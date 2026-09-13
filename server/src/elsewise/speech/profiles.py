from dataclasses import dataclass
from enum import StrEnum

from elsewise.speech.models.manifest import ModelArtifact


class SpeechProfile(StrEnum):
    AUTO = "auto"
    CONSERVATIVE = "conservative"
    STANDARD = "standard"
    BEST = "best"


@dataclass(frozen=True, slots=True)
class HardwareCapabilities:
    ram_mb: int
    vram_mb: int = 0
    providers: frozenset[str] = frozenset({"cpu"})


@dataclass(frozen=True, slots=True)
class ProfileResolution:
    requested: SpeechProfile
    effective: SpeechProfile | None
    artifact: ModelArtifact | None
    provider: str | None
    reason: str


_QUALITY = {
    "conservative": 0,
    "standard": 1,
    "best": 2,
}


def resolve_profile(
    requested: SpeechProfile,
    *,
    language: str,
    installed_artifacts: tuple[ModelArtifact, ...],
    hardware: HardwareCapabilities,
) -> ProfileResolution:
    candidates = [
        artifact
        for artifact in installed_artifacts
        if artifact.kind == "asr"
        and language in artifact.languages
        and artifact.ram_mb <= hardware.ram_mb
        and artifact.vram_mb <= hardware.vram_mb
        and artifact.providers.intersection(hardware.providers)
    ]
    if requested is not SpeechProfile.AUTO:
        maximum = _QUALITY[requested.value]
        candidates = [
            artifact for artifact in candidates if _QUALITY[artifact.quality_tier] <= maximum
        ]
    if not candidates:
        return ProfileResolution(
            requested=requested,
            effective=None,
            artifact=None,
            provider=None,
            reason="model_missing_or_incompatible",
        )
    selected = max(candidates, key=lambda artifact: _QUALITY[artifact.quality_tier])
    provider = sorted(selected.providers.intersection(hardware.providers))[0]
    effective = SpeechProfile(selected.quality_tier)
    reason = "requested" if requested in {SpeechProfile.AUTO, effective} else "safety_downgrade"
    return ProfileResolution(requested, effective, selected, provider, reason)
