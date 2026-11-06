"""Light and dark themes. Item tiles stay dark to keep TF2 quality colours readable."""

PALETTES = {
    "light": {
        "bg": "#F3F4F6",
        "surface": "#FFFFFF",
        "text": "#20242B",
        "muted": "#626B78",
        "nav": "#E8EBF0",
        "nav_text": "#434B57",
        "nav_active": "#D8E2F0",
        "accent": "#365F91",
        "accent_hover": "#2C507C",
        "accent_disabled": "#AABCD1",
        "on_accent": "#FFFFFF",
        "border": "#D5DAE1",
        "hover": "#E9EDF2",
        "disabled": "#ECEFF3",
        "disabled_text": "#7B8491",
        "selection": "#DCE8F7",
        "selection_text": "#192D48",
        "danger": "#A63038",
        "success": "#286D4C",
        "scrollbar": "#BCC4CF",
        "item_bg": "#30343A",
        "item_border": "#AEB8C6",
        "placeholder": "#68717E",
    },
    "dark": {
        "bg": "#181B20",
        "surface": "#23272E",
        "text": "#E5E9F0",
        "muted": "#A8B0BC",
        "nav": "#20242A",
        "nav_text": "#B8C0CC",
        "nav_active": "#35465D",
        "accent": "#476F9F",
        "accent_hover": "#527EAF",
        "accent_disabled": "#3C4C61",
        "on_accent": "#FFFFFF",
        "border": "#454D59",
        "hover": "#303741",
        "disabled": "#2B3038",
        "disabled_text": "#8D97A6",
        "selection": "#3A5577",
        "selection_text": "#F4F7FC",
        "danger": "#F09AA1",
        "success": "#8DC7A5",
        "scrollbar": "#606C7D",
        "item_bg": "#2B3037",
        "item_border": "#536071",
        "placeholder": "#68778B",
    },
}


def palette(theme="light"):
    """Return a copy so widget changes cannot alter the shared palette."""
    return dict(PALETTES.get(theme, PALETTES["light"]))
