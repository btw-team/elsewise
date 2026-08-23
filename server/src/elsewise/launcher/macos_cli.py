import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MacCliStatus = Literal[
    "installed",
    "removed",
    "not_installed",
    "move_to_applications",
    "source_missing",
    "destination_conflict",
    "failed",
]


@dataclass(frozen=True, slots=True)
class MacCliResult:
    status: MacCliStatus
    destination: Path


def app_bundle_for(executable: Path) -> Path | None:
    for parent in (executable, *executable.parents):
        if parent.suffix == ".app":
            return parent
    return None


class MacCliManager:
    def __init__(
        self,
        executable: Path | None = None,
        destination: Path = Path("/usr/local/bin/elsewise"),
    ) -> None:
        self.executable = (executable or Path(sys.executable)).resolve()
        self.destination = destination

    def install(self) -> MacCliResult:
        bundle = app_bundle_for(self.executable)
        if bundle is None:
            return MacCliResult("source_missing", self.destination)
        if bundle.is_relative_to("/Volumes"):
            return MacCliResult("move_to_applications", self.destination)
        source = bundle / "Contents" / "MacOS" / "elsewise"
        if not source.is_file():
            return MacCliResult("source_missing", self.destination)
        if os.path.lexists(self.destination) and not self._owned_symlink():
            return MacCliResult("destination_conflict", self.destination)
        return self._mutate("install", source)

    def remove(self) -> MacCliResult:
        if not os.path.lexists(self.destination):
            return MacCliResult("not_installed", self.destination)
        if not self._owned_symlink():
            return MacCliResult("destination_conflict", self.destination)
        return self._mutate("remove", None)

    def _owned_symlink(self) -> bool:
        if not self.destination.is_symlink():
            return False
        try:
            raw = Path(os.readlink(self.destination))
        except OSError:
            return False
        target = raw if raw.is_absolute() else self.destination.parent / raw
        parts = target.parts
        return (
            target.name == "elsewise"
            and "Contents" in parts
            and "MacOS" in parts
            and any(part == "Elsewise.app" for part in parts)
        )

    def _mutate(self, operation: Literal["install", "remove"], source: Path | None) -> MacCliResult:
        try:
            if os.access(self.destination.parent, os.W_OK):
                if os.path.lexists(self.destination):
                    if not self._owned_symlink():
                        return MacCliResult("destination_conflict", self.destination)
                    self.destination.unlink()
                if operation == "install" and source is not None:
                    self.destination.symlink_to(source)
                status: MacCliStatus = "installed" if operation == "install" else "removed"
                return MacCliResult(status, self.destination)

            destination = shlex.quote(str(self.destination))
            validate = (
                f"if [ -e {destination} ] || [ -L {destination} ]; then "
                f"test -L {destination} || exit 23; "
                f'case "$(readlink {destination})" in '
                f"*Elsewise.app/Contents/MacOS/elsewise) ;; *) exit 24 ;; esac; "
                f"rm -f {destination}; fi"
            )
            if operation == "install" and source is not None:
                command = (
                    f"mkdir -p {shlex.quote(str(self.destination.parent))} && "
                    f"{validate} && ln -s {shlex.quote(str(source))} {destination}"
                )
            else:
                command = validate
            script = f"do shell script {self._apple_quote(command)} with administrator privileges"
            subprocess.run(["osascript", "-e", script], check=True, timeout=60)
            status = "installed" if operation == "install" else "removed"
            return MacCliResult(status, self.destination)
        except (OSError, subprocess.SubprocessError):
            return MacCliResult("failed", self.destination)

    @staticmethod
    def _apple_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
