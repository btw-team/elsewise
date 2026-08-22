import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extension_archives_are_deterministic_and_contain_a_manifest(tmp_path: Path) -> None:
    module = load_script("build-extension-archives.py")
    source = tmp_path / "extension" / "dist" / "chrome"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text('{"name":"Elsewise"}', encoding="utf-8")
    (source / "background.js").write_text("export {};", encoding="utf-8")
    module.__dict__["OUTPUT"] = tmp_path / "packages"
    module.__dict__["ROOT"] = tmp_path
    (tmp_path / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")

    first = module.archive("chrome", module.product_version())
    first_digest = hashlib.sha256(first.read_bytes()).digest()
    second = module.archive("chrome", module.product_version())

    assert first.name == "Elsewise-extension-chrome-1.2.3.zip"
    assert hashlib.sha256(second.read_bytes()).digest() == first_digest
    with zipfile.ZipFile(second) as bundle:
        assert bundle.namelist() == ["background.js", "manifest.json"]
        assert json.loads(bundle.read("manifest.json")) == {"name": "Elsewise"}


def test_release_inventory_and_checksums_are_exact(tmp_path: Path) -> None:
    module = load_script("verify-release-assets.py")
    for name in module.expected_names("1.2.3"):
        (tmp_path / name).write_bytes(name.encode())

    paths = module.validate(tmp_path, "1.2.3")
    checksums = module.checksum_lines(paths)

    assert len(paths) == 11
    assert checksums.count("\n") == 11
    assert "SHA256SUMS" not in checksums
    assert all(path.name in checksums for path in paths)

    (tmp_path / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="unexpected.bin"):
        module.validate(tmp_path, "1.2.3")


def test_nfpm_file_sources_are_repository_relative() -> None:
    source = (ROOT / "packaging/linux/nfpm.yaml").read_text(encoding="utf-8")
    file_sources = (
        Path(value)
        for value in re.findall(r"^\s*- src: (.+)$", source, flags=re.MULTILINE)
        if not value.startswith("/opt/")
    )

    for source in file_sources:
        assert not source.is_absolute()
        assert ".." not in source.parts


def test_documentation_checker_validates_files_images_and_anchors(tmp_path: Path) -> None:
    module = load_script("check-docs.py")
    docs = tmp_path / "docs"
    assets = docs / "assets"
    assets.mkdir(parents=True)
    (assets / "screen.png").write_bytes(b"png")
    (tmp_path / "README.md").write_text(
        "# Project\n\n[Guide](docs/guide.md#first-run)\n\n![Screen](docs/assets/screen.png)\n",
        encoding="utf-8",
    )
    guide = docs / "guide.md"
    guide.write_text("# Guide\n\n## First run\n", encoding="utf-8")

    assert module.check(tmp_path) == []
    guide.write_text("# Guide\n", encoding="utf-8")
    assert module.check(tmp_path) == ["README.md: missing anchor: docs/guide.md#first-run"]
