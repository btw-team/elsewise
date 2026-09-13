import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ArtifactKind = Literal["vad", "asr", "finalizer", "speaker_embedding"]
QualityTier = Literal["conservative", "standard", "best"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ModelArtifactFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    sha256: str

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("artifact file path must stay inside the model root")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be lowercase hexadecimal")
        return value


class ModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9._-]+$")
    version: str = Field(min_length=1, max_length=64)
    kind: ArtifactKind
    backend: str = Field(min_length=1, max_length=128)
    runtime_version: str = Field(min_length=1, max_length=64)
    urls: tuple[str, ...] = Field(min_length=1, max_length=4)
    archive_sha256: str
    content_sha256: str
    files: tuple[ModelArtifactFile, ...] = Field(min_length=1, max_length=128)
    license: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=512)
    languages: frozenset[str] = Field(min_length=1, max_length=64)
    quality_tier: QualityTier
    providers: frozenset[str] = Field(min_length=1, max_length=16)
    ram_mb: int = Field(ge=1)
    vram_mb: int = Field(ge=0)
    disk_mb: int = Field(ge=1)
    streaming: bool

    @field_validator("archive_sha256", "content_sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be lowercase hexadecimal")
        return value

    @model_validator(mode="after")
    def unique_paths(self) -> "ModelArtifact":
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact file paths must be unique")
        return self


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    artifacts: tuple[ModelArtifact, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def unique_artifacts(self) -> "ModelManifest":
        keys = [(item.id, item.version) for item in self.artifacts]
        if len(keys) != len(set(keys)):
            raise ValueError("manifest artifact ids and versions must be unique")
        return self
