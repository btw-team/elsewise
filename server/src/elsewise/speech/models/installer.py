import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from elsewise.speech.models.manifest import ModelArtifact


class ModelInstallError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(root: Path, relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with (root / relative).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_member_path(value: str) -> str:
    normalized = value.removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or "\\" in normalized:
        raise ModelInstallError("model archive contains an unsafe path")
    return normalized


class ModelInstaller:
    def __init__(self, model_root: Path) -> None:
        self.model_root = model_root

    def install_from_archive(self, artifact: ModelArtifact, archive: Path) -> Path:
        if not archive.is_file() or _sha256(archive) != artifact.archive_sha256:
            raise ModelInstallError("model archive checksum mismatch")
        self.model_root.mkdir(parents=True, exist_ok=True)
        destination = self.model_root / artifact.content_sha256
        if destination.is_dir():
            self.verify(artifact, destination)
            return destination
        temporary = Path(tempfile.mkdtemp(prefix=f".{artifact.id}-", dir=self.model_root))
        try:
            if zipfile.is_zipfile(archive):
                self._extract_zip(archive, temporary, artifact)
            elif tarfile.is_tarfile(archive):
                self._extract_tar(archive, temporary, artifact)
            else:
                raise ModelInstallError("unsupported model archive format")
            self.verify(artifact, temporary)
            try:
                os.replace(temporary, destination)
            except OSError:
                if destination.is_dir():
                    self.verify(artifact, destination)
                else:
                    raise
            return destination
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def verify(artifact: ModelArtifact, root: Path) -> None:
        expected = {item.path: item for item in artifact.files}
        actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        if actual != set(expected):
            raise ModelInstallError("model files do not match the manifest")
        for relative, definition in expected.items():
            path = root / relative
            if path.is_symlink() or path.stat().st_size != definition.size:
                raise ModelInstallError("model file metadata does not match the manifest")
            if _sha256(path) != definition.sha256:
                raise ModelInstallError("model file checksum mismatch")
        if _content_sha256(root, list(expected)) != artifact.content_sha256:
            raise ModelInstallError("model content checksum mismatch")

    @staticmethod
    def _extract_zip(archive: Path, destination: Path, artifact: ModelArtifact) -> None:
        expected = {item.path: item for item in artifact.files}
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                relative = _safe_member_path(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ModelInstallError("model archive symlinks are forbidden")
                target = destination / relative
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                definition = expected.get(relative)
                if definition is None or member.file_size != definition.size:
                    raise ModelInstallError("model archive files do not match the manifest")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

    @staticmethod
    def _extract_tar(archive: Path, destination: Path, artifact: ModelArtifact) -> None:
        expected = {item.path: item for item in artifact.files}
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                relative = _safe_member_path(member.name)
                if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ModelInstallError("unsupported model archive member")
                target = destination / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                definition = expected.get(relative)
                if definition is None or member.size != definition.size:
                    raise ModelInstallError("model archive files do not match the manifest")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ModelInstallError("model archive member cannot be read")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
