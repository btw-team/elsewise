from collections.abc import Callable
from functools import partial
from typing import Any

import customtkinter as ctk  # type: ignore[import-untyped]

from elsewise.external_links import ExternalLinks
from elsewise.launcher.i18n import Translator
from elsewise.launcher.theme import TOKENS
from elsewise.runtime.controller import ServerStatus


class OverviewFrame(ctk.CTkScrollableFrame):  # type: ignore[misc]
    def __init__(
        self,
        master: Any,
        *,
        translator: Translator,
        family: str,
        links: ExternalLinks,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_restart: Callable[[], None],
        on_open: Callable[[], None],
        on_copy: Callable[[], None],
        on_link: Callable[[str], None],
        on_check_update: Callable[[], None],
        on_open_release: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color=TOKENS.canvas, corner_radius=0)
        self.translator = translator
        self.family = family
        self.links = links
        self._status = ServerStatus("stopped")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._heading(self, translator.text("overview"), row=0, columnspan=2)
        server = self._card("", row=1, column=0, columnspan=2)
        server_header = ctk.CTkFrame(server, fg_color="transparent")
        server_header.grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="ew")
        ctk.CTkLabel(
            server_header,
            text=translator.text("server").upper(),
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=self.family, size=11, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            server_header,
            text="|",
            text_color=TOKENS.border_strong,
            font=ctk.CTkFont(family=self.family, size=12),
        ).pack(side="left", padx=8)
        self.server_status = ctk.CTkLabel(
            server_header,
            text="Stopped",
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=self.family, size=12, weight="bold"),
        )
        self.server_status.pack(side="left")
        self.server_meta = ctk.CTkLabel(
            server_header,
            text="",
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=12),
        )
        self.server_meta.pack(side="left", padx=(10, 0))
        controls = ctk.CTkFrame(server, fg_color="transparent")
        controls.grid(row=1, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
        self.start_button = self._button(controls, translator.text("start"), on_start, primary=True)
        self.stop_button = self._button(controls, translator.text("stop"), on_stop)
        self.restart_button = self._button(controls, translator.text("restart"), on_restart)
        self._grid_button_row(
            controls,
            (self.start_button, self.stop_button, self.restart_button),
        )

        connections = self._card(translator.text("connections"), row=2, column=0)
        self.web_status = self._row(connections, translator.text("web_gui"), 0)
        self.extension_status = self._row(connections, translator.text("browser_extension"), 1)

        activity = self._card(translator.text("session"), row=2, column=1)
        self.session_status = self._row(activity, translator.text("session"), 0)
        self.source_status = self._row(activity, translator.text("source"), 1)
        self.agent_work_status = self._row(activity, translator.text("agent_work"), 2)

        web = self._card(translator.text("web_gui"), row=3, column=0, columnspan=2)
        self.address = self._value(web, "http://127.0.0.1:38473", 0, 0)
        web_actions = ctk.CTkFrame(web, fg_color="transparent")
        web_actions.grid(row=2, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
        open_web_button = self._button(
            web_actions, translator.text("open_web_gui"), on_open, primary=True
        )
        copy_address_button = self._button(web_actions, translator.text("copy_address"), on_copy)
        self._grid_button_row(web_actions, (open_web_button, copy_address_button))

        agents = self._card(translator.text("agents"), row=4, column=0, columnspan=2)
        self.agent_status_labels: dict[str, ctk.CTkLabel] = {}
        self.agent_path_values: dict[str, ctk.StringVar] = {}
        self._agent_provider(agents, "codex", "Codex", 0)
        self._agent_provider(agents, "claude", "Claude Code", 1)

        updates = self._card(translator.text("updates"), row=5, column=0, columnspan=2)
        self.current_version = self._row(updates, translator.text("current_version"), 0)
        self.latest_version = self._row(updates, translator.text("latest_version"), 1)
        self.update_status = self._row(updates, translator.text("status"), 2)
        self.last_checked = self._row(updates, translator.text("last_checked"), 3)
        update_actions = ctk.CTkFrame(updates, fg_color="transparent")
        update_actions.grid(row=5, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
        check_updates_button = self._button(
            update_actions, translator.text("check_updates"), on_check_update
        )
        release_button = self._button(
            update_actions, translator.text("open_release"), on_open_release
        )
        self._grid_button_row(update_actions, (check_updates_button, release_button))

        links_card = self._card(translator.text("extensions_links"), row=6, column=0, columnspan=2)
        link_values = (
            ("chrome_extension", links["chrome_store"]),
            ("firefox_extension", links["firefox_store"]),
            ("documentation", links["documentation"]),
            ("github_project", links["project"]),
        )
        links_actions = ctk.CTkFrame(links_card, fg_color="transparent")
        links_actions.grid(row=1, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
        links_actions.grid_columnconfigure((0, 1), weight=1)
        for index, (label, url) in enumerate(link_values):
            button = self._button(
                links_actions,
                translator.text(label),
                partial(on_link, url),
            )
            button.grid(
                row=index // 2,
                column=index % 2,
                padx=(0, 8) if index % 2 == 0 else (8, 0),
                pady=(0, 4) if index < 2 else (4, 0),
                sticky="ew",
            )
        self.set_lifecycle(ServerStatus("stopped", url="http://127.0.0.1:38473"))

    def set_lifecycle(self, status: ServerStatus, *, busy: bool = False) -> None:
        self._status = status
        self.server_status.configure(
            text=status.state.replace("_", " ").title(),
            text_color=self._state_color(status.state),
        )
        metadata: list[str] = []
        if status.pid is not None:
            metadata.append(f"PID {status.pid}")
        if status.uptime_seconds is not None:
            metadata.append(f"{int(status.uptime_seconds)}s")
        self.server_meta.configure(text=" · ".join(metadata))
        if status.url:
            self.address.configure(text=status.url)
        self._set_button_state(
            self.start_button,
            enabled=status.state == "stopped" and not busy,
            primary=True,
        )
        self._set_button_state(
            self.stop_button,
            enabled=status.state in {"running", "starting", "unresponsive"} and not busy,
        )
        self._set_button_state(
            self.restart_button,
            enabled=status.state == "running" and not busy,
        )

    def set_restart_waiting(self, waiting: bool) -> None:
        self.restart_button.configure(
            text=(self.translator.text("cancel") if waiting else self.translator.text("restart"))
        )
        self._set_button_state(self.restart_button, enabled=True)
        if waiting:
            self.agent_work_status.configure(text=self.translator.text("waiting_restart"))

    def set_runtime(self, payload: dict[str, Any]) -> None:
        connections = payload.get("connections", {})
        self._set_connection(self.web_status, connections.get("web_gui", {}))
        self._set_connection(self.extension_status, connections.get("browser_extension", {}))
        session = payload.get("session")
        self.session_status.configure(
            text=(
                f"{session.get('title', '')} · {session.get('recording_status', '')}"
                if isinstance(session, dict)
                else self.translator.text("not_running")
            )
        )
        source = payload.get("source")
        self.source_status.configure(
            text=(
                f"{source.get('platform', '')} · {source.get('captions_status', '')}"
                if isinstance(source, dict)
                else "—"
            )
        )
        work = payload.get("agent_work", {})
        if isinstance(work, dict):
            self.agent_work_status.configure(
                text=f"{work.get('running', 0)} running · {work.get('queued', 0)} queued"
            )
        agents = payload.get("agents", {})
        if isinstance(agents, dict):
            for provider_id, status_label in self.agent_status_labels.items():
                provider = agents.get(provider_id)
                if not isinstance(provider, dict):
                    status_label.configure(
                        text=self.translator.text("unavailable"),
                        text_color=TOKENS.danger,
                    )
                    self.agent_path_values[provider_id].set("—")
                    continue
                status = str(provider.get("status", "unavailable"))
                resolved = provider.get("resolved_executable") or "—"
                status_label.configure(
                    text=self._agent_status_text(status),
                    text_color=self._state_color(status),
                )
                self.agent_path_values[provider_id].set(str(resolved))

    def set_update(self, payload: dict[str, Any]) -> None:
        self.current_version.configure(text=str(payload.get("current_version", "—")))
        self.latest_version.configure(text=str(payload.get("latest_version") or "—"))
        status = str(payload.get("status", "not_checked"))
        self.update_status.configure(
            text=self.translator.text(f"update_{status}"),
            text_color=(
                TOKENS.success if status in {"up_to_date", "available"} else TOKENS.text_muted
            ),
        )
        self.last_checked.configure(text=str(payload.get("last_success") or "—"))

    def _set_connection(self, label: ctk.CTkLabel, value: Any) -> None:
        connected = isinstance(value, dict) and bool(value.get("connected"))
        count = int(value.get("count", 0)) if isinstance(value, dict) else 0
        label.configure(
            text=(
                f"{self.translator.text('connected')} · {count}"
                if connected
                else self.translator.text("not_connected")
            ),
            text_color=TOKENS.success if connected else TOKENS.text_muted,
        )

    def _card(self, title: str, *, row: int, column: int, columnspan: int = 1) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self,
            fg_color=TOKENS.surface,
            corner_radius=7,
            border_width=1,
            border_color=TOKENS.border,
        )
        card.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            padx=(0 if column else 26, 26 if column or columnspan == 2 else 8),
            pady=8,
            sticky="nsew",
        )
        card.grid_columnconfigure(1, weight=1)
        if title:
            ctk.CTkLabel(
                card,
                text=title.upper(),
                text_color=TOKENS.text_muted,
                font=ctk.CTkFont(family=self.family, size=11, weight="bold"),
            ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")
        return card

    def _heading(self, master: Any, text: str, *, row: int, columnspan: int) -> None:
        ctk.CTkLabel(
            master,
            text=text,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=26, weight="normal"),
        ).grid(row=row, column=0, columnspan=columnspan, padx=28, pady=(22, 12), sticky="w")

    def _row(self, master: ctk.CTkFrame, name: str, row: int) -> ctk.CTkLabel:
        ctk.CTkLabel(
            master,
            text=name,
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=13),
        ).grid(row=row + 1, column=0, padx=16, pady=6, sticky="w")
        return self._value(master, "—", row, 1, anchor="e")

    def _agent_provider(
        self,
        master: ctk.CTkFrame,
        provider_id: str,
        name: str,
        index: int,
    ) -> None:
        header_row = index * 2 + 1
        header = ctk.CTkFrame(master, fg_color="transparent")
        header.grid(
            row=header_row,
            column=0,
            columnspan=2,
            padx=16,
            pady=(6 if index == 0 else 8, 2),
            sticky="ew",
        )
        ctk.CTkLabel(
            header,
            text=name,
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=13, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="|",
            text_color=TOKENS.border_strong,
            font=ctk.CTkFont(family=self.family, size=12),
        ).pack(side="left", padx=8)
        status = ctk.CTkLabel(
            header,
            text=self.translator.text("unavailable"),
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=self.family, size=12, weight="bold"),
        )
        status.pack(side="left")
        path_value = ctk.StringVar(value="—")
        path = ctk.CTkEntry(
            master,
            textvariable=path_value,
            state="readonly",
            height=30,
            corner_radius=5,
            fg_color=TOKENS.surface_raised,
            border_color=TOKENS.border,
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=12),
        )
        path.grid(
            row=header_row + 1,
            column=0,
            columnspan=2,
            padx=16,
            pady=(2, 8 if index == 0 else 12),
            sticky="ew",
        )
        self.agent_status_labels[provider_id] = status
        self.agent_path_values[provider_id] = path_value

    def _agent_status_text(self, status: str) -> str:
        if status in {"ready", "unavailable"}:
            return self.translator.text(status)
        return status.replace("_", " ").title()

    def _value(
        self, master: Any, text: str, row: int, column: int, *, anchor: str = "w"
    ) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            master,
            text=text,
            text_color=TOKENS.text,
            anchor=anchor,
            font=ctk.CTkFont(family=self.family, size=13),
        )
        label.grid(row=row + 1, column=column, padx=16, pady=6, sticky="ew")
        return label

    def _button(
        self,
        master: Any,
        text: str,
        command: Callable[[], None],
        *,
        primary: bool = False,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            master,
            text=text,
            command=command,
            height=34,
            corner_radius=5,
            fg_color=TOKENS.accent if primary else TOKENS.surface_raised,
            hover_color=TOKENS.accent_strong if primary else TOKENS.surface_active,
            text_color=TOKENS.canvas if primary else TOKENS.text,
            text_color_disabled=TOKENS.text_faint,
            border_width=1,
            border_color=TOKENS.accent_deep if primary else TOKENS.border_strong,
            font=ctk.CTkFont(family=self.family, size=13, weight="bold"),
        )

    @staticmethod
    def _grid_button_row(master: Any, buttons: tuple[ctk.CTkButton, ...]) -> None:
        last_index = len(buttons) - 1
        for index, button in enumerate(buttons):
            master.grid_columnconfigure(index, weight=1)
            padding: tuple[int, int]
            if last_index == 0:
                padding = (0, 0)
            elif index == 0:
                padding = (0, 8)
            elif index == last_index:
                padding = (8, 0)
            else:
                padding = (8, 8)
            button.grid(row=0, column=index, padx=padding, sticky="ew")

    @staticmethod
    def _set_button_state(
        button: ctk.CTkButton,
        *,
        enabled: bool,
        primary: bool = False,
    ) -> None:
        button.configure(
            state="normal" if enabled else "disabled",
            fg_color=(TOKENS.accent if primary else TOKENS.surface_raised)
            if enabled
            else TOKENS.surface,
            border_color=(TOKENS.accent_deep if primary else TOKENS.border_strong)
            if enabled
            else TOKENS.border,
            text_color=TOKENS.canvas if primary and enabled else TOKENS.text,
            text_color_disabled=TOKENS.text_faint,
        )

    @staticmethod
    def _state_color(state: str) -> str:
        if state in {"running", "ready"}:
            return TOKENS.success
        if state in {"error", "unavailable", "port_conflict", "unresponsive"}:
            return TOKENS.danger
        if state in {"starting", "stopping"}:
            return TOKENS.warning
        return TOKENS.text_muted
