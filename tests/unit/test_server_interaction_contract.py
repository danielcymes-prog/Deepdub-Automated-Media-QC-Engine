"""Regression tests for console interaction behaviour (polling, row navigation).

These lock four defects that route-level tests cannot see, because every one of
them returns a perfectly valid 200:

1.  The poller did ``region.innerHTML = fresh.innerHTML`` every 2s. On the job
    detail page the polled region *contains the Cancel button*, so an operator
    who tabbed to it lost focus to ``<body>`` every two seconds and could never
    activate it from the keyboard. It also destroyed any text selection.
2.  Job rows navigated via ``<tr onclick="location.href=…">``: invisible to the
    keyboard, swallowed ⌘/middle-click, and blocked by any CSP.
3.  Polling ran at the same rate with the window hidden, so a minimised RDP
    session kept forcing a full server-side page render every 2s per operator.
4.  ``Updated just now`` was a literal string regardless of age, and only
    reported trouble after three consecutive failures — a frozen queue read as a
    quiet one for ~6 seconds, which is exactly the state an operator would act
    on incorrectly.

These are static assertions over the checked-in templates and scripts. They
verify the *contract* that makes the correct behaviour possible; the behaviour
itself is exercised by the jsdom suite in tests/js/ (see ADR-023), which is not
yet wired into CI.
"""

import re
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent.parent / "src" / "deepdub_qc" / "server"
STATIC = SERVER / "static"
TEMPLATES = SERVER / "templates"

#: Every Jinja template in the console.
ALL_TEMPLATES = sorted(TEMPLATES.glob("*.html.j2"))

#: Inline handler attributes that a Content-Security-Policy would block.
INLINE_HANDLER_RE = re.compile(r"\son(click|submit|change|load|input|focus|blur)\s*=")


#: Matches a JS string literal (kept) or a comment (dropped). String alternatives
#: come first so a `//` inside a quoted URL is not mistaken for a comment.
_JS_TOKEN_RE = re.compile(
    r"\"(?:\\.|[^\"\\])*\"" r"|'(?:\\.|[^'\\])*'" r"|/\*.*?\*/" r"|//[^\n]*",
    re.S,
)


def _js_code_only(js: str) -> str:
    """Strip JS comments, preserving string literals.

    Necessary because these tests assert that defect patterns are *absent*, and
    the fixed source documents each defect verbatim in a comment. Without this,
    the explanation of a bug reads as the bug.
    """
    return _JS_TOKEN_RE.sub(
        lambda m: m.group(0) if m.group(0)[0] in "\"'" else " ",
        js,
    )


def _jinja_code_only(html: str) -> str:
    """Strip ``{# … #}`` comments, for the same reason as _js_code_only."""
    return re.sub(r"\{#.*?#\}", " ", html, flags=re.S)


@pytest.fixture(scope="module")
def app_js() -> str:
    """app.js with comments removed — assertions target real code only."""
    return _js_code_only((STATIC / "app.js").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def app_js_raw() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (STATIC / "app.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jobs_html() -> str:
    return (TEMPLATES / "jobs.html.j2").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. No inline event handlers anywhere (CSP + keyboard reachability)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda p: p.name)
def test_no_inline_event_handlers(template: Path) -> None:
    """Inline JS is unreachable by keyboard when on a <tr> and dies under a CSP."""
    source = _jinja_code_only(template.read_text(encoding="utf-8"))
    found = INLINE_HANDLER_RE.findall(source)
    assert not found, (
        f"{template.name} uses inline on{found[0]}=; bind it in app.js instead "
        "(rows use a real anchor, forms use data-confirm)"
    )


def test_destructive_forms_declare_a_confirmation_message() -> None:
    """Cancelling a running job discards analysis work — it must be confirmed."""
    html = (TEMPLATES / "job_detail.html.j2").read_text(encoding="utf-8")
    cancel_forms = re.findall(r"<form[^>]*?/cancel\"[^>]*?>", html, re.S)
    assert cancel_forms, "no cancel form found — did the action move?"
    for form in cancel_forms:
        assert "data-confirm=" in form, f"cancel form has no data-confirm: {form!r}"


def test_app_js_binds_confirmation_by_delegation(app_js: str) -> None:
    """Delegation, so forms introduced by a poll refresh are covered too."""
    assert "form[data-confirm]" in app_js
    assert 'addEventListener("submit"' in app_js


# --------------------------------------------------------------------------
# 2. Rows navigate via real anchors (ADR-016 follow-on)
# --------------------------------------------------------------------------


def test_job_rows_navigate_via_a_real_anchor(jobs_html: str) -> None:
    assert 'class="row-link"' in jobs_html, "job rows have no anchor"
    anchor = re.search(r'<a class="row-link"[^>]*>', jobs_html)
    assert anchor and "href=" in anchor.group(0), (
        "row-link must carry a real href so ⌘-click and middle-click work"
    )


def test_row_link_has_an_accessible_description(jobs_html: str) -> None:
    """A link whose only text is "a3f9c1d2…" tells a screen reader nothing."""
    block = re.search(r'<a class="row-link".*?</a>', jobs_html, re.S).group(0)
    assert "visually-hidden" in block, "row-link needs a hidden descriptive label"


def test_pointer_cursor_is_scoped_to_tables_whose_rows_navigate(css: str) -> None:
    """The presets table must not advertise a click that does nothing."""
    generic = re.search(r"\.data-table tbody tr:hover\s*\{([^}]*)\}", css, re.S)
    assert generic, "row hover rule is missing"
    assert "cursor" not in generic.group(1), (
        "cursor: pointer on every .data-table row is a false affordance; scope it to .rows-linked"
    )
    assert ".data-table.rows-linked tbody tr:hover { cursor: pointer; }" in css


def test_only_the_jobs_table_opts_into_row_linking() -> None:
    linked = {
        path.name
        for path in ALL_TEMPLATES
        if "rows-linked" in _jinja_code_only(path.read_text(encoding="utf-8"))
    }
    assert linked == {"jobs.html.j2"}, (
        f"unexpected rows-linked tables: {linked}; presets rows do not navigate"
    )


def test_visually_hidden_utility_is_defined(css: str) -> None:
    """Templates rely on it for captions, column headers and row descriptions."""
    rule = re.search(r"\.visually-hidden\s*\{([^}]*)\}", css, re.S)
    assert rule, ".visually-hidden is used in templates but not defined in CSS"
    body = rule.group(1)
    # display:none / visibility:hidden would hide it from screen readers too.
    assert "display: none" not in body
    assert "visibility: hidden" not in body
    assert "position: absolute" in body


# --------------------------------------------------------------------------
# 3. Polling preserves focus, is keyed, and pauses when hidden
# --------------------------------------------------------------------------


def test_poller_does_not_replace_the_whole_region(app_js: str) -> None:
    """The defect verbatim: it wiped focus and selection every two seconds."""
    assert "region.innerHTML = fresh.innerHTML" not in app_js, (
        "wholesale innerHTML replacement destroys keyboard focus; patch instead"
    )


def test_poller_checks_for_the_focused_element(app_js: str) -> None:
    assert "document.activeElement" in app_js, (
        "the poller must know where focus is before mutating the DOM"
    )


def test_poller_keys_rows_by_job_id(app_js: str, jobs_html: str) -> None:
    """Row identity is what lets cells be patched without rebuilding the table."""
    assert "data-job-id" in jobs_html, "job rows carry no stable key"
    assert "data-job-id" in app_js, "the poller does not key rows by job id"


def test_only_volatile_cells_are_marked_for_patching(jobs_html: str) -> None:
    """id, filename, preset and requester are fixed for a job's lifetime."""
    cells = set(re.findall(r'data-cell="(\w+)"', jobs_html))
    assert cells == {"state", "verdict"}, (
        f"unexpected volatile cells {cells}; only state and verdict change"
    )


def test_polling_pauses_while_the_window_is_hidden(app_js: str) -> None:
    assert 'document.visibilityState === "hidden"' in app_js, (
        "a minimised RDP session should not force a full page render every 2s"
    )
    assert 'addEventListener("visibilitychange"' in app_js, (
        "the view must catch up immediately when it becomes visible again"
    )


# --------------------------------------------------------------------------
# 4. Freshness is measured, not asserted
# --------------------------------------------------------------------------


def test_freshness_caption_is_derived_from_the_last_successful_poll(app_js: str) -> None:
    assert "lastSuccess" in app_js, "caption age must come from a real timestamp"
    assert "Updated just now · auto-refresh" not in app_js, (
        "the caption was a literal string that claimed freshness unconditionally"
    )


def test_stale_state_is_reported_on_the_first_failure(app_js: str) -> None:
    """`failures >= 3` meant a dead console looked healthy for ~6 seconds."""
    assert "failures >= 3" not in app_js
    assert re.search(r"stale\s*=\s*true", app_js), "no stale flag set on failure"


def test_stale_caption_is_visually_distinct(css: str) -> None:
    rule = re.search(r"\.poll-caption\.stale\s*\{([^}]*)\}", css, re.S)
    assert rule, "a stale caption must not look like a fresh one"
    assert "--qc-warning" in rule.group(1)


# --------------------------------------------------------------------------
# 5. Live regions announce progress without re-reading history
# --------------------------------------------------------------------------


def test_stage_list_is_not_itself_a_live_region() -> None:
    """It was aria-live and replaced wholesale, so every completed stage was
    re-announced on every 2s poll — unusable during a long analysis."""
    html = (TEMPLATES / "job_detail.html.j2").read_text(encoding="utf-8")
    stage_list = re.search(r'<ul class="stage-list"[^>]*>', html)
    assert stage_list, "stage list is missing"
    assert "aria-live" not in stage_list.group(0), (
        "the history list must not be a live region; announce the current stage"
    )


def test_a_single_line_live_region_carries_current_stage() -> None:
    html = (TEMPLATES / "job_detail.html.j2").read_text(encoding="utf-8")
    status = re.search(r"<p[^>]*data-stage-status[^>]*>", html)
    assert status, "no stage status live region"
    assert 'aria-live="polite"' in status.group(0)
    assert 'role="status"' in status.group(0)


def test_live_region_is_mutated_in_place_not_replaced(app_js: str, app_js_raw: str) -> None:
    """Replacing a live region element is unreliably announced across readers."""
    assert "data-stage-status" in app_js, "the poller does not patch the live region"
    patch = re.search(r"function patchLiveRegions\(.*?\n  \}", app_js_raw, re.S)
    assert patch, "patchLiveRegions is missing"
    assert "textContent" in patch.group(0), "live region must be updated by text"


# --------------------------------------------------------------------------
# 6. Table and pagination semantics
# --------------------------------------------------------------------------


@pytest.mark.parametrize("template", ["jobs.html.j2", "presets.html.j2"], ids=str)
def test_data_tables_declare_header_scope_and_a_caption(template: str) -> None:
    html = (TEMPLATES / template).read_text(encoding="utf-8")
    headers = re.findall(r"<th\b[^>]*>", html)
    assert headers, f"{template} has no table headers"
    for header in headers:
        assert "scope=" in header, f"{template}: <th> without scope: {header!r}"
    assert "<caption" in html, f"{template}: table has no caption"


def test_pagination_marks_the_current_page_semantically(jobs_html: str) -> None:
    """`<strong>` conveys emphasis, not location."""
    assert 'aria-label="Jobs pagination"' in jobs_html
    current = re.search(r'<span class="page-current"[^>]*>', jobs_html)
    assert current and 'aria-current="page"' in current.group(0), (
        "current page must be marked with aria-current, not <strong>"
    )


def test_presets_page_has_an_empty_state() -> None:
    """An unreadable presets_root rendered bare column headers with no clue."""
    html = (TEMPLATES / "presets.html.j2").read_text(encoding="utf-8")
    assert "empty-state" in html, "presets has no empty state (jobs does)"
    assert "presets_root" in html, "the empty state should name the setting to check"


def test_preset_description_is_not_title_attribute_only() -> None:
    """A title tooltip is unreachable by keyboard and invisible on touch."""
    html = (TEMPLATES / "presets.html.j2").read_text(encoding="utf-8")
    assert 'title="{{ p.description }}"' not in html, (
        "render the description inline; a title attribute is not accessible"
    )
    assert "cell-caption" in html
