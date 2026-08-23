import os
import shutil
import subprocess
import sys
from collections.abc import Callable


class NativeNotifier:
    def __init__(self, fallback: Callable[[str, str], None]) -> None:
        self.fallback = fallback
        self._sent: set[str] = set()

    def send_once(self, event_id: str, title: str, message: str) -> bool:
        if event_id in self._sent:
            return True
        self._sent.add(event_id)
        if self._send_native(title, message):
            return True
        self.fallback(title, message)
        return False

    @staticmethod
    def _send_native(title: str, message: str) -> bool:
        try:
            if sys.platform.startswith("linux"):
                executable = shutil.which("notify-send")
                if executable is None:
                    return False
                subprocess.Popen(
                    [executable, "--app-name=Elsewise", title, message],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                return True
            if sys.platform == "darwin":
                executable = shutil.which("osascript")
                if executable is None:
                    return False
                script = (
                    "on run argv\n"
                    "display notification (item 2 of argv) with title (item 1 of argv)\n"
                    "end run"
                )
                subprocess.Popen(
                    [executable, "-e", script, "--", title, message],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                return True
            if os.name == "nt":
                executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
                if executable is None:
                    return False
                script = (
                    "$title=$args[0];$message=$args[1];"
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$n=New-Object System.Windows.Forms.NotifyIcon;"
                    "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                    "$n.BalloonTipTitle=$title;$n.BalloonTipText=$message;"
                    "$n.Visible=$true;$n.ShowBalloonTip(5000);Start-Sleep -Seconds 6;$n.Dispose()"
                )
                subprocess.Popen(
                    [
                        executable,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        script,
                        title,
                        message,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return True
        except OSError:
            return False
        return False
