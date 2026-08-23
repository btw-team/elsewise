import contextlib
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from collections.abc import Callable
from typing import Any, cast

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image

from elsewise import __version__
from elsewise.external_links import load_external_links
from elsewise.launcher.about import AboutFrame
from elsewise.launcher.assets import asset_path
from elsewise.launcher.details import DetailsFrame
from elsewise.launcher.i18n import Translator
from elsewise.launcher.log_viewer import LogTailWorker
from elsewise.launcher.macos_cli import MacCliManager
from elsewise.launcher.monitor import LifecycleActionRunner, MonitorEvent, RuntimeMonitor
from elsewise.launcher.notifications import NativeNotifier
from elsewise.launcher.overview import OverviewFrame
from elsewise.launcher.settings_view import SettingsFrame
from elsewise.launcher.single_instance import LauncherSingleInstance
from elsewise.launcher.theme import TOKENS, UiTheme, current_theme, font_family, set_theme
from elsewise.launcher.updates import UpdateChecker, UpdateResult
from elsewise.runtime.controller import DaemonController, ServerStatus
from elsewise.runtime.logging import configure_launcher_logging
from elsewise.runtime.signals import shutdown_signal_handlers
from elsewise.settings.config import SettingsStore
from elsewise.settings.languages import SUPPORTED_LANGUAGE_SET
from elsewise.settings.launcher import LauncherSettingsStore
from elsewise.settings.pairing import PairingManager
from elsewise.settings.paths import AppPaths

_LOGGER = logging.getLogger("elsewise.launcher")
_MAX_EVENTS_PER_TICK = 100
_DEFAULT_WINDOW_GEOMETRY = "1024x640"
_MINIMUM_WINDOW_SIZE = (1024, 640)
_TAB_KEYS = ("overview", "details", "settings", "about")


class LauncherApplication(ctk.CTk):  # type: ignore[misc]
    def __init__(
        self,
        *,
        paths: AppPaths,
        instance: LauncherSingleInstance,
        language: str,
        theme: UiTheme,
    ) -> None:
        set_theme(theme)
        ctk.set_appearance_mode(theme)
        super().__init__(fg_color=TOKENS.canvas)
        self.paths = paths
        self.instance = instance
        self.translator = Translator(language)
        self.ui_theme: UiTheme = theme
        self.links = load_external_links()
        self.activation_queue: queue.SimpleQueue[bool] = queue.SimpleQueue()
        self.event_queue: queue.SimpleQueue[MonitorEvent] = queue.SimpleQueue()
        self.family = font_family(self)
        self.controller = DaemonController(paths)
        self.monitor = RuntimeMonitor(self.controller, self.event_queue.put)
        self.log_worker = LogTailWorker(
            paths.diagnostics / "server.log",
            lambda lines, reset: self.event_queue.put(
                {"kind": "log", "lines": lines, "reset": reset}
            ),
        )
        self.notifier = NativeNotifier(
            lambda title, message: self.event_queue.put(
                {"kind": "notification", "title": title, "message": message}
            )
        )
        self.action_runner = LifecycleActionRunner(
            lambda status: self.event_queue.put({"kind": "action", "status": status})
        )
        self.launcher_settings_store = LauncherSettingsStore(self.paths.config / "launcher.json")
        self.launcher_settings_store.load()
        self.pairing_manager = PairingManager(self.paths.config / "pairing.json")
        self.pairing_manager.ensure()
        self.update_checker = UpdateChecker(paths.cache / "updates.json", __version__)
        self.update_result = self.update_checker.cached_result()
        self.update_lock = threading.Lock()
        self.runtime_payload: dict[str, Any] = {}
        self.current_status = ServerStatus("stopped", url=self.controller.url)
        self.pending_action = ""
        self.restart_waiting = False
        self.restart_cancel = threading.Event()
        self.closing = False
        self.closed = False
        self.notification_frame: ctk.CTkFrame | None = None
        self.title(f"{self.translator.text('app_title')} {__version__}")
        self.geometry(_DEFAULT_WINDOW_GEOMETRY)
        self.minsize(*_MINIMUM_WINDOW_SIZE)
        self.protocol("WM_DELETE_WINDOW", self.close_launcher)
        self._tabs: dict[str, ctk.CTkFrame] = {}
        self._tab_buttons: dict[str, ctk.CTkButton] = {}
        self._tab_build_pending: set[str] = set()
        self._build_generation = 0
        self._active_tab = "overview"
        self._logo_image: ctk.CTkImage | None = None
        self._content: ctk.CTkFrame
        self._loading_frame: ctk.CTkFrame
        self._loading_title: ctk.CTkLabel
        self._loading_message: ctk.CTkLabel
        self.details: DetailsFrame | None = None
        self.settings_frame: SettingsFrame | None = None
        self.about_frame: AboutFrame | None = None
        self._deferred_log_lines: deque[str] = deque(maxlen=1000)
        self._build()
        self.show_tab("overview")
        self.after(0, self._show_recovery_notice)
        self.after(100, self._drain_activation_queue)
        self.after(100, self._drain_event_queue)

    def _build(self) -> None:
        self._build_generation += 1
        self._tabs.clear()
        self._tab_buttons.clear()
        self._tab_build_pending.clear()
        self.details = None
        self.settings_frame = None
        self.about_frame = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        navigation = ctk.CTkFrame(
            self,
            width=210,
            corner_radius=0,
            fg_color=TOKENS.panel,
            border_width=1,
            border_color=TOKENS.border,
        )
        navigation.grid(row=0, column=0, sticky="nsew")
        navigation.grid_propagate(False)
        navigation.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(navigation, fg_color="transparent")
        brand.grid(row=0, column=0, padx=20, pady=(22, 26), sticky="ew")
        logo_dark = asset_path("elsewise-logo-dark.png")
        logo_light = asset_path("elsewise-logo-light.png")
        if logo_dark is not None and logo_light is not None:
            with Image.open(logo_dark) as source:
                prepared_dark = source.convert("RGBA")
            with Image.open(logo_light) as source:
                prepared_light = source.convert("RGBA")
            self._logo_image = ctk.CTkImage(
                light_image=prepared_light,
                dark_image=prepared_dark,
                size=(166, 26),
            )
            label = ctk.CTkLabel(brand, text="", image=self._logo_image)
            label.grid(row=0, column=0, sticky="w")

        for row, key in enumerate(_TAB_KEYS, start=1):
            button = ctk.CTkButton(
                navigation,
                text=self.translator.text(key),
                height=38,
                corner_radius=5,
                anchor="w",
                fg_color="transparent",
                hover_color=TOKENS.surface_active,
                text_color=TOKENS.text_soft,
                font=ctk.CTkFont(family=self.family, size=14),
                command=lambda selected=key: self.show_tab(selected),
            )
            button.grid(row=row, column=0, padx=14, pady=4, sticky="ew")
            self._tab_buttons[key] = button

        self._content = ctk.CTkFrame(self, corner_radius=0, fg_color=TOKENS.canvas)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._loading_frame = ctk.CTkFrame(
            self._content,
            fg_color=TOKENS.canvas,
            corner_radius=0,
        )
        self._loading_frame.grid(row=0, column=0, sticky="nsew")
        self._loading_title = ctk.CTkLabel(
            self._loading_frame,
            text="",
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=26, weight="normal"),
        )
        self._loading_title.pack(anchor="w", padx=30, pady=(24, 8))
        self._loading_message = ctk.CTkLabel(
            self._loading_frame,
            text=self.translator.text("placeholder"),
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=self.family, size=14),
        )
        self._loading_message.pack(anchor="w", padx=30)
        self._loading_frame.grid_remove()

        self.overview = OverviewFrame(
            self._content,
            translator=self.translator,
            family=self.family,
            links=self.links,
            on_start=lambda: self._run_action("start", self.controller.start),
            on_stop=lambda: self._run_action("stop", self.controller.stop),
            on_restart=self._request_restart,
            on_open=self._open_web_gui,
            on_copy=self._copy_address,
            on_link=self._open_link,
            on_check_update=lambda: self._request_update_check(manual=True),
            on_open_release=self._open_release,
        )
        self.overview.grid(row=0, column=0, sticky="nsew")
        self.overview.grid_remove()
        self.overview.set_update(self.update_result.model_dump(mode="json"))
        self._tabs["overview"] = self.overview
        self._install_scroll_bindings()

    def _create_lazy_tab(self, key: str) -> ctk.CTkFrame:
        if key == "details":
            frame = DetailsFrame(
                self._content,
                translator=self.translator,
                family=self.family,
                on_pause=self.log_worker.set_paused,
                on_refresh=self.log_worker.refresh,
                on_copy=self._copy_text,
                on_open_folder=self._open_log_folder,
            )
            self.details = frame
            if self._deferred_log_lines:
                frame.append_lines(list(self._deferred_log_lines), replace=True)
                self._deferred_log_lines.clear()
            self.log_worker.refresh()
        elif key == "settings":
            frame = SettingsFrame(
                self._content,
                translator=self.translator,
                family=self.family,
                store=self.launcher_settings_store,
                pairing=self.pairing_manager,
                language=self.translator.language,
                theme=self.ui_theme,
                server_running=lambda: self.current_status.state == "running",
                on_language=self._change_language,
                on_theme=self._change_theme,
                on_install_cli=self._install_cli if sys.platform == "darwin" else None,
                on_remove_cli=self._remove_cli if sys.platform == "darwin" else None,
            )
            self.settings_frame = frame
        elif key == "about":
            frame = AboutFrame(
                self._content,
                translator=self.translator,
                family=self.family,
                links=self.links,
                on_link=self._open_link,
            )
            self.about_frame = frame
        else:
            raise ValueError(f"Unknown lazy launcher tab: {key}")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_remove()
        self._tabs[key] = frame
        self._install_scroll_bindings()
        return frame

    def _install_scroll_bindings(self) -> None:
        # CTkScrollableFrame installs one global binding per instance. On X11 that
        # can update the canvas position without scheduling a visible repaint.
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")
        self.bind_all("<MouseWheel>", self._scroll_active_tab, add="+")
        if sys.platform.startswith("linux"):
            self.bind_all("<Button-4>", self._scroll_active_tab, add="+")
            self.bind_all("<Button-5>", self._scroll_active_tab, add="+")

    def _scroll_active_tab(self, event: Any) -> str | None:
        frame = self._tabs.get(self._active_tab)
        canvas = getattr(frame, "_parent_canvas", None)
        contains_widget = getattr(frame, "check_if_master_is_canvas", None)
        if canvas is None or not callable(contains_widget) or not contains_widget(event.widget):
            return None

        button_number = getattr(event, "num", None)
        delta = int(getattr(event, "delta", 0) or 0)
        if button_number == 4:
            units = -3
        elif button_number == 5:
            units = 3
        elif delta:
            if sys.platform == "darwin":
                units = -delta
            else:
                units = -3 if delta > 0 else 3
        else:
            return None

        canvas.yview_scroll(units, "units")
        canvas.after_idle(canvas.update_idletasks)
        return "break"

    def start_services(self) -> None:
        self.monitor.start()
        self.log_worker.start()
        launcher_settings = self.launcher_settings_store.load()
        if launcher_settings.start_server_on_launch and self.controller.status().state == "stopped":
            self._run_action("start", self.controller.start)
        if launcher_settings.check_updates_on_launch:
            self._request_update_check(manual=False)

    def show_tab(self, key: str) -> None:
        if key not in _TAB_KEYS:
            return
        self._active_tab = key
        for name, button in self._tab_buttons.items():
            selected = name == key
            light_selection = selected and current_theme() == "light"
            button.configure(
                fg_color=(
                    TOKENS.accent
                    if light_selection
                    else TOKENS.surface_active
                    if selected
                    else "transparent"
                ),
                text_color=(
                    TOKENS.primary_text
                    if light_selection
                    else TOKENS.accent_strong
                    if selected
                    else TOKENS.text_soft
                ),
                hover_color=TOKENS.accent_strong if light_selection else TOKENS.surface_active,
                border_width=1 if selected else 0,
                border_color=TOKENS.border_strong if light_selection else TOKENS.accent_deep,
            )
        frame = self._tabs.get(key)
        if frame is not None:
            self._show_frame(frame)
            return

        for existing in self._tabs.values():
            existing.grid_remove()
        self._loading_title.configure(text=self.translator.text(key))
        self._loading_message.configure(text=self.translator.text("placeholder"))
        self._loading_frame.grid()
        if key in self._tab_build_pending:
            return
        self._tab_build_pending.add(key)
        generation = self._build_generation
        self.after(10, lambda: self._finish_lazy_tab(key, generation))

    def _show_frame(self, selected: ctk.CTkFrame) -> None:
        self._loading_frame.grid_remove()
        for frame in self._tabs.values():
            if frame is selected:
                frame.grid()
            else:
                frame.grid_remove()

    def _finish_lazy_tab(self, key: str, generation: int) -> None:
        if self.closed or generation != self._build_generation:
            return
        if self._active_tab != key:
            self._tab_build_pending.discard(key)
            return
        try:
            frame = self._create_lazy_tab(key)
        except Exception:
            self._tab_build_pending.discard(key)
            _LOGGER.exception("Unable to build launcher tab %s", key)
            return
        self._tab_build_pending.discard(key)
        if self._active_tab == key:
            self._show_frame(frame)

    def request_activation(self) -> None:
        self.activation_queue.put(True)

    def _drain_activation_queue(self) -> None:
        activated = False
        while not self.activation_queue.empty():
            self.activation_queue.get_nowait()
            activated = True
        if activated:
            self.deiconify()
            self.lift()
            with contextlib.suppress(Exception):
                self.focus_force()
        self.after(100, self._drain_activation_queue)

    def _drain_event_queue(self) -> None:
        processed = 0
        while processed < _MAX_EVENTS_PER_TICK:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            kind = event.get("kind")
            if kind == "runtime":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    self.runtime_payload = payload
                    self.overview.set_runtime(payload)
                    shared = payload.get("settings")
                    language = shared.get("ui_language") if isinstance(shared, dict) else None
                    theme = shared.get("ui_theme") if isinstance(shared, dict) else None
                    next_language = (
                        language
                        if isinstance(language, str) and language in SUPPORTED_LANGUAGE_SET
                        else self.translator.language
                    )
                    next_theme: UiTheme = "light" if theme == "light" else "dark"
                    if next_language != self.translator.language or next_theme != self.ui_theme:
                        self._apply_interface_settings(next_language, next_theme)
            elif kind == "log":
                lines = event.get("lines")
                if isinstance(lines, list) and all(isinstance(line, str) for line in lines):
                    typed_lines = cast(list[str], lines)
                    if self.details is not None:
                        self.details.append_lines(
                            typed_lines,
                            replace=bool(event.get("reset")),
                        )
                    else:
                        if event.get("reset"):
                            self._deferred_log_lines.clear()
                        self._deferred_log_lines.extend(typed_lines)
            elif kind == "notification":
                self._show_notification(
                    str(event.get("title", "Elsewise")),
                    str(event.get("message", "")),
                )
            elif kind == "update":
                result = event.get("result")
                if isinstance(result, UpdateResult):
                    self.update_result = result
                    self.overview.set_update(result.model_dump(mode="json"))
                    if result.update_available:
                        self.notifier.send_once(
                            f"update-{result.latest_version}",
                            self.translator.text("update_available_title"),
                            self.translator.text("update_available_message").format(
                                version=result.latest_version or ""
                            ),
                        )
            elif kind in {"lifecycle", "action"}:
                status = event.get("status")
                if isinstance(status, ServerStatus):
                    previous = self.current_status
                    self.current_status = status
                    self.overview.set_lifecycle(status, busy=False)
                    if (
                        kind == "lifecycle"
                        and previous.state == "running"
                        and status.state in {"stopped", "error"}
                        and not self.pending_action
                        and not self.closing
                    ):
                        self.notifier.send_once(
                            f"server-crash-{previous.pid or 'unknown'}",
                            self.translator.text("server_crashed_title"),
                            self.translator.text("server_crashed_message"),
                        )
                    if kind == "action":
                        self._finish_action(status)
        self.after(10 if processed == _MAX_EVENTS_PER_TICK else 100, self._drain_event_queue)

    def _run_action(self, name: str, action: Callable[[], ServerStatus]) -> None:
        if self.action_runner.run(action):
            self.pending_action = name
            self.overview.set_lifecycle(self.current_status, busy=True)

    def _finish_action(self, status: ServerStatus) -> None:
        action = self.pending_action
        self.pending_action = ""
        self.monitor.request_refresh()
        if self.restart_waiting:
            self.restart_waiting = False
            self.overview.set_restart_waiting(False)
        if action in {"restart", "wait_restart"} and status.state != "running":
            self.notifier.send_once(
                f"restart-failed-{int(time.time())}",
                self.translator.text("restart_failed_title"),
                self.translator.text("restart_failed_message"),
            )
        if action in {"stop_close", "force_close"}:
            if status.state == "stopped":
                self._final_close()
                return
            if status.state == "unresponsive":
                self._decision(
                    self.translator.text("force_stop_title"),
                    self.translator.text("force_stop_message"),
                    (
                        (self.translator.text("cancel"), self._cancel_close, False),
                        (
                            self.translator.text("force_stop"),
                            lambda: self._run_action("force_close", self.controller.force_stop),
                            True,
                        ),
                    ),
                )
                return
        if action == "stop" and status.state == "unresponsive":
            self._decision(
                self.translator.text("force_stop_title"),
                self.translator.text("force_stop_message"),
                (
                    (self.translator.text("cancel"), lambda: None, False),
                    (
                        self.translator.text("force_stop"),
                        lambda: self._run_action("force_stop", self.controller.force_stop),
                        True,
                    ),
                ),
            )

    def _request_restart(self) -> None:
        if self.restart_waiting:
            self.restart_cancel.set()
            return
        session = self.runtime_payload.get("session")
        work = self.runtime_payload.get("agent_work", {})
        recording = isinstance(session, dict) and session.get("recording_status") == "running"
        active_work = isinstance(work, dict) and (
            int(work.get("queued", 0)) + int(work.get("running", 0)) > 0
        )
        if recording:
            self._decision(
                self.translator.text("restart_recording_title"),
                self.translator.text("restart_recording_message"),
                (
                    (self.translator.text("cancel"), lambda: None, False),
                    (
                        self.translator.text("restart_now"),
                        lambda: self._run_action("restart", self.controller.restart),
                        True,
                    ),
                ),
            )
        elif active_work:
            self._decision(
                self.translator.text("restart_work_title"),
                self.translator.text("restart_work_message"),
                (
                    (self.translator.text("cancel"), lambda: None, False),
                    (self.translator.text("wait_restart"), self._wait_and_restart, False),
                    (
                        self.translator.text("restart_now"),
                        lambda: self._run_action("restart", self.controller.restart),
                        True,
                    ),
                ),
            )
        else:
            self._run_action("restart", self.controller.restart)

    def _wait_and_restart(self) -> None:
        self.restart_cancel.clear()
        self.restart_waiting = True

        def wait() -> ServerStatus:
            if not self.controller.set_agent_drain(True):
                return ServerStatus("error", message="Unable to pause new agent work.")
            while not self.restart_cancel.wait(0.5):
                payload = self.controller.runtime_status_payload()
                work = payload.get("agent_work", {}) if payload else {}
                if isinstance(work, dict) and not (
                    int(work.get("queued", 0)) + int(work.get("running", 0))
                ):
                    return self.controller.restart()
            self.controller.set_agent_drain(False)
            return self.controller.status()

        self._run_action("wait_restart", wait)
        self.overview.set_restart_waiting(True)

    def _decision(
        self,
        title: str,
        message: str,
        choices: tuple[tuple[str, Callable[[], None], bool], ...],
    ) -> None:
        dialog = ctk.CTkToplevel(self, fg_color=TOKENS.canvas)
        dialog.title(title)
        dialog.geometry("520x220")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text=title,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(24, 10))
        ctk.CTkLabel(
            dialog,
            text=message,
            wraplength=470,
            justify="left",
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=13),
        ).pack(anchor="w", padx=24)
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", padx=20, pady=20)
        for label, callback, danger in choices:

            def choose(selected: Callable[[], None] = callback) -> None:
                dialog.destroy()
                selected()

            ctk.CTkButton(
                buttons,
                text=label,
                command=choose,
                width=120,
                fg_color=TOKENS.danger_deep if danger else TOKENS.surface_raised,
                hover_color=TOKENS.primary_hover if danger else TOKENS.surface_active,
                border_width=1,
                border_color=TOKENS.danger if danger else TOKENS.border_strong,
                text_color=TOKENS.text,
            ).pack(side="right", padx=4)

    def _open_web_gui(self) -> None:
        self.controller.open_web_gui()

    @staticmethod
    def _open_link(target: str) -> None:
        webbrowser.open(target)

    def _copy_address(self) -> None:
        self._copy_text(self.current_status.url or self.controller.url)

    def _copy_text(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)

    def _open_log_folder(self) -> None:
        target = str(self.paths.diagnostics)
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target], start_new_session=True)
            else:
                subprocess.Popen(["xdg-open", target], start_new_session=True)
        except OSError:
            _LOGGER.exception("Unable to open log folder")

    def _request_update_check(self, *, manual: bool) -> None:
        if not self.update_lock.acquire(blocking=False):
            return

        def check() -> None:
            try:
                result = self.update_checker.check(manual=manual)
                self.event_queue.put({"kind": "update", "result": result})
            finally:
                self.update_lock.release()

        threading.Thread(target=check, name="elsewise-update-check", daemon=True).start()

    def _open_release(self) -> None:
        self._open_link(self.update_result.release_url or self.links["releases"])

    def _install_cli(self) -> str:
        result = MacCliManager().install()
        return self.translator.text(f"cli_{result.status}").format(path=result.destination)

    def _remove_cli(self) -> str:
        result = MacCliManager().remove()
        return self.translator.text(f"cli_{result.status}").format(path=result.destination)

    def _change_language(self, language: str) -> None:
        self._save_global_settings({"ui_language": language})
        self._apply_interface_settings(language, self.ui_theme)

    def _change_theme(self, theme: str) -> None:
        selected: UiTheme = "light" if theme == "light" else "dark"
        self._save_global_settings({"ui_theme": selected})
        self._apply_interface_settings(self.translator.language, selected)

    def _save_global_settings(self, changes: dict[str, object]) -> None:
        saved = False
        if self.current_status.state == "running" and self.current_status.url:
            request = urllib.request.Request(
                f"{self.current_status.url}/api/settings",
                method="PATCH",
                data=json.dumps(changes).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(request, timeout=2.0).close()
                saved = True
            except (OSError, urllib.error.URLError):
                saved = False
        if not saved:
            SettingsStore(self.paths.config / "settings.json").update(changes)

    def _apply_language(self, language: str) -> None:
        self._apply_interface_settings(language, self.ui_theme)

    def _apply_interface_settings(self, language: str, theme: UiTheme) -> None:
        active = self._active_tab
        self.translator = Translator(language)
        self.ui_theme = theme
        set_theme(theme)
        ctk.set_appearance_mode(theme)
        self.title(f"{self.translator.text('app_title')} {__version__}")
        for child in self.winfo_children():
            child.destroy()
        self.notification_frame = None
        self._build()
        self.show_tab(active)
        self.log_worker.refresh()
        self.overview.set_lifecycle(self.current_status)
        if self.runtime_payload:
            self.overview.set_runtime(self.runtime_payload)
        self.overview.set_update(self.update_result.model_dump(mode="json"))

    def _show_recovery_notice(self) -> None:
        notices = [
            notice
            for notice in (
                self.launcher_settings_store.recovery_notice,
                self.update_checker.store.recovery_notice,
            )
            if notice is not None
        ]
        if not notices:
            return
        messages = [
            self.translator.text(
                "recovery_backup" if notice.source == "backup" else "recovery_defaults"
            ).format(file=notice.file_name)
            for notice in notices
        ]
        self._show_notification(
            self.translator.text("recovery_title"),
            "\n".join(messages),
        )

    def _show_notification(self, title: str, message: str) -> None:
        if self.notification_frame is not None:
            self.notification_frame.destroy()
        frame = ctk.CTkFrame(
            self,
            fg_color=TOKENS.surface_raised,
            border_width=1,
            border_color=TOKENS.warning,
            corner_radius=6,
        )
        frame.place(relx=0.98, rely=0.97, anchor="se")
        ctk.CTkLabel(
            frame,
            text=title,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=13, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        ctk.CTkLabel(
            frame,
            text=message,
            wraplength=360,
            justify="left",
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=12),
        ).grid(row=1, column=0, padx=14, pady=(2, 10), sticky="w")
        ctk.CTkButton(
            frame,
            text="×",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color=TOKENS.surface_active,
            command=frame.destroy,
        ).grid(row=0, column=1, rowspan=2, padx=6)
        self.notification_frame = frame

    def close_launcher(self) -> None:
        if self.closing:
            return
        launcher_settings = self.launcher_settings_store.load()
        if not launcher_settings.stop_server_on_exit or self.current_status.state != "running":
            self._final_close()
            return
        session = self.runtime_payload.get("session")
        recording = isinstance(session, dict) and session.get("recording_status") == "running"
        if recording:
            self._decision(
                self.translator.text("close_recording_title"),
                self.translator.text("close_recording_message"),
                (
                    (self.translator.text("cancel"), lambda: None, False),
                    (
                        self.translator.text("close_keep_server"),
                        self._final_close,
                        False,
                    ),
                    (
                        self.translator.text("stop_and_close"),
                        self._stop_and_close,
                        True,
                    ),
                ),
            )
            return
        self._stop_and_close()

    def _stop_and_close(self) -> None:
        self.closing = True
        self._run_action("stop_close", self.controller.stop)

    def _cancel_close(self) -> None:
        self.closing = False

    def _final_close(self) -> None:
        if self.closed:
            return
        _LOGGER.info("Closing Elsewise Launcher")
        self.closed = True
        self.closing = True
        self.restart_cancel.set()
        with contextlib.suppress(Exception):
            if self.restart_waiting:
                self.controller.set_agent_drain(False)
        with contextlib.suppress(Exception):
            self.monitor.stop()
        with contextlib.suppress(Exception):
            self.log_worker.stop()
        with contextlib.suppress(Exception):
            self.instance.close()
        with contextlib.suppress(Exception):
            self.quit()
        _LOGGER.info("Elsewise Launcher closed")


def main() -> None:
    paths = AppPaths.resolve(ensure_exists=True)
    configure_launcher_logging(paths.diagnostics)
    instance = LauncherSingleInstance(paths.runtime)
    if not instance.acquire():
        if not instance.notify_existing():
            _LOGGER.error("Another launcher instance owns the lock but cannot be activated")
        return
    settings_path = paths.config / "settings.json"
    settings = SettingsStore(settings_path).load()
    language = settings.ui_language
    theme: UiTheme = settings.ui_theme
    set_theme(theme)
    ctk.set_appearance_mode(theme)
    shutdown_requested = threading.Event()
    application: LauncherApplication | None = None
    try:
        with shutdown_signal_handlers(lambda _signal: shutdown_requested.set()):
            application = LauncherApplication(
                paths=paths,
                instance=instance,
                language=language,
                theme=theme,
            )
            instance.start_listener(application.request_activation)
            application.start_services()
            _LOGGER.info("Elsewise Launcher ready")

            def check_shutdown_request() -> None:
                if shutdown_requested.is_set():
                    _LOGGER.info("Launcher shutdown requested by process signal")
                    application.close_launcher()
                    return
                application.after(100, check_shutdown_request)

            application.after(100, check_shutdown_request)
            application.mainloop()
    except KeyboardInterrupt:
        shutdown_requested.set()
    except Exception:
        _LOGGER.exception("Launcher failed")
        raise
    finally:
        if application is not None:
            application._final_close()
        else:
            instance.close()


if __name__ == "__main__":
    main()
