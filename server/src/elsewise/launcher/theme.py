import json
from dataclasses import dataclass, fields
from pathlib import Path
from tkinter import font as tkfont
from typing import Any, Literal, cast

UiTheme = Literal["dark", "light"]


@dataclass(slots=True)
class ThemeTokens:
    canvas: str = ""
    panel: str = ""
    surface: str = ""
    surface_raised: str = ""
    surface_active: str = ""
    border: str = ""
    border_strong: str = ""
    text: str = ""
    text_soft: str = ""
    text_muted: str = ""
    text_faint: str = ""
    accent: str = ""
    accent_strong: str = ""
    accent_deep: str = ""
    primary: str = ""
    primary_fill: str = ""
    primary_hover: str = ""
    primary_text: str = ""
    on_accent: str = ""
    danger: str = ""
    danger_deep: str = ""
    success: str = ""
    success_deep: str = ""
    warning: str = ""
    warning_deep: str = ""
    focus_ring: str = ""


def _token_file() -> Path:
    packaged = Path(__file__).resolve().parents[1] / "assets" / "theme-tokens.json"
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[4] / "shared" / "theme-tokens.json"


def _load_themes() -> dict[UiTheme, dict[str, str]]:
    payload = json.loads(_token_file().read_text(encoding="utf-8"))
    expected = {field.name for field in fields(ThemeTokens)}
    themes: dict[UiTheme, dict[str, str]] = {}
    for name in ("dark", "light"):
        values = payload.get(name)
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError(f"Invalid {name} launcher theme token table")
        if not all(isinstance(value, str) for value in values.values()):
            raise ValueError(f"Invalid {name} launcher theme token value")
        themes[name] = cast(dict[str, str], values)
    return themes


THEMES = _load_themes()
TOKENS = ThemeTokens(**THEMES["dark"])
_current_theme: UiTheme = "dark"


def set_theme(theme: UiTheme) -> None:
    """Update the stable token object imported by launcher components."""
    global _current_theme
    for name, value in THEMES[theme].items():
        setattr(TOKENS, name, value)
    _current_theme = theme


def current_theme() -> UiTheme:
    return _current_theme


def font_family(widget: Any) -> str:
    available = set(tkfont.families(widget))
    for family in ("Inter", "Segoe UI", "SF Pro Text", "DejaVu Sans", "Arial"):
        if family in available:
            return family
    return "TkDefaultFont"
