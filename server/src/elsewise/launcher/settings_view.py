from collections.abc import Callable
from math import ceil
from tkinter import font as tkfont
from typing import Any

import customtkinter as ctk  # type: ignore[import-untyped]

from elsewise.launcher.i18n import Translator
from elsewise.launcher.theme import TOKENS
from elsewise.settings.languages import (
    LANGUAGE_DISPLAY_NAMES,
    SUPPORTED_LANGUAGE_SET,
)
from elsewise.settings.launcher import LauncherSettingsStore
from elsewise.settings.pairing import PairingManager


class _WidthMatchedOptionMenu(ctk.CTkOptionMenu):  # type: ignore[misc]
    """Option menu whose native dropdown follows the rendered widget width."""

    _DEFAULT_DROPDOWN_CHARACTERS = 18

    def _open_dropdown_menu(self) -> None:
        dropdown = self._dropdown_menu
        dropdown._min_character_width = self._DEFAULT_DROPDOWN_CHARACTERS
        dropdown._add_menu_commands()
        self.update_idletasks()

        target_width = self.winfo_width()
        requested_width = dropdown.winfo_reqwidth()
        if requested_width < target_width:
            menu_font = tkfont.Font(root=self, font=dropdown.cget("font"))
            space_width = max(1, menu_font.measure(" "))
            extra_characters = ceil((target_width - requested_width) / space_width)
            dropdown._min_character_width += extra_characters
            dropdown._add_menu_commands()

        super()._open_dropdown_menu()


class SettingsFrame(ctk.CTkScrollableFrame):  # type: ignore[misc]
    def __init__(
        self,
        master: Any,
        *,
        translator: Translator,
        family: str,
        store: LauncherSettingsStore,
        pairing: PairingManager,
        language: str,
        server_running: Callable[[], bool],
        on_language: Callable[[str], None],
        on_install_cli: Callable[[], str] | None = None,
        on_remove_cli: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(master, fg_color=TOKENS.canvas, corner_radius=0)
        self.translator = translator
        self.family = family
        self.store = store
        self.pairing = pairing
        self.server_running = server_running
        self.on_language = on_language
        settings = store.load()
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self,
            text=translator.text("settings"),
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=22, weight="bold"),
        ).grid(row=0, column=0, padx=28, pady=(26, 18), sticky="w")
        card = ctk.CTkFrame(
            self,
            fg_color=TOKENS.surface,
            corner_radius=7,
            border_width=1,
            border_color=TOKENS.border,
        )
        card.grid(row=1, column=0, padx=28, pady=6, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        self._add_field_label(card, translator.text("interface_language"), 0)
        self.language_menu = _WidthMatchedOptionMenu(
            card,
            values=list(LANGUAGE_DISPLAY_NAMES.values()),
            command=self._language_changed,
            fg_color=TOKENS.surface_raised,
            button_color=TOKENS.accent_deep,
            button_hover_color=TOKENS.accent,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=13),
        )
        selected_language = language if language in SUPPORTED_LANGUAGE_SET else "en"
        self.language_menu.set(LANGUAGE_DISPLAY_NAMES[selected_language])
        self.language_menu.grid(row=0, column=1, padx=18, pady=12, sticky="ew")

        self.start_var = ctk.BooleanVar(value=settings.start_server_on_launch)
        self.check_var = ctk.BooleanVar(value=settings.check_updates_on_launch)
        self.stop_var = ctk.BooleanVar(value=settings.stop_server_on_exit)
        self._checkbox(
            card,
            translator.text("start_on_launch"),
            self.start_var,
            1,
            lambda: self._save(start_server_on_launch=self.start_var.get()),
        )
        self._checkbox(
            card,
            translator.text("check_updates_on_launch"),
            self.check_var,
            2,
            lambda: self._save(check_updates_on_launch=self.check_var.get()),
        )
        self._add_field_label(card, translator.text("maximum_log_storage"), 3)
        self.log_menu = _WidthMatchedOptionMenu(
            card,
            values=[f"{value} MB" for value in settings.supported_log_limits()],
            command=self._log_limit_changed,
            fg_color=TOKENS.surface_raised,
            button_color=TOKENS.accent_deep,
            button_hover_color=TOKENS.accent,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=13),
        )
        self.log_menu.set(f"{settings.server_log_total_limit_mb} MB")
        self.log_menu.grid(row=3, column=1, padx=18, pady=12, sticky="ew")
        self._checkbox(
            card,
            translator.text("stop_on_exit"),
            self.stop_var,
            4,
            lambda: self._save(stop_server_on_exit=self.stop_var.get()),
        )
        if on_install_cli is not None and on_remove_cli is not None:
            cli_actions = ctk.CTkFrame(card, fg_color="transparent")
            cli_actions.grid(row=5, column=0, columnspan=2, padx=16, pady=8, sticky="ew")
            cli_actions.grid_columnconfigure((0, 1), weight=1)
            install_button = self._action_button(
                cli_actions,
                translator.text("install_cli"),
                lambda: self._show_feedback(on_install_cli()),
            )
            remove_button = self._action_button(
                cli_actions,
                translator.text("remove_cli"),
                lambda: self._show_feedback(on_remove_cli()),
            )
            install_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
            remove_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")
        pairing_card = ctk.CTkFrame(
            self,
            fg_color=TOKENS.surface,
            corner_radius=7,
            border_width=1,
            border_color=TOKENS.border,
        )
        pairing_card.grid(row=2, column=0, padx=28, pady=6, sticky="ew")
        pairing_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            pairing_card,
            text=translator.text("browser_extension_pairing"),
            text_color=TOKENS.text,
            anchor="w",
            font=ctk.CTkFont(family=family, size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(16, 5), sticky="ew")
        ctk.CTkLabel(
            pairing_card,
            text=translator.text("pairing_hint"),
            text_color=TOKENS.text_faint,
            anchor="w",
            justify="left",
            wraplength=820,
            font=ctk.CTkFont(family=family, size=12),
        ).grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        ctk.CTkLabel(
            pairing_card,
            text=translator.text("pairing_token"),
            text_color=TOKENS.text_soft,
            anchor="w",
            font=ctk.CTkFont(family=family, size=13),
        ).grid(row=2, column=0, padx=18, pady=(0, 6), sticky="ew")
        self.pairing_token_var = ctk.StringVar(value=pairing.token())
        self.pairing_token_entry = ctk.CTkEntry(
            pairing_card,
            textvariable=self.pairing_token_var,
            fg_color=TOKENS.canvas,
            border_color=TOKENS.border,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=12),
        )
        self.pairing_token_entry.grid(row=3, column=0, padx=18, pady=(0, 12), sticky="ew")
        pairing_actions = ctk.CTkFrame(pairing_card, fg_color="transparent")
        pairing_actions.grid(row=4, column=0, padx=18, pady=(0, 16), sticky="ew")
        pairing_actions.grid_columnconfigure((0, 1, 2), weight=1)
        copy_button = self._action_button(
            pairing_actions,
            translator.text("copy_token"),
            self._copy_pairing_token,
        )
        regenerate_button = self._action_button(
            pairing_actions,
            translator.text("regenerate_token"),
            self._regenerate_pairing_token,
        )
        save_button = self._action_button(
            pairing_actions,
            translator.text("save"),
            self._save_pairing_token,
        )
        copy_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        regenerate_button.grid(row=0, column=1, padx=8, sticky="ew")
        save_button.grid(row=0, column=2, padx=(8, 0), sticky="ew")

        self.feedback = ctk.CTkLabel(
            self,
            text="",
            text_color=TOKENS.success,
            font=ctk.CTkFont(family=family, size=12),
        )
        self.feedback.grid(row=3, column=0, padx=30, pady=8, sticky="w")

    def _language_changed(self, name: str) -> None:
        language = next(
            (code for code, display in LANGUAGE_DISPLAY_NAMES.items() if display == name), "en"
        )
        self.on_language(language)

    def _log_limit_changed(self, value: str) -> None:
        limit = int(value.split()[0])
        self._save(server_log_total_limit_mb=limit)
        if self.server_running():
            self._show_feedback(self.translator.text("applied_next_start"))

    def _save(self, **changes: object) -> None:
        self.store.update(**changes)
        self._show_feedback(self.translator.text("saved"))

    def _copy_pairing_token(self) -> None:
        token = self.pairing_token_var.get().strip()
        if not token:
            self._show_feedback(self.translator.text("pairing_invalid"), error=True)
            return
        self.clipboard_clear()
        self.clipboard_append(token)
        self._show_feedback(self.translator.text("pairing_copied"))

    def _regenerate_pairing_token(self) -> None:
        token = self.pairing.regenerate()
        self.pairing_token_var.set(token)
        self._show_feedback(self.translator.text("pairing_regenerated"))

    def _save_pairing_token(self) -> None:
        try:
            self.pairing.save(self.pairing_token_var.get())
        except ValueError:
            self._show_feedback(self.translator.text("pairing_invalid"), error=True)
            return
        self.pairing_token_var.set(self.pairing.token())
        self._show_feedback(self.translator.text("pairing_saved"))

    def _show_feedback(self, text: str, *, error: bool = False) -> None:
        self.feedback.configure(text=text, text_color=TOKENS.danger if error else TOKENS.success)
        self.after(2500, lambda: self.feedback.configure(text=""))

    def _add_field_label(self, master: Any, text: str, row: int) -> None:
        ctk.CTkLabel(
            master,
            text=text,
            text_color=TOKENS.text_soft,
            anchor="w",
            font=ctk.CTkFont(family=self.family, size=13),
        ).grid(row=row, column=0, padx=18, pady=12, sticky="w")

    def _checkbox(
        self,
        master: Any,
        text: str,
        variable: Any,
        row: int,
        command: Callable[[], None],
    ) -> None:
        checkbox = ctk.CTkCheckBox(
            master,
            text=text,
            variable=variable,
            command=command,
            fg_color=TOKENS.accent,
            hover_color=TOKENS.accent_strong,
            border_color=TOKENS.border_strong,
            checkmark_color=TOKENS.canvas,
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=self.family, size=13),
        )
        checkbox.grid(row=row, column=0, columnspan=2, padx=18, pady=12, sticky="w")

    def _action_button(self, master: Any, text: str, command: Callable[[], None]) -> ctk.CTkButton:
        return ctk.CTkButton(
            master,
            text=text,
            command=command,
            height=34,
            corner_radius=5,
            fg_color=TOKENS.surface_raised,
            hover_color=TOKENS.surface_active,
            border_width=1,
            border_color=TOKENS.border_strong,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=13, weight="bold"),
        )
