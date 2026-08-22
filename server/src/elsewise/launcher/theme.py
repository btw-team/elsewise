from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Any


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    canvas: str = "#0f0e0d"
    panel: str = "#12110f"
    surface: str = "#191714"
    surface_raised: str = "#211e19"
    surface_active: str = "#2b211b"
    border: str = "#37322b"
    border_strong: str = "#55483a"
    text: str = "#e7d9c7"
    text_soft: str = "#cab8a3"
    text_muted: str = "#9a8f83"
    text_faint: str = "#746f67"
    accent: str = "#b88945"
    accent_strong: str = "#d0a45e"
    accent_deep: str = "#695032"
    primary: str = "#a8473f"
    primary_fill: str = "#71302b"
    primary_hover: str = "#873a34"
    danger: str = "#e17c72"
    danger_deep: str = "#441917"
    success: str = "#73b184"
    success_deep: str = "#243327"
    warning: str = "#d0a45e"
    warning_deep: str = "#332819"


TOKENS = ThemeTokens()


def font_family(widget: Any) -> str:
    available = set(tkfont.families(widget))
    for family in ("Inter", "Segoe UI", "SF Pro Text", "DejaVu Sans", "Arial"):
        if family in available:
            return family
    return "TkDefaultFont"
