import hashlib
import zipfile
from pathlib import Path

import pytest
from elsewise.speech.models import (
    ModelArtifact,
    ModelInstaller,
    ModelInstallError,
    ModelManifest,
    ModelRegistry,
)
from elsewise.speech.profiles import HardwareCapabilities, SpeechProfile, resolve_profile


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_sha256(path: str, value: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(path.encode())
    digest.update(b"\0")
    digest.update(value)
    digest.update(b"\0")
    return digest.hexdigest()


def artifact_for(archive: Path, data: bytes, *, tier: str = "conservative") -> ModelArtifact:
    return ModelArtifact.model_validate(
        {
            "id": f"fake-{tier}",
            "version": "1",
            "kind": "asr",
            "backend": "fake",
            "runtime_version": "1",
            "urls": ["https://models.example.invalid/fake.zip"],
            "archive_sha256": sha256(archive.read_bytes()),
            "content_sha256": content_sha256("model.bin", data),
            "files": [{"path": "model.bin", "size": len(data), "sha256": sha256(data)}],
            "license": "Apache-2.0",
            "source": "https://example.invalid/model-card",
            "languages": ["en", "ru"],
            "quality_tier": tier,
            "providers": ["cpu"],
            "ram_mb": 256,
            "vram_mb": 0,
            "disk_mb": 1,
            "streaming": True,
        }
    )


def test_model_install_is_verified_content_addressed_and_idempotent(tmp_path: Path) -> None:
    data = b"deterministic fake model"
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model.bin", data)
    artifact = artifact_for(archive, data)
    manifest = ModelManifest(version=1, artifacts=(artifact,))
    assert manifest.artifacts[0].languages == frozenset({"en", "ru"})

    installer = ModelInstaller(tmp_path / "models")
    installed = installer.install_from_archive(artifact, archive)

    assert installed.name == artifact.content_sha256
    assert (installed / "model.bin").read_bytes() == data
    assert installer.install_from_archive(artifact, archive) == installed


def test_model_install_rejects_archive_traversal_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.bin", b"unsafe")
    artifact = artifact_for(archive, b"unsafe")

    with pytest.raises(ModelInstallError, match="unsafe path"):
        ModelInstaller(tmp_path / "models").install_from_archive(artifact, archive)
    assert not (tmp_path / "outside.bin").exists()


def test_profile_resolver_reports_requested_and_effective_policy(tmp_path: Path) -> None:
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model.bin", b"model")
    conservative = artifact_for(archive, b"model")
    resolution = resolve_profile(
        SpeechProfile.BEST,
        language="en",
        installed_artifacts=(conservative,),
        hardware=HardwareCapabilities(ram_mb=512),
    )
    assert resolution.requested is SpeechProfile.BEST
    assert resolution.effective is SpeechProfile.CONSERVATIVE
    assert resolution.reason == "safety_downgrade"

    unavailable = resolve_profile(
        SpeechProfile.AUTO,
        language="fr",
        installed_artifacts=(conservative,),
        hardware=HardwareCapabilities(ram_mb=512),
    )
    assert unavailable.effective is None
    assert unavailable.reason == "model_missing_or_incompatible"


def test_model_registry_reports_missing_installed_and_corrupt(tmp_path: Path) -> None:
    data = b"model"
    archive = tmp_path / "model.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model.bin", data)
    artifact = artifact_for(archive, data)
    registry = ModelRegistry(ModelManifest(version=7, artifacts=(artifact,)), tmp_path / "models")

    assert registry.inventory()[0].status == "missing"
    installed = registry.install_from_archive(artifact.id, artifact.version, archive)
    assert registry.inventory()[0].status == "installed"

    (installed / "model.bin").write_bytes(b"broken")
    item = registry.inventory()[0]
    assert item.status == "corrupt"
    assert item.error_code == "model_corrupt"
