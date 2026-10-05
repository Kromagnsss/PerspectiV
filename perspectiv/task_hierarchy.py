from __future__ import annotations


MAX_TASK_LEVEL = 6
STRUCTURING_TASK_LEVELS = frozenset({1, 2})

# A restrained blue-grey scale: structural rows are stronger and details fade to white.
TASK_LEVEL_STYLES: dict[int, dict[str, object]] = {
    1: {
        "background_color": "#d6e2ef",
        "font_weight": 700,
        "font_style": "normal",
        "font_size": 13,
        "text_decoration": "underline",
    },
    2: {
        "background_color": "#e2e9f1",
        "font_weight": 650,
        "font_style": "normal",
        "font_size": 13,
        "text_decoration": "none",
    },
    3: {
        "background_color": "#e9eef4",
        "font_weight": 600,
        "font_style": "normal",
        "font_size": 13,
        "text_decoration": "none",
    },
    4: {
        "background_color": "#eff3f7",
        "font_weight": 500,
        "font_style": "normal",
        "font_size": 13,
        "text_decoration": "none",
    },
    5: {
        "background_color": "#f5f7f9",
        "font_weight": 400,
        "font_style": "normal",
        "font_size": 13,
        "text_decoration": "none",
    },
    6: {
        "background_color": "#fbfcfd",
        "font_weight": 400,
        "font_style": "italic",
        "font_size": 12,
        "text_decoration": "none",
    },
}


def normalize_task_level(level: object, default: int = 1) -> int:
    try:
        value = int(level)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, MAX_TASK_LEVEL))


def task_level_style(level: object) -> dict[str, object]:
    return TASK_LEVEL_STYLES[normalize_task_level(level)]
