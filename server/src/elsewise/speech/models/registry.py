from dataclasses import dataclass
from pathlib import Path

from elsewise.speech.models.installer import ModelInstaller, ModelInstallError
from elsewise.speech.models.manifest import ModelArtifact, ModelManifest


@dataclass(frozen=True, slots=True)
class ModelInventoryItem:
    artifact: ModelArtifact
    status: str
    error_code: str | None = None

    def payload(self) -> dict[str, object]:
        artifact = self.artifact
        return {
            "id": artifact.id,
            "version": artifact.version,
            "kind": artifact.kind,
            "backend": artifact.backend,
            "quality_tier": artifact.quality_tier,
            "languages": sorted(artifact.languages),
            "providers": sorted(artifact.providers),
            "ram_mb": artifact.ram_mb,
            "vram_mb": artifact.vram_mb,
            "disk_mb": artifact.disk_mb,
            "streaming": artifact.streaming,
            "license": artifact.license,
            "source": artifact.source,
            "status": self.status,
            "error_code": self.error_code,
        }


class ModelRegistry:
    def __init__(self, manifest: ModelManifest, model_root: Path) -> None:
        self.manifest = manifest
        self.model_root = model_root
        self.installer = ModelInstaller(model_root)

    @classmethod
    def empty(cls, model_root: Path) -> "ModelRegistry":
        # Production candidates stay absent until their artifact, license and
        # language metadata pass P2-E05. Tests may inject an explicit manifest.
        return cls(ModelManifest(version=1, artifacts=()), model_root)

    def inventory(self) -> tuple[ModelInventoryItem, ...]:
        items: list[ModelInventoryItem] = []
        for artifact in self.manifest.artifacts:
            root = self.model_root / artifact.content_sha256
            if not root.is_dir():
                items.append(ModelInventoryItem(artifact, "missing", "model_missing"))
                continue
            try:
                self.installer.verify(artifact, root)
            except (ModelInstallError, OSError):
                items.append(ModelInventoryItem(artifact, "corrupt", "model_corrupt"))
            else:
                items.append(ModelInventoryItem(artifact, "installed"))
        return tuple(items)

    def installed_artifacts(self) -> tuple[ModelArtifact, ...]:
        return tuple(item.artifact for item in self.inventory() if item.status == "installed")

    def require(self, artifact_id: str, version: str) -> ModelArtifact:
        artifact = next(
            (
                item
                for item in self.manifest.artifacts
                if item.id == artifact_id and item.version == version
            ),
            None,
        )
        if artifact is None:
            raise KeyError((artifact_id, version))
        return artifact

    def install_from_archive(self, artifact_id: str, version: str, archive: Path) -> Path:
        return self.installer.install_from_archive(self.require(artifact_id, version), archive)
