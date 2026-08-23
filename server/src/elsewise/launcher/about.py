from collections.abc import Callable
from typing import Any

import customtkinter as ctk  # type: ignore[import-untyped]
from PIL import Image, ImageDraw

from elsewise import __version__
from elsewise.external_links import ExternalLinks
from elsewise.launcher.assets import asset_path
from elsewise.launcher.i18n import Translator
from elsewise.launcher.theme import TOKENS


class AboutFrame(ctk.CTkScrollableFrame):  # type: ignore[misc]
    def __init__(
        self,
        master: Any,
        *,
        translator: Translator,
        family: str,
        links: ExternalLinks,
        on_link: Callable[[str], None],
    ) -> None:
        super().__init__(master, fg_color=TOKENS.canvas, corner_radius=0)
        self._images: list[ctk.CTkImage] = []
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self,
            text=translator.text("about"),
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=26, weight="normal"),
        ).grid(row=0, column=0, padx=28, pady=(22, 16), sticky="w")

        hero = self._card(row=1)
        brand_line = ctk.CTkFrame(hero, fg_color="transparent")
        brand_line.grid(row=0, column=0, padx=18, pady=(18, 12), sticky="w")
        logo = self._theme_logo((240, 38))
        if logo is not None:
            ctk.CTkLabel(brand_line, text="", image=logo).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            brand_line,
            text=f"v{__version__}",
            height=14,
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=family, size=12, weight="bold"),
        ).grid(row=0, column=1, padx=(12, 0), sticky="s")
        hero_labels: list[ctk.CTkLabel] = []
        for row, key in enumerate(("about_description", "about_local_first", "about_cli"), 1):
            label = ctk.CTkLabel(
                hero,
                text=translator.text(key),
                justify="left",
                anchor="w",
                text_color=TOKENS.text_soft if row == 1 else TOKENS.text_muted,
                font=ctk.CTkFont(family=family, size=13),
            )
            label.grid(row=row, column=0, padx=18, pady=4, sticky="ew")
            hero_labels.append(label)
        hero.grid_columnconfigure(0, weight=1)
        self._bind_dynamic_wrap(hero, hero_labels, horizontal_inset=36)

        facts = self._card(row=2)
        self._link_row(
            facts,
            translator.text("project"),
            "btw-team/elsewise",
            links["project"],
            on_link,
            0,
            family,
        )
        self._link_row(
            facts,
            translator.text("license"),
            "Apache-2.0 + NOTICE",
            links["license"],
            on_link,
            1,
            family,
        )

        stack = self._card(row=3)
        self._section_label(stack, translator.text("core_stack"), 0, family)
        tags = ctk.CTkFrame(stack, fg_color="transparent")
        tags.grid(row=1, column=0, padx=18, pady=(4, 14), sticky="w")
        for index, technology in enumerate(
            ("Python", "FastAPI", "CustomTkinter", "React", "TypeScript", "SQLite", "WebExtensions")
        ):
            ctk.CTkLabel(
                tags,
                text=technology,
                fg_color=TOKENS.surface_raised,
                corner_radius=6,
                text_color=TOKENS.text_soft,
                font=ctk.CTkFont(family=family, size=12),
            ).pack(side="left", padx=(0, 6) if index < 6 else 0, ipadx=7, ipady=3)
        self._section_label(stack, translator.text("third_party"), 2, family)
        third_party = ctk.CTkLabel(
            stack,
            text="Uvicorn · SQLAlchemy · Alembic · Pydantic · Pillow · psutil · Phosphor Icons",
            justify="left",
            anchor="w",
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=family, size=12),
        )
        third_party.grid(row=3, column=0, padx=18, pady=(4, 14), sticky="ew")
        stack.grid_columnconfigure(0, weight=1)
        self._bind_dynamic_wrap(stack, [third_party], horizontal_inset=36)

        footer = self._card(row=4)
        avatar = self._image("white-bunny-avatar.png", (44, 44), corner_radius=9)
        avatar_label: ctk.CTkLabel | None = None
        if avatar is not None:
            avatar_label = ctk.CTkLabel(footer, text="", image=avatar)
            avatar_label.grid(row=0, column=0, padx=(18, 8), pady=12)
        maintained_by = ctk.CTkLabel(
            footer,
            text=translator.text("maintained_by"),
            text_color=TOKENS.text_soft,
            font=ctk.CTkFont(family=family, size=13),
        )
        maintained_by.grid(row=0, column=1, pady=12, sticky="w")
        support_icon = self._image("kofi-icon.png", (18, 18))
        support_button = ctk.CTkButton(
            footer,
            text=translator.text("support_message"),
            image=support_icon,
            compound="left",
            command=lambda: on_link(links["support"]),
            fg_color="transparent",
            hover_color=TOKENS.surface_active,
            text_color=TOKENS.accent_strong,
            font=ctk.CTkFont(family=family, size=12),
        )
        support_button.grid(row=0, column=2, padx=(8, 18), pady=10, sticky="e")
        footer.grid_columnconfigure(2, weight=1)
        self._bind_footer_layout(footer, avatar_label, maintained_by, support_button)

    def _card(self, *, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self,
            fg_color=TOKENS.surface,
            corner_radius=7,
            border_width=1,
            border_color=TOKENS.border,
        )
        card.grid(row=row, column=0, padx=28, pady=7, sticky="ew")
        return card

    def _image(
        self,
        name: str,
        size: tuple[int, int],
        *,
        corner_radius: int | None = None,
    ) -> ctk.CTkImage | None:
        path = asset_path(name)
        if path is None:
            return None
        with Image.open(path) as source:
            prepared = source.convert("RGBA")
        if corner_radius is not None:
            scale = min(prepared.size) / min(size)
            mask = Image.new("L", prepared.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, prepared.width - 1, prepared.height - 1),
                radius=round(corner_radius * scale),
                fill=255,
            )
            prepared.putalpha(mask)
        image = ctk.CTkImage(prepared, size=size)
        self._images.append(image)
        return image

    def _theme_logo(self, size: tuple[int, int]) -> ctk.CTkImage | None:
        dark_path = asset_path("elsewise-logo-dark.png")
        light_path = asset_path("elsewise-logo-light.png")
        if dark_path is None or light_path is None:
            return None
        with Image.open(dark_path) as source:
            dark = source.convert("RGBA")
        with Image.open(light_path) as source:
            light = source.convert("RGBA")
        image = ctk.CTkImage(light_image=light, dark_image=dark, size=size)
        self._images.append(image)
        return image

    @staticmethod
    def _bind_dynamic_wrap(
        master: ctk.CTkFrame,
        labels: list[ctk.CTkLabel],
        *,
        horizontal_inset: int,
    ) -> None:
        current_width = 0

        def resize(event: Any) -> None:
            nonlocal current_width
            wraplength = max(120, int(event.width) - horizontal_inset)
            if wraplength == current_width:
                return
            current_width = wraplength
            for label in labels:
                label.configure(wraplength=wraplength)

        master.bind("<Configure>", resize, add="+")

    @staticmethod
    def _bind_footer_layout(
        footer: ctk.CTkFrame,
        avatar: ctk.CTkLabel | None,
        maintained_by: ctk.CTkLabel,
        support_button: ctk.CTkButton,
    ) -> None:
        stacked: bool | None = None

        def resize(event: Any) -> None:
            nonlocal stacked
            avatar_width = avatar.winfo_reqwidth() if avatar is not None else 0
            avatar_padding = 26 if avatar is not None else 18
            required_width = (
                avatar_width
                + avatar_padding
                + maintained_by.winfo_reqwidth()
                + support_button.winfo_reqwidth()
                + 26
            )
            next_stacked = int(event.width) < required_width
            if next_stacked == stacked:
                return
            stacked = next_stacked
            if next_stacked:
                if avatar is not None:
                    avatar.grid_configure(pady=(12, 6))
                maintained_by.grid_configure(pady=(12, 6))
                support_button.grid_configure(
                    row=1,
                    column=0,
                    columnspan=3,
                    padx=18,
                    pady=(0, 10),
                    sticky="e",
                )
                return
            if avatar is not None:
                avatar.grid_configure(pady=12)
            maintained_by.grid_configure(pady=12)
            support_button.grid_configure(
                row=0,
                column=2,
                columnspan=1,
                padx=(8, 18),
                pady=10,
                sticky="e",
            )

        footer.bind("<Configure>", resize, add="+")

    @staticmethod
    def _link_row(
        master: Any,
        label: str,
        value: str,
        target: str,
        on_link: Callable[[str], None],
        row: int,
        family: str,
    ) -> None:
        top_padding = (8, 2) if row == 0 else (2, 8)
        button_padding = (6, 1) if row == 0 else (1, 6)
        ctk.CTkLabel(
            master,
            text=label,
            text_color=TOKENS.text_muted,
            font=ctk.CTkFont(family=family, size=12),
        ).grid(row=row, column=0, padx=18, pady=top_padding, sticky="w")
        ctk.CTkButton(
            master,
            text=value,
            command=lambda: on_link(target),
            fg_color="transparent",
            hover_color=TOKENS.surface_active,
            text_color=TOKENS.accent,
            font=ctk.CTkFont(family=family, size=13, weight="bold"),
        ).grid(row=row, column=1, padx=18, pady=button_padding, sticky="e")
        master.grid_columnconfigure(1, weight=1)

    @staticmethod
    def _section_label(master: Any, text: str, row: int, family: str) -> None:
        ctk.CTkLabel(
            master,
            text=text,
            text_color=TOKENS.text,
            font=ctk.CTkFont(family=family, size=14, weight="bold"),
        ).grid(row=row, column=0, padx=18, pady=(14, 4), sticky="w")
