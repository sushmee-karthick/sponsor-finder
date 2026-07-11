"""Small, safe presentation helpers for the Streamlit interface."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from urllib.parse import urlsplit

GOV_UK_REGISTER_URL = (
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
)


GLOBAL_STYLES = """
<style>
:root {
    --sf-navy-950: #08142f;
    --sf-navy-900: #0c1b3a;
    --sf-navy-800: #15315f;
    --sf-blue-600: #2457d6;
    --sf-blue-500: #3974ef;
    --sf-teal-500: #19a69a;
    --sf-ink-900: #111b33;
    --sf-ink-700: #41506a;
    --sf-ink-500: #637087;
    --sf-line: #dfe5ef;
    --sf-surface: #ffffff;
    --sf-canvas: #f4f7fb;
    --sf-warning: #8a5300;
    --sf-focus: #0b72e7;
}

html {
    scroll-behavior: smooth;
}

body,
[data-testid="stAppViewContainer"],
[data-testid="stSidebar"] {
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 91% 1%, rgba(57, 116, 239, 0.11), transparent 27rem),
        radial-gradient(circle at 8% 32%, rgba(25, 166, 154, 0.07), transparent 22rem),
        var(--sf-canvas);
    color: var(--sf-ink-900);
}

[data-testid="stHeader"] {
    background: rgba(244, 247, 251, 0.86);
    border-bottom: 1px solid rgba(223, 229, 239, 0.78);
    backdrop-filter: blur(14px);
}

[data-testid="stMainBlockContainer"],
.block-container {
    max-width: 1380px;
    padding: 2.25rem 2.75rem 4rem;
}

[data-testid="stSidebar"] {
    background: rgba(251, 252, 255, 0.98);
    border-right: 1px solid var(--sf-line);
}

[data-testid="stSidebarContent"] {
    padding-top: 1.5rem;
}

.sf-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin: 0.1rem 0 1.35rem;
    padding: 0.2rem 0.1rem;
}

.sf-brand-mark {
    display: inline-flex;
    width: 2.7rem;
    height: 2.7rem;
    flex: 0 0 2.7rem;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(255, 255, 255, 0.13);
    border-radius: 0.85rem;
    background: linear-gradient(145deg, var(--sf-navy-900), var(--sf-blue-600));
    box-shadow: 0 8px 22px rgba(12, 27, 58, 0.18);
}

.sf-sidebar-brand strong {
    display: block;
    color: var(--sf-navy-950);
    font-size: 1.02rem;
    letter-spacing: -0.02em;
    line-height: 1.2;
}

.sf-sidebar-brand small {
    display: block;
    margin-top: 0.18rem;
    color: var(--sf-ink-500);
    font-size: 0.71rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

[data-testid="stSidebar"] h3 {
    margin: 1.2rem 0 0.25rem;
    color: var(--sf-blue-600);
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.11em;
    text-transform: uppercase;
}

.st-key-sf_hero {
    position: relative;
    isolation: isolate;
    overflow: hidden;
    margin-bottom: 1.15rem;
    padding: clamp(1.6rem, 4vw, 3.2rem);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 1.45rem;
    background:
        radial-gradient(circle at 87% 8%, rgba(57, 116, 239, 0.46), transparent 23rem),
        radial-gradient(circle at 79% 112%, rgba(25, 166, 154, 0.25), transparent 22rem),
        linear-gradient(135deg, var(--sf-navy-950), #102b57 64%, #14386c);
    box-shadow: 0 24px 60px rgba(12, 27, 58, 0.18);
}

.st-key-sf_hero::after {
    position: absolute;
    z-index: -1;
    top: -8rem;
    right: -7rem;
    width: 21rem;
    height: 21rem;
    border: 1px solid rgba(255, 255, 255, 0.13);
    border-radius: 50%;
    box-shadow:
        0 0 0 3.2rem rgba(255, 255, 255, 0.025),
        0 0 0 6.4rem rgba(255, 255, 255, 0.018);
    content: "";
}

.st-key-sf_hero h1 {
    max-width: 820px;
    margin: 0.45rem 0 0.6rem;
    color: #ffffff;
    font-size: clamp(2.15rem, 5vw, 4.25rem);
    font-weight: 760;
    letter-spacing: -0.055em;
    line-height: 0.98;
}

.st-key-sf_hero [data-testid="stCaptionContainer"] {
    max-width: 800px;
    color: rgba(236, 243, 255, 0.73);
}

.st-key-sf_hero [data-testid="stLinkButton"] a {
    min-height: 2.75rem;
    border: 1px solid rgba(255, 255, 255, 0.82);
    border-radius: 0.75rem;
    background: #ffffff;
    color: var(--sf-navy-900);
    font-weight: 750;
    box-shadow: 0 10px 24px rgba(8, 20, 47, 0.2);
}

.sf-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    color: #a9c7ff;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

.sf-eyebrow-dot {
    width: 0.52rem;
    height: 0.52rem;
    border: 2px solid rgba(255, 255, 255, 0.48);
    border-radius: 50%;
    background: #34d5c5;
    box-shadow: 0 0 0 0.26rem rgba(52, 213, 197, 0.13);
}

.sf-hero-lede {
    max-width: 760px;
    margin: 0 0 1.15rem;
    color: #eef4ff;
    font-size: clamp(1.02rem, 2vw, 1.23rem);
    line-height: 1.62;
}

.sf-trust-chips,
.sf-filter-chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.48rem;
}

.sf-trust-chips {
    margin: 0 0 1.15rem;
}

.sf-trust-chip {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
    padding: 0.38rem 0.7rem;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.07);
    color: rgba(244, 248, 255, 0.9);
    font-size: 0.75rem;
    font-weight: 650;
    backdrop-filter: blur(8px);
}

.st-key-sf_source_strip {
    margin: 0.4rem 0 1.15rem;
    padding: 0.95rem 1.15rem;
    border: 1px solid var(--sf-line);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.82);
    box-shadow: 0 8px 30px rgba(32, 48, 76, 0.045);
}

.st-key-sf_source_strip p {
    margin-bottom: 0;
}

.sf-status-badge {
    display: inline-flex;
    align-items: center;
    min-height: 2rem;
    padding: 0.4rem 0.75rem;
    border-radius: 999px;
    font-size: 0.73rem;
    font-weight: 800;
    letter-spacing: 0.025em;
    line-height: 1.35;
    text-align: center;
}

.sf-status-badge--warning {
    border: 1px solid #efcf99;
    background: #fff7e8;
    color: var(--sf-warning);
}

.sf-status-badge--neutral {
    border: 1px solid #cfd9ec;
    background: #f2f6fd;
    color: var(--sf-navy-800);
}

.st-key-sf_metrics {
    margin: 0.15rem 0 1.65rem;
}

.st-key-sf_metrics [data-testid="stMetric"] {
    min-height: 8.25rem;
    padding: 1.05rem 1.1rem;
    border: 1px solid var(--sf-line);
    border-radius: 1rem;
    background: rgba(255, 255, 255, 0.9);
    box-shadow: 0 10px 28px rgba(32, 48, 76, 0.055);
}

.st-key-sf_metrics [data-testid="stMetricLabel"] {
    color: var(--sf-ink-500);
    font-size: 0.78rem;
    font-weight: 720;
    letter-spacing: 0.025em;
}

.st-key-sf_metrics [data-testid="stMetricValue"] {
    color: var(--sf-navy-950);
    font-size: clamp(1.75rem, 3vw, 2.35rem);
    font-weight: 760;
    letter-spacing: -0.045em;
}

.sf-filter-chips {
    margin: 0.65rem 0 1rem;
}

.sf-filter-label {
    margin-right: 0.15rem;
    color: var(--sf-ink-500);
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

.sf-filter-chip {
    display: inline-flex;
    align-items: center;
    max-width: 100%;
    min-height: 1.9rem;
    padding: 0.34rem 0.68rem;
    border: 1px solid #cfdbf1;
    border-radius: 999px;
    background: #edf3ff;
    color: #214789;
    font-size: 0.76rem;
    font-weight: 650;
    overflow-wrap: anywhere;
    white-space: normal;
}

.st-key-sf_results {
    margin-top: 0.25rem;
    padding: clamp(1rem, 2vw, 1.45rem);
    border: 1px solid var(--sf-line);
    border-radius: 1.15rem;
    background: rgba(255, 255, 255, 0.88);
    box-shadow: 0 14px 36px rgba(32, 48, 76, 0.055);
}

.st-key-sf_results h2,
.st-key-sf_about h2 {
    color: var(--sf-navy-950);
    font-size: clamp(1.45rem, 3vw, 1.85rem);
    font-weight: 750;
    letter-spacing: -0.035em;
}

.st-key-sf_result_controls {
    margin: 0.35rem 0 0.9rem;
    padding: 0.75rem;
    border: 1px solid #e5eaf2;
    border-radius: 0.9rem;
    background: #f8faff;
}

[data-testid="stButton"] button,
[data-testid="stDownloadButton"] button,
[data-testid="stLinkButton"] a {
    min-height: 2.65rem;
    border-radius: 0.72rem;
    font-weight: 700;
}

[data-testid="stDataFrame"] {
    overflow: hidden;
    border: 1px solid var(--sf-line);
    border-radius: 0.85rem;
    background: var(--sf-surface);
}

[data-baseweb="tab-list"] {
    gap: 0.25rem;
    margin-bottom: 0.8rem;
    padding: 0.28rem;
    border-radius: 0.78rem;
    background: #edf1f7;
}

button[data-baseweb="tab"] {
    min-height: 2.55rem;
    padding-inline: 1rem;
    border-radius: 0.62rem;
    color: var(--sf-ink-700);
    font-weight: 700;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: #ffffff;
    color: var(--sf-navy-950);
    box-shadow: 0 3px 10px rgba(32, 48, 76, 0.08);
}

button[data-baseweb="tab"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.85rem;
}

[data-testid="stExpander"] {
    overflow: hidden;
    border-color: var(--sf-line);
    border-radius: 0.85rem;
    background: rgba(255, 255, 255, 0.74);
}

.st-key-sf_about {
    margin-top: 1.5rem;
}

.sf-footer {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    margin-top: 2rem;
    padding: 1.2rem 0 0.25rem;
    border-top: 1px solid var(--sf-line);
    color: var(--sf-ink-500);
    font-size: 0.75rem;
}

.sf-footer strong {
    color: var(--sf-navy-800);
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

:is(button, a, input, textarea, [role="button"], [role="tab"]):focus-visible {
    outline: 3px solid var(--sf-focus) !important;
    outline-offset: 2px !important;
}

@media (max-width: 760px) {
    [data-testid="stMainBlockContainer"],
    .block-container {
        padding: 1.2rem 1rem 3rem;
    }

    .st-key-sf_hero {
        padding: 1.35rem;
        border-radius: 1.1rem;
    }

    .st-key-sf_hero h1 {
        font-size: clamp(2rem, 12vw, 3rem);
    }

    .st-key-sf_metrics [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    .st-key-sf_source_strip [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    .st-key-sf_source_strip [data-testid="stColumn"] {
        min-width: 100% !important;
        flex-basis: 100% !important;
    }

    .st-key-sf_metrics [data-testid="stColumn"] {
        min-width: calc(50% - 0.75rem) !important;
        flex: 1 1 calc(50% - 0.75rem) !important;
    }

    .st-key-sf_result_controls [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    .st-key-sf_result_controls [data-testid="stColumn"] {
        min-width: calc(50% - 0.75rem) !important;
        flex: 1 1 calc(50% - 0.75rem) !important;
    }

    .st-key-sf_result_controls [data-testid="stColumn"]:last-child {
        min-width: 100% !important;
        flex-basis: 100% !important;
    }

    .sf-footer {
        flex-direction: column;
    }
}

@media (max-width: 390px) {
    .st-key-sf_metrics [data-testid="stColumn"] {
        min-width: 100% !important;
        flex-basis: 100% !important;
    }

    .sf-trust-chip {
        width: 100%;
    }
}

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
    }
}
</style>
"""


_BRAND_MARK = """
<span class="sf-brand-mark" aria-hidden="true">
  <svg width="29" height="29" viewBox="0 0 29 29" fill="none"
       xmlns="http://www.w3.org/2000/svg" focusable="false">
    <circle cx="12.2" cy="12.2" r="7.25" stroke="white" stroke-width="2.3"/>
    <path d="M17.5 17.5L24 24" stroke="#65E4D7" stroke-width="2.8"
          stroke-linecap="round"/>
    <path d="M8.6 12.6L11.1 15L15.9 9.7" stroke="#65E4D7" stroke-width="2.1"
          stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</span>
"""


SIDEBAR_BRAND_HTML = f"""
<div class="sf-sidebar-brand">
  {_BRAND_MARK}
  <span>
    <strong>Sponsor Finder</strong>
    <small>UK sponsor intelligence</small>
  </span>
</div>
"""


HERO_EYEBROW_HTML = """
<div class="sf-eyebrow">
  <span class="sf-eyebrow-dot" aria-hidden="true"></span>
  UK sponsor intelligence
</div>
"""


HERO_LEDE_HTML = """
<p class="sf-hero-lede">
  Explore UK sponsor records with clearer evidence. Search by route, rating,
  location and candidate sector while keeping uncertainty visible.
</p>
"""


HERO_TRUST_HTML = """
<div class="sf-trust-chips" aria-label="Product principles">
  <span class="sf-trust-chip">Snapshot source kept visible</span>
  <span class="sf-trust-chip">Route-aware licence filters</span>
  <span class="sf-trust-chip">Sector matches labelled for verification</span>
</div>
"""


FOOTER_HTML = """
<footer class="sf-footer">
  <strong>Sponsor Finder</strong>
  <span>Open-source sponsor research · Verify current details before making decisions.</span>
</footer>
"""


def active_filter_labels(
    *,
    search: str,
    routes: Sequence[str],
    ratings: Sequence[str],
    towns: Sequence[str],
    sectors: Sequence[str],
    include_unknown_sectors: bool,
) -> list[str]:
    """Return concise, human-readable labels for result-changing filters."""
    labels: list[str] = []
    if search.strip():
        labels.append(f"Company · {search.strip()}")
    labels.extend(f"Route · {value}" for value in routes)
    labels.extend(f"Rating · {value}" for value in ratings)
    labels.extend(f"Location · {value}" for value in towns)
    labels.extend(f"Sector · {value}" for value in sectors)
    if not include_unknown_sectors:
        labels.append("Only records with sector data")
    return labels


def filter_chips_html(labels: Sequence[str]) -> str:
    """Render active filter labels after escaping all data-derived text."""
    count = len(labels)
    noun = "filter" if count == 1 else "filters"
    chips = "".join(
        f'<span class="sf-filter-chip">{escape(label, quote=True)}</span>' for label in labels
    )
    return (
        '<div class="sf-filter-chips" aria-label="Active search filters">'
        f'<span class="sf-filter-label">{count} active {noun}</span>{chips}</div>'
    )


def snapshot_badge_html(status: str, *, uploaded: bool = False) -> str:
    """Return a conservative status badge based on manifest metadata."""
    if uploaded:
        label = "Uploaded CSV · verify source and currency"
        tone = "warning"
    elif "legacy" in status.casefold():
        label = "Legacy snapshot · verify current licence"
        tone = "warning"
    else:
        label = "Repository snapshot · verify current licence"
        tone = "neutral"
    return (
        f'<span class="sf-status-badge sf-status-badge--{tone}">{escape(label, quote=True)}</span>'
    )


def safe_http_url(value: object) -> str:
    """Keep only absolute HTTP(S) links before handing values to a LinkColumn."""
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    return text
