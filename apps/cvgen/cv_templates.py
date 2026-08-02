"""
Central registry of CV templates.

To add a new template, add one entry to TEMPLATE_REGISTRY below.
Everything else (gallery, preview, PDF generation) reads from this
registry automatically - no other code needs to change.

Fields:
  layout          "single" | "sidebar" | "banded"
                  - single: classic top header, full-width body
                  - sidebar: full-height colored column + white main column
                  - banded: full-width colored header bar, plain two-column body below
  sidebar_side    "left" | "right"  (only used when layout == "sidebar")
  font            "sans" | "serif"
  heading_style   "underline" | "block" | "plain_caps"
                  - underline: heading text + thin accent rule beneath it
                  - block: heading text on a solid accent-colored chip
                  - plain_caps: bold accent-colored capitalized text, no rule/chip
  divider         True/False - whether a rule appears under the name/contact
                  block (only meaningful for "single" layout)

Both pdf_builder.py and cv_preview.html branch on these same fields, so the
on-screen preview and the generated PDF always stay visually in sync.
"""

TEMPLATE_REGISTRY = {
    "modern": {
        "name": "Modern",
        "description": "Bold header chip and clean single-column body. Strong all-purpose choice.",
        "accent": "#2563EB",
        "layout": "single",
        "font": "sans",
        "heading_style": "block",
        "divider": True,
    },
    "professional": {
        "name": "Professional",
        "description": "Full-height navy sidebar on the left, classic two-column recruiter format.",
        "accent": "#10316B",
        "layout": "sidebar",
        "sidebar_side": "left",
        "font": "sans",
        "heading_style": "underline",
    },
    "minimal": {
        "name": "Minimal",
        "description": "Understated, typography-first design. No rules, no chips - just clean type.",
        "accent": "#111827",
        "layout": "single",
        "font": "sans",
        "heading_style": "plain_caps",
        "divider": False,
    },
    "executive": {
        "name": "Executive",
        "description": "Full-width slate header band over a serif, two-column body for senior roles.",
        "accent": "#1E293B",
        "layout": "banded",
        "font": "serif",
        "heading_style": "underline",
    },
    "creative": {
        "name": "Creative",
        "description": "Violet sidebar on the right with bold chip headings for a design-forward feel.",
        "accent": "#7C3AED",
        "layout": "sidebar",
        "sidebar_side": "right",
        "font": "sans",
        "heading_style": "block",
    },
    "elegant": {
        "name": "Elegant",
        "description": "Serif typography with underlined section rules for an editorial feel.",
        "accent": "#9F1239",
        "layout": "single",
        "font": "serif",
        "heading_style": "underline",
        "divider": True,
    },
    "corporate": {
        "name": "Corporate",
        "description": "Teal header band with a structured two-column body beneath it.",
        "accent": "#0F766E",
        "layout": "banded",
        "font": "sans",
        "heading_style": "block",
    },
    "ats_friendly": {
        "name": "ATS Friendly",
        "description": "Single column, minimal styling, plain capitalized headings - built for parsers.",
        "accent": "#334155",
        "layout": "single",
        "font": "sans",
        "heading_style": "plain_caps",
        "divider": False,
    },
    "classic": {
        "name": "Classic",
        "description": "Timeless serif CV with underlined section rules, no sidebar.",
        "accent": "#1F2937",
        "layout": "single",
        "font": "serif",
        "heading_style": "underline",
        "divider": True,
    },
    "compact": {
        "name": "Compact",
        "description": "Amber sidebar on the left with tight, capitalized headings to fit more per page.",
        "accent": "#B45309",
        "layout": "sidebar",
        "sidebar_side": "left",
        "font": "sans",
        "heading_style": "plain_caps",
    },
}

DEFAULT_TEMPLATE_ID = "modern"

TEMPLATE_CHOICES = [(key, meta["name"]) for key, meta in TEMPLATE_REGISTRY.items()]

_DEFAULTS = {
    "sidebar_side": "left",
    "font": "sans",
    "heading_style": "underline",
    "divider": True,
}


def get_template_meta(template_id):
    """Return the metadata dict for a template id, falling back to the default.
    Fills in any optional fields (sidebar_side, font, heading_style, divider)
    that a template entry didn't explicitly set."""
    meta = dict(TEMPLATE_REGISTRY.get(template_id, TEMPLATE_REGISTRY[DEFAULT_TEMPLATE_ID]))
    for key, value in _DEFAULTS.items():
        meta.setdefault(key, value)
    return meta


def get_template_list():
    """Return all templates as a list of dicts (id + metadata) for the gallery view."""
    return [get_template_meta(key) | {"id": key} for key in TEMPLATE_REGISTRY]


def is_valid_template(template_id):
    return template_id in TEMPLATE_REGISTRY