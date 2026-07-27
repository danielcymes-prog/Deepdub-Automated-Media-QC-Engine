"""Regression tests for the console shell's static assets and brand chrome.

These lock four defects that were shipped in the Phase 3.5 console and are all
invisible to the existing route tests, because a page can return 200 with
perfectly valid markup while still rendering in the wrong font at the wrong
aspect ratio:

1.  ``--font-ui`` named 'Onest' but no ``@font-face`` or font link existed
    anywhere, so the console rendered in the system fallback (ADR-015).
2.  ``wordmark.svg`` carried intrinsic ``em`` dimensions that resolve against
    the *parent* font-size rather than the height CSS sets, stretching the
    Deepdub mark ~13% horizontally.
3.  ``.shell-header`` height and ``.data-table th``'s sticky ``top`` were two
    independent ``60px`` literals that must agree or sticky table headers slide
    underneath the app bar (ADR-016).
4.  The active nav underline used violet, colliding with ``--qc-error``'s
    reserved "pipeline could not finish" meaning (ADR-016).

Everything here is a static assertion over the checked-in asset text. There is
no browser in CI, so these tests deliberately verify the *contract* that makes
correct rendering possible rather than pixels.
"""

import re
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent.parent / "src" / "deepdub_qc" / "server"
STATIC = SERVER / "static"
TEMPLATES = SERVER / "templates"

#: Templates that render a full HTML document and therefore need the font links.
SHELL_TEMPLATES = ("base.html.j2", "cap.html.j2")


@pytest.fixture(scope="module")
def css() -> str:
    return (STATIC / "app.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wordmark() -> str:
    return (STATIC / "wordmark.svg").read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    """Drop /* … */ blocks so prose about CDNs isn't mistaken for a CDN import."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _root_token(css: str, name: str) -> str:
    """Return the value of a custom property declared in :root."""
    match = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", css, re.M)
    assert match, f"{name} is not declared in app.css"
    return match.group(1).strip()


# --------------------------------------------------------------------------
# 1. Fonts are self-hosted and actually loaded (ADR-015)
# --------------------------------------------------------------------------


def test_every_font_family_named_in_a_token_has_a_font_face_rule(css: str) -> None:
    """A font stack that names a family nobody loads is a silent fallback."""
    face_families = set(re.findall(r"@font-face\s*\{[^}]*?font-family:\s*'([^']+)'", css, re.S))
    for token in ("--font-ui", "--font-mono"):
        first = _root_token(css, token).split(",")[0].strip().strip("'\"")
        assert first in face_families, (
            f"{token} leads with {first!r} but app.css declares no @font-face for it; "
            "the console will silently render in the next stack entry"
        )


def test_font_files_referenced_by_css_exist_on_disk(css: str) -> None:
    urls = re.findall(r"url\('(fonts/[^']+)'\)", css)
    assert urls, "no local font files referenced — did this regress to a CDN @import?"
    for url in urls:
        path = STATIC / url
        assert path.is_file(), f"{url} is referenced by app.css but missing from static/"
        assert path.stat().st_size > 0, f"{url} is empty"


def test_console_css_makes_no_outbound_font_request(css: str) -> None:
    """ADR-014 forbids CDN assets; the RDP host may have no egress at all."""
    declarations = _strip_comments(css)
    assert "fonts.googleapis.com" not in declarations
    assert "fonts.gstatic.com" not in declarations
    assert "@import" not in declarations
    assert "//" not in re.sub(r"url\('fonts/", "", declarations), (
        "no protocol-relative or absolute URLs may appear in console CSS"
    )


def test_font_faces_span_the_weights_the_type_scale_asks_for(css: str) -> None:
    """The scale uses 550/650, which only a variable axis can render."""
    declared = re.findall(r"font-weight:\s*(\d+)\s+(\d+)\s*;", css)
    assert declared, "no variable-weight @font-face ranges found"
    used = {int(w) for w in re.findall(r"font-weight:\s*(\d{3})\s*;", css)}
    for weight in sorted(used):
        assert any(int(lo) <= weight <= int(hi) for lo, hi in declared), (
            f"font-weight: {weight} is used but no @font-face range covers it; "
            "a static instance would round or synthesise it"
        )


@pytest.mark.parametrize("template", SHELL_TEMPLATES)
def test_shell_templates_preload_the_ui_font(template: str) -> None:
    html = (TEMPLATES / template).read_text(encoding="utf-8")
    assert 'rel="preload"' in html, f"{template} does not preload any font"
    assert "onest-latin-wght-normal.woff2" in html
    # crossorigin is mandatory on font preloads even same-origin, or the
    # browser fetches the file twice and the preload is wasted.
    for tag in re.findall(r"<link[^>]*rel=\"preload\"[^>]*>", html, re.S):
        assert "crossorigin" in tag, f"{template}: font preload missing crossorigin"
        assert 'as="font"' in tag


def test_vendored_fonts_ship_their_licences() -> None:
    fonts = STATIC / "fonts"
    assert fonts.is_dir(), "static/fonts/ is missing — fonts are not self-hosted"
    families = {p.name.split("-latin")[0] for p in fonts.glob("*.woff2")}
    assert families, "no woff2 files vendored; ADR-015 requires self-hosted faces"

    licences = list(fonts.glob("LICENSE-*.txt"))
    assert len(licences) >= len(families), (
        f"{len(families)} vendored families ({sorted(families)}) but only "
        f"{len(licences)} licence file(s); each family needs its licence committed"
    )
    for licence in licences:
        assert "SIL Open Font License" in licence.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 2. The wordmark cannot be stretched (aspect-ratio regression)
# --------------------------------------------------------------------------


def test_wordmark_svg_declares_no_intrinsic_dimensions(wordmark: str) -> None:
    """``width: 6.625em`` resolved against the parent font-size, not our height,
    so setting height alone stretched the mark ~13% wider than the viewBox."""
    opening = wordmark[: wordmark.index(">") + 1]
    assert "viewBox=" in opening, "viewBox is the only sanctioned size source"
    assert not re.search(r"\b(width|height)=", opening), (
        f"wordmark.svg re-declares intrinsic dimensions: {opening!r}"
    )


def test_css_pins_the_wordmark_to_its_viewbox_ratio(css: str, wordmark: str) -> None:
    view_box = re.search(r'viewBox="([\d.\s-]+)"', wordmark).group(1).split()
    intrinsic = float(view_box[2]) / float(view_box[3])

    rule = re.search(r"\.wordmark img[^{]*\{([^}]*)\}", css, re.S)
    assert rule, ".wordmark img rule is missing"
    body = rule.group(1)

    ratio = re.search(r"aspect-ratio:\s*([\d.]+)\s*/\s*([\d.]+)", body)
    assert ratio, "no aspect-ratio: the mark can be distorted by a lone height"
    assert float(ratio.group(1)) / float(ratio.group(2)) == pytest.approx(intrinsic), (
        "CSS aspect-ratio has drifted from the SVG viewBox ratio"
    )
    assert re.search(r"width:\s*auto", body), (
        "width must be auto so the pinned ratio drives it from height"
    )


# --------------------------------------------------------------------------
# 3. Shell geometry is token-derived, not duplicated literals (ADR-016)
# --------------------------------------------------------------------------


def test_sticky_table_header_offset_tracks_the_shell_header_token(css: str) -> None:
    """Two hardcoded 60px values drifting apart hides column headers on scroll."""
    _root_token(css, "--shell-header-h")

    header = re.search(r"\.shell-header\s*\{([^}]*)\}", css, re.S).group(1)
    assert "var(--shell-header-h)" in header, ".shell-header height must use the token"

    th = re.search(r"\.data-table th\s*\{([^}]*)\}", css, re.S).group(1)
    top = re.search(r"top:\s*([^;]+);", th)
    assert top, ".data-table th has no sticky top offset"
    assert "var(--shell-header-h)" in top.group(1), (
        f"sticky offset is {top.group(1).strip()!r}, not derived from "
        "--shell-header-h; it will drift when the header height changes"
    )


def test_header_and_main_share_the_content_column(css: str) -> None:
    """Without a shared container the wordmark never aligns with page content."""
    for token in ("--content-max", "--content-pad"):
        _root_token(css, token)

    inner = re.search(r"\.shell-header-inner\s*\{([^}]*)\}", css, re.S)
    assert inner, "no .shell-header-inner container"
    main = re.search(r"^main\s*\{([^}]*)\}", css, re.S | re.M).group(1)

    for name, body in (("shell-header-inner", inner.group(1)), ("main", main)):
        assert "var(--content-max)" in body, f"{name} does not use --content-max"
        assert "var(--content-pad)" in body, f"{name} does not use --content-pad"


def test_base_template_wraps_header_contents_in_the_container() -> None:
    html = (TEMPLATES / "base.html.j2").read_text(encoding="utf-8")
    header = re.search(r"<header[^>]*>(.*?)</header>", html, re.S).group(1)
    assert "shell-header-inner" in header
    # wordmark, nav and health must all be inside the constrained container
    inner = header[header.index("shell-header-inner") :]
    for fragment in ("wordmark", "<nav", 'id="health-dot"'):
        assert fragment in inner, f"{fragment} sits outside .shell-header-inner"


# --------------------------------------------------------------------------
# 4. Status colours stay reserved; state is never colour-only (ADR-016)
# --------------------------------------------------------------------------


def test_nav_active_underline_uses_the_brand_accent_not_a_verdict_colour(css: str) -> None:
    rule = re.search(r"\.shell-header nav a\.active::after\s*\{([^}]*)\}", css, re.S)
    assert rule, "active nav item has no underline"
    background = re.search(r"background:\s*([^;]+);", rule.group(1)).group(1).strip()
    assert background == "var(--dd-accent)", (
        f"active underline is {background!r}; navigation chrome must use the brand "
        "accent so the verdict palette keeps a 1:1 colour-to-meaning mapping"
    )
    reserved = ("--qc-error", "--dd-violet", "--qc-pass", "--qc-warning", "--qc-fail")
    assert not any(token in background for token in reserved)


def test_nav_active_state_is_not_conveyed_by_colour_alone(css: str) -> None:
    """WCAG 1.4.1: the underline plus a weight step, not hue on its own."""
    base = re.search(r"\.shell-header nav a\s*\{([^}]*)\}", css, re.S).group(1)
    active = re.search(r"\.shell-header nav a\.active\s*\{([^}]*)\}", css, re.S).group(1)
    base_weight = re.search(r"font-weight:\s*(\d+)", base)
    active_weight = re.search(r"font-weight:\s*(\d+)", active)
    assert base_weight and active_weight, "nav links need explicit weights to differ"
    assert int(active_weight.group(1)) > int(base_weight.group(1))


def test_health_indicator_has_a_text_label_not_just_a_coloured_dot() -> None:
    html = (TEMPLATES / "base.html.j2").read_text(encoding="utf-8")
    health = re.search(r'<span class="health"[^>]*>(.*?)</span>\s*</span>', html, re.S)
    assert health, "health indicator markup changed shape"
    assert health.group(1).strip(), "health status has no text label"

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "textContent" in js, "app.js must update the label, not only the title"

    css_text = (STATIC / "app.css").read_text(encoding="utf-8")
    dot = re.search(r"\.health::before\s*\{([^}]*)\}", css_text, re.S)
    assert dot, "the dot should be a pseudo-element so markup carries the label"


def test_active_nav_item_is_marked_for_assistive_tech() -> None:
    """The underline is visual only; aria-current carries it to a screen reader."""
    html = (TEMPLATES / "base.html.j2").read_text(encoding="utf-8")
    assert 'aria-current="page"' in html
    assert 'class=""' not in html, "empty class attribute leaked from a Jinja expression"
