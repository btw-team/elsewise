import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_theme_tokens_cover_both_palettes_and_core_pairs_meet_wcag_aa() -> None:
    themes = json.loads((ROOT / "shared/theme-tokens.json").read_text(encoding="utf-8"))
    assert themes["dark"]["canvas"] == "#1b2229"
    assert themes["dark"]["accent"] == "#03b8e9"
    assert themes["dark"]["accent_strong"] == "#17d3cf"
    assert themes["light"]["canvas"] == "#f7fafb"
    assert themes["light"]["accent"] == "#038ab3"
    assert themes["light"]["accent_strong"] == "#09bfbd"
    assert set(themes["dark"]) == set(themes["light"])

    for values in themes.values():
        for foreground, background in (
            ("text", "canvas"),
            ("text", "panel"),
            ("text_soft", "canvas"),
            ("text_soft", "panel"),
            ("primary_text", "primary_fill"),
            ("danger", "danger_deep"),
            ("success", "success_deep"),
            ("warning", "warning_deep"),
        ):
            assert _contrast(values[foreground], values[background]) >= 4.5, (
                foreground,
                background,
            )
