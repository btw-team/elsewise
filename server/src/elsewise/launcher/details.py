from collections import deque
from collections.abc import Callable
from typing import Any

import customtkinter as ctk  # type: ignore[import-untyped]

from elsewise.launcher.i18n import Translator
from elsewise.launcher.theme import TOKENS


class DetailsFrame(ctk.CTkFrame):  # type: ignore[misc]
    def __init__(
        self,
        master: Any,
        *,
        translator: Translator,
        family: str,
        on_pause: Callable[[bool], None],
        on_refresh: Callable[[], None],
        on_copy: Callable[[str], None],
        on_open_folder: Callable[[], None],
    ) -> None:
        super().__init__(master, fg_color=TOKENS.canvas, corner_radius=0)
        self.translator = translator
        self.family = family
        self.on_pause = on_pause
        self.on_refresh = on_refresh
        self.on_copy = on_copy
        self.paused = False
        self.lines: deque[str] = deque(maxlen=1000)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(
            self,
            text=translator.text("details"),
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=26, weight="normal"),
        ).grid(row=0, column=0, padx=28, pady=(22, 12), sticky="w")
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=1, column=0, padx=28, pady=(0, 10), sticky="ew")
        self.pause_button = self._button(controls, translator.text("pause"), self._toggle_pause)
        self.pause_button.pack(side="left", padx=(0, 6))
        self._button(controls, translator.text("refresh"), on_refresh).pack(side="left", padx=6)
        self._button(
            controls,
            translator.text("copy_visible_log"),
            lambda: on_copy(self.textbox.get("1.0", "end-1c")),
        ).pack(side="left", padx=6)
        self._button(controls, translator.text("open_log_folder"), on_open_folder).pack(
            side="left", padx=6
        )
        self.textbox = ctk.CTkTextbox(
            self,
            fg_color=TOKENS.surface,
            text_color=TOKENS.text_soft,
            border_width=1,
            border_color=TOKENS.border,
            corner_radius=6,
            wrap="none",
            font=ctk.CTkFont(family="DejaVu Sans Mono", size=12),
        )
        self.textbox.grid(row=2, column=0, padx=28, pady=(0, 24), sticky="nsew")
        self.textbox.configure(state="disabled")

    def append_lines(self, lines: list[str], *, replace: bool = False) -> None:
        if replace:
            self.lines.clear()
        self.lines.extend(lines)
        bottom = self.textbox.yview()[1] >= 0.995
        current = self.textbox.yview()
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", "".join(self.lines))
        self.textbox.configure(state="disabled")
        if bottom:
            self.textbox.see("end")
        else:
            self.textbox.yview_moveto(current[0])

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_button.configure(text=self.translator.text("resume" if self.paused else "pause"))
        self.on_pause(self.paused)

    def _button(self, master: Any, text: str, command: Callable[[], None]) -> ctk.CTkButton:
        return ctk.CTkButton(
            master,
            text=text,
            command=command,
            height=32,
            fg_color=TOKENS.surface_raised,
            hover_color=TOKENS.surface_active,
            border_width=1,
            border_color=TOKENS.border_strong,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=self.family, size=12),
        )
