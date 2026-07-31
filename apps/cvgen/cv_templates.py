"""
Central registry of CV templates.

To add a new template, add one entry to TEMPLATE_REGISTRY below.
Everything else (gallery, preview, PDF generation) reads from this
registry automatically - no other code needs to change.

layout must be one of the keys in pdf_builder.LAYOUT_BUILDERS
("single" or "sidebar"). cv_preview.html also branches on this
same value, so the on-screen preview and the generated PDF always
stay in sync.
"""

TEMPLATE_REGISTRY = {
    "modern": {
        "name": "Modern",
        "description": "Clean lines with a bold accent header. A strong all-purpose choice.",
        "accent": "#2563EB",
        "layout": "single",
    },
    "professional": {
        "name": "Professional",
        "description": "Traditional two-column layout favored by recruiters.",
        "accent": "#10316B",
        "layout": "sidebar",
    },
    "minimal": {
        "name": "Minimal",
        "description": "Understated, typography-first design with generous whitespace.",
        "accent": "#111827",
        "layout": "single",
    },
    "executive": {
        "name": "Executive",
        "description": "Polished, authoritative layout suited to senior leadership roles.",
        "accent": "#1E293B",
        "layout": "sidebar",
    },
    "creative": {
        "name": "Creative",
        "description": "Distinct color accents for creative and design portfolios.",
        "accent": "#7C3AED",
        "layout": "sidebar",
    },
    "elegant": {
        "name": "Elegant",
        "description": "Refined, editorial styling for a sophisticated feel.",
        "accent": "#9F1239",
        "layout": "single",
    },
    "corporate": {
        "name": "Corporate",
        "description": "Structured, formal format built for corporate applications.",
        "accent": "#0F766E",
        "layout": "sidebar",
    },
    "ats_friendly": {
        "name": "ATS Friendly",
        "description": "Simplified, keyword-first layout optimized for applicant tracking systems.",
        "accent": "#334155",
        "layout": "single",
    },
    "classic": {
        "name": "Classic",
        "description": "A timeless, no-frills black and white CV format.",
        "accent": "#1F2937",
        "layout": "single",
    },
    "compact": {
        "name": "Compact",
        "description": "Space-efficient two-column design that fits more onto one page.",
        "accent": "#B45309",
        "layout": "sidebar",
    },
}

DEFAULT_TEMPLATE_ID = "modern"

TEMPLATE_CHOICES = [(key, meta["name"]) for key, meta in TEMPLATE_REGISTRY.items()]


def get_template_meta(template_id):
    """Return the metadata dict for a template id, falling back to the default."""
    return TEMPLATE_REGISTRY.get(template_id, TEMPLATE_REGISTRY[DEFAULT_TEMPLATE_ID])


def get_template_list():
    """Return all templates as a list of dicts (id + metadata) for the gallery view."""
    return [{"id": key, **meta} for key, meta in TEMPLATE_REGISTRY.items()]


def is_valid_template(template_id):
    return template_id in TEMPLATE_REGISTRY