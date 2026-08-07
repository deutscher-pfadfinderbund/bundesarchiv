"""Canonical E2E journeys (Part #26) — the common flows written ONCE, driven in a real browser.

Each test walks a whole flow through the live app (server + Postgres index + browser), so a review no
longer re-derives them by hand. Marked ``e2e`` (excluded from the default run; ``-m e2e`` to run).
The ``archivist_page`` / ``public_page`` fixtures (conftest) carry the right viewer cookie; the
corpus is the canonical one from ``_corpus``.

Journeys: search+filter+pane · create draft · edit+save · CAS conflict (two contexts) · Kopieren
loop · Löschen confirm · publish preview gate · bulk select→confirm→partial result.
"""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Page, Route, expect
from pytest_django.plugin import DjangoDbBlocker
from tests.e2e._corpus import CorpusHandles

pytestmark = pytest.mark.e2e


# --- search + filter + pane --------------------------------------------------------


def test_search_filter_and_open_pane(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    page.goto(live_workbench + "/")
    # the ledger shows the corpus
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).to_be_visible()
    # filter by a tag facet (Schlagworte: sommer) narrows to the one article
    page.goto(live_workbench + "/?schlagwort=sommer")
    expect(page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(page.get_by_text("Herbstlager 1963")).not_to_be_visible()
    # the pane opens via the row's explicit Vorschau action (one-click model: the Titel itself
    # navigates to the detail page; the pane is never a toll gate) and keeps the search state
    page.get_by_role("link", name="Vorschau", exact=True).first.click()
    expect(page.locator(".pane")).to_be_visible()
    expect(page.locator(".pane h2")).to_have_text("Sommerfahrt 1962")
    assert "schlagwort=sommer" in page.url and "artikel=" in page.url  # URL-borne pane state
    # ✕ closes the pane and keeps the filter
    page.get_by_label("Vorschau schließen").click()
    expect(page.locator(".pane")).not_to_be_visible()
    assert "schlagwort=sommer" in page.url


def test_ledger_headers_compute_one_uniform_treatment(
    archivist_page: Page, live_workbench: str
) -> None:
    # Learning G.1: a comment is not a proof; the computed style is. Every [role=columnheader]
    # AND every anchor inside one must compute the SAME font treatment (the label role) — the
    # sortable-head link may differ only by affordance, never by typography.
    archivist_page.goto(live_workbench + "/")
    treatments: list[str] = archivist_page.evaluate(
        """() => Array.from(document.querySelectorAll(
               '.ledger [role=columnheader], .ledger [role=columnheader] a'
           )).map((el) => {
               const s = getComputedStyle(el);
               return [s.fontSize, s.fontWeight, s.fontFamily, s.textTransform,
                       s.letterSpacing, s.color].join('|');
           })"""
    )
    assert len(treatments) >= 5  # four column heads + at least one sortable-head anchor
    assert len(set(treatments)) == 1, f"non-uniform header treatments: {sorted(set(treatments))}"


#: The generic control-row walker (design-review-law E, mandatory; learning G.21: invariants are
#: WALKERS over all instances). Enumerates EVERY control row on the page — the header's control
#: cluster, the filter rail, each [role=toolbar] — and for each row returns its controls'
#: computed heights + font treatments. A "control" is a button, a summary, or a chip (the rail's
#: clear-all link is text, not a control); inside a toolbar the icon links ARE the controls.
#: A new control row (or a new control in an existing row) is covered the day it appears —
#: per-instance copies of this proof are forbidden.
_CONTROL_ROW_WALKER_JS = """() => {
    const rows = [
        ['header', document.querySelector('body > header')],
        ['filterrail', document.querySelector('.filterrail')],
        ...Array.from(document.querySelectorAll('[role=toolbar]')).map(
            (el, i) => ['toolbar-' + i, el]),
    ].filter(([, el]) => el);
    return rows.map(([name, row]) => {
        const selector = row.matches('[role=toolbar]')
            ? 'a, button' : 'button, a.button, summary, .chip';
        const controls = Array.from(row.querySelectorAll(selector))
            .filter((el) => el.offsetParent !== null)  // rendered only (closed dropdowns skip)
            .map((el) => {
                const s = getComputedStyle(el);
                return {
                    label: (el.getAttribute('aria-label') || el.textContent).trim(),
                    chip: el.matches('.chip'),
                    height: el.offsetHeight,
                    font: [s.fontSize, s.fontWeight, s.fontFamily, s.textTransform,
                           s.letterSpacing].join('|'),
                };
            });
        return {name, controls};
    });
}"""


def test_control_rows_compute_one_height_source(archivist_page: Page, live_workbench: str) -> None:
    # Law C8 proven computed (the generalized G.1 pattern, section E): within EVERY control row,
    # all controls compute the SAME height (offsetHeight within 1px — one --control-height source,
    # equal by construction) and — chips excepted, which keep chip typography but must still match
    # height — the same font treatment. Driven on the filtered workbench so the rail carries
    # chips + dropdowns and the ledger carries row toolbars in one shot.
    page = archivist_page
    page.goto(live_workbench + "/?schlagwort=sommer")
    rows: list[dict[str, list[dict[str, str | int | bool]]]] = page.evaluate(_CONTROL_ROW_WALKER_JS)
    by_name = {str(row["name"]): row["controls"] for row in rows}
    # the walker must actually see the rows this page composes — a silent no-find proves nothing
    assert "header" in by_name and "filterrail" in by_name
    assert len(by_name["header"]) >= 2  # the Suchen button + the "+ Neu …" summary
    assert any(c["chip"] for c in by_name["filterrail"])  # the active-filter chip is present
    assert any(name.startswith("toolbar-") for name in by_name)  # ledger row toolbars
    defects: list[str] = []
    for name, controls in by_name.items():
        if len(controls) < 2:
            continue  # nothing to compare within this row
        heights = {str(c["label"]): int(str(c["height"])) for c in controls}
        if max(heights.values()) - min(heights.values()) > 1:
            defects.append(f"row '{name}' computes more than one height: {heights}")
        fonts = {c["font"] for c in controls if not c["chip"]}
        if len(fonts) > 1:
            defects.append(f"row '{name}' computes mixed control fonts: {fonts}")
    assert not defects, "control rows violating C8 (one height source):\n" + "\n".join(defects)


def test_treffer_count_rides_the_rail_and_stays_live(
    archivist_page: Page, live_workbench: str
) -> None:
    # Law C10 (owner round-2 correction 2026-08-07): the "N Treffer" count rides the filter
    # rail's line — the occupied band — and the status-only toolrow is gone. The rail lives
    # OUTSIDE the #results swap target, so the htmx type-to-search swap must refresh the count
    # out-of-band: type a narrowing q and watch the RAIL's count change without navigation.
    page = archivist_page
    page.goto(live_workbench + "/")
    count = page.locator(".filterrail #trefferzahl")
    expect(count).to_have_text("3 Treffer")  # the canonical corpus, archivist-scoped
    # real keystrokes (the hx-trigger is keyup; fill() sets the value without key events)
    page.locator('input[name="q"]').press_sequentially("Sommerfahrt")
    expect(count).to_have_text("1 Treffer")  # refreshed out-of-band, no full navigation
    assert "q=Sommerfahrt" in page.url  # it was the hx swap (pushed URL), not a page load
    # zero hits: the rail still renders, the count stays on its line (the rail is the one place)
    page.goto(live_workbench + "/?q=zzzznomatch")
    expect(page.locator(".filterrail #trefferzahl")).to_have_text("0 Treffer")


def test_pane_open_never_folds_the_ledger(archivist_page: Page, live_workbench: str) -> None:
    # Decision 1 (owner 2026-08-07), proven computed (learning G.1): at the NARROWEST viewport
    # that still shows the pane (the 80rem switch = 1280px at default root font), the pane-open
    # ledger keeps its one-line row anatomy — the header row stays visible (the phone fold is
    # the only state that hides it) and the low-priority columns merely drop.
    page = archivist_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(live_workbench + "/")
    page.get_by_role("link", name="Vorschau", exact=True).first.click()
    expect(page.locator(".pane")).to_be_visible()
    header_row = page.locator('.ledger [role="table"] > [role="row"]')
    expect(header_row).to_be_visible()  # the fold's signature is a hidden header row


def test_public_never_sees_a_draft(public_page: Page, live_workbench: str) -> None:
    # the leak spine, end to end: a public visitor's workbench shows the published articles but never
    # the draft (search scopes it out) and no archivist chrome (no bulk column, no "+ Neu …" create
    # disclosure — Mock B, owner 2026-08-07).
    public_page.goto(live_workbench + "/")
    expect(public_page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(public_page.get_by_text("Lagerchronik")).not_to_be_visible()  # the draft's title
    expect(public_page.locator("details.menu")).to_have_count(0)


# --- detail read view (4.6) --------------------------------------------------------


def test_detail_read_from_search_result(public_page: Page, live_workbench: str) -> None:
    page = public_page
    # a member/public visitor: the Titel click IS the navigation to the Lesesaal detail read view
    # (one-click entry, owner 2026-08-07 — no pane interception, no JS in the loop).
    page.goto(live_workbench + "/")
    page.locator(".ledger .titel a", has_text="Sommerfahrt 1962").click()
    page.wait_for_url("**/artikel/**")
    # the reading structure: title, record card facts (Signatur + human + mono date), the cover
    expect(page.locator("main h1")).to_have_text("Sommerfahrt 1962")
    expect(page.locator("main header p")).to_have_text("Juli 1962")  # human German under the title
    expect(page.locator(".facts dd.mono").first).to_have_text("1962-07")  # mono machine date
    expect(page.get_by_text("F 12")).to_be_visible()  # Signatur
    expect(page.locator("main figure img")).to_be_visible()  # cover Platte
    expect(page.locator(".filmstrip > div > a")).to_have_count(2)  # cover + one further plate
    # a plate links its gated media byte route; Zurück returns to the search
    href = page.locator(".filmstrip > div > a").first.get_attribute("href")
    assert href is not None and href.startswith("/media/")
    page.get_by_text("Zurück zur Suche").click()
    page.wait_for_url(lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/")))


# --- create a Bestand (4.8) --------------------------------------------------------


def test_create_bestand_then_file_an_article_under_it(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # "+ Neu …" → Neuer Bestand → fill Name → Anlegen → LAND on the create-article form
    # (create→catalog is one flow), the new Bestand pre-selected + a success hinweis. File the
    # first article under it. The create actions live in the header's ONE quiet disclosure
    # (Mock B, owner 2026-08-07) — a native <details>, opened by a plain click.
    page.goto(live_workbench + "/")
    page.click("details.menu > summary")
    page.get_by_role("link", name="Neuer Bestand").click()
    page.wait_for_url("**/bestand/neu")
    page.fill('input[name="name"]', "Plakate")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/artikel/neu?**")  # 302 to the create-article form, not the workbench
    expect(page.get_by_text("Bestand „Plakate“ angelegt.")).to_be_visible()  # success hinweis
    expect(page.locator('select[name="collection_id"]')).to_contain_text("Plakate")
    page.fill('input[name="title"]', "Ein Plakat")  # the new Bestand is already pre-selected
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    # now the Bestand has an article, so it appears in the workbench's Bestand filter dropdown
    # (the rail is the primary filter interaction — open the group to see its values)
    page.goto(live_workbench + "/")
    page.locator(".filterrail summary", has_text="Bestand").click()
    expect(page.locator(".facet a", has_text="Plakate")).to_be_visible()


# --- create a draft ----------------------------------------------------------------


def _create_draft(page: Page, base: str, title: str) -> str:
    """Drive the create step (Titel + Bestand → Anlegen) then set the required Medienart on the edit
    form, so the draft is saveable/publishable. Returns the new draft's edit-form URL."""
    page.goto(base + "/artikel/neu")
    page.fill('input[name="title"]', title)
    page.select_option('select[name="collection_id"]', "FOTOS")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    # Medienart is required to save/publish (spec §3) — set it so downstream steps aren't blocked.
    page.select_option('select[name="media_type"]', "Fotografie")
    return page.url


def test_create_draft_lands_on_edit_form(archivist_page: Page, live_workbench: str) -> None:
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Neuer Entwurf")
    assert "/bearbeiten" in edit_url
    # the edit form is seeded with the new title + shows the ENTWURF header badge
    expect(archivist_page.locator('input[name="title"]')).to_have_value("E2E Neuer Entwurf")
    expect(archivist_page.get_by_text("Entwurf", exact=True).first).to_be_visible()


# --- edit + save -------------------------------------------------------------------


def test_edit_and_save_redirects_to_read_view(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Bearbeiten")
    page.fill('input[name="creator"]', "K. Meyer")
    page.fill('input[name="ref_code"]', "E2E-1")
    page.click('button:has-text("Speichern")')
    # save 302s to the read view (the detail stub in this slice)
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url


def test_failed_save_banner_leaves_speichern_clickable(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # A failed save reveals the global error banner, fixed at the viewport bottom — the SAME edge the
    # sticky footer's Speichern docks at. The banner must lift the footer, never cover it: the retry
    # button has to stay clickable exactly when the archivist needs it (design-gate finding).
    _create_draft(page, live_workbench, "E2E Fehlschlag")

    def fail_saves(route: Route) -> None:
        # abort only the save POSTs; the edit page's own GET (same URL) must keep loading normally
        if route.request.method == "POST":
            route.abort()
        else:
            route.fallback()

    page.route("**/bearbeiten", fail_saves)
    page.click('button:has-text("Speichern")')  # htmx sendError → the banner reveals
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()
    # THE assertion, at the natural post-failure scroll position (footer stuck at the viewport
    # bottom, exactly where the banner sits): a real browser hit-test at Speichern's center must
    # reach the button, and the footer must sit clear above the banner. A bare page.click cannot
    # pin this — Playwright's actionability retry rescues an occluded sticky-bottom element by
    # scrolling the page to the very bottom, where the footer un-sticks above the banner and the
    # click lands anyway (verified against the unfixed CSS).
    state = page.evaluate(
        """() => {
        const banner = document.querySelector('.error-banner');
        const btn = document.querySelector('footer.sticky button.primary');
        const footer = document.querySelector('footer.sticky');
        const b = banner.getBoundingClientRect();
        const f = footer.getBoundingClientRect();
        const r = btn.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return {
            speichernHit: btn === hit || btn.contains(hit),
            footerBottom: f.bottom,
            bannerTop: b.top,
        };
    }"""
    )
    assert state["speichernHit"], "the error banner paints over Speichern (hit-test misses)"
    assert state["footerBottom"] <= state["bannerTop"] + 1, (
        f"the sticky footer overlaps the banner: footer bottom {state['footerBottom']}px "
        f"vs banner top {state['bannerTop']}px"
    )
    # and the retry itself works end to end: the second Speichern fires another save while the
    # banner stays visible through it (the error is never sacrificed to keep the button clickable)
    page.click('button:has-text("Speichern")', timeout=5000)
    expect(page.get_by_text("Aktion fehlgeschlagen. Bitte erneut versuchen.")).to_be_visible()


# --- dirty register (PE) -----------------------------------------------------------


def test_dirty_register_covers_fields_outside_the_form_subtree(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # Custom-bag fields are form= ASSOCIATED with #bearbeiten-form but sit outside its
    # DOM subtree (the #medien-drawer split) — the dirty register must still see their first edit.
    edit_url = _create_draft(page, live_workbench, "E2E Ungespeichert")
    page.goto(edit_url)  # fresh load: _create_draft's Medienart pick already revealed the chip
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.click('summary:has-text("Weitere Angaben")')
    page.fill('input[name="custom_key"]', "Quelle")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()
    # and the plain path still works: a Gruppe-1 field inside the form reveals it too
    page.goto(edit_url)
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_hidden()
    page.fill('input[name="title"]', "E2E Ungespeichert 2")
    expect(page.get_by_text("Nicht gespeicherte Änderungen")).to_be_visible()


# --- CAS conflict (two contexts) ---------------------------------------------------


def test_cas_conflict_second_saver_sees_panel(
    archivist_page: Page, live_workbench: str, browser: Browser
) -> None:
    # Two archivists open the SAME draft edit form at the same version; the first save wins, the
    # second sees the "Inzwischen geändert" panel (CAS, ADR 0013) — driven through two real browsers.
    edit_url = _create_draft(archivist_page, live_workbench, "E2E Rennen")

    from tests.e2e.conftest import _archivist_cookie

    ctx2 = browser.new_context()
    ctx2.add_cookies([_archivist_cookie(live_workbench)])  # type: ignore[list-item]
    page2 = ctx2.new_page()
    page2.goto(edit_url)  # both now hold the same expected_version
    # both forms carry a valid Medienart so each save reaches the CAS path (not a validation error);
    # the draft on disk has none yet, so page2 sets its own too.
    page2.select_option('select[name="media_type"]', "Fotografie")

    # archivist 1 saves first (wins)
    archivist_page.fill('input[name="creator"]', "Erster")
    archivist_page.click('button:has-text("Speichern")')
    archivist_page.wait_for_url(lambda url: "/bearbeiten" not in url)

    # archivist 2 saves the now-stale form → the conflict panel appears inline, values preserved
    page2.fill('input[name="creator"]', "Zweiter")
    page2.click('button:has-text("Speichern")')
    expect(page2.get_by_text("Inzwischen geändert")).to_be_visible()
    expect(page2.locator('input[name="creator"]')).to_have_value("Zweiter")
    ctx2.close()


# --- Kopieren loop -----------------------------------------------------------------


def test_kopieren_creates_draft_copy_signatur_focused(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # from the published article's read view, Kopieren → a fresh draft's edit form, Signatur focused
    page.goto(live_workbench + f"/artikel/{e2e_corpus.published_ulid}")
    page.click('button:has-text("Kopieren")')
    page.wait_for_url("**/bearbeiten**")
    # the copy cleared the Signatur (ref_code) and the field is focused (spec §5)
    expect(page.locator('input[name="ref_code"]')).to_have_value("")
    expect(page.locator('input[name="ref_code"]')).to_be_focused()
    # title carried over
    expect(page.locator('input[name="title"]')).to_have_value("Sommerfahrt 1962")


# --- Löschen confirm ---------------------------------------------------------------


def test_loeschen_confirm_then_delete(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Löschen")
    ulid = page.url.split("/artikel/")[1].split("/")[0]
    # from the read view, Löschen → the confirm page (the ONE red button.danger), then delete
    page.goto(live_workbench + f"/artikel/{ulid}")
    page.click('a:has-text("Löschen")')
    expect(page.get_by_text("Artikel löschen?")).to_be_visible()
    expect(page.locator("button.danger")).to_be_visible()
    page.click('button:has-text("Endgültig löschen")')
    page.wait_for_url(
        lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/"))
    )  # → workbench


# --- publish preview gate ----------------------------------------------------------


def test_publish_requires_over_exposure_confirm(archivist_page: Page, live_workbench: str) -> None:
    page = archivist_page
    _create_draft(page, live_workbench, "E2E Zu Veröffentlichen")
    # _create_draft already set the required Medienart; open the over-exposure preview
    page.click('button:has-text("Veröffentlichen")')
    # the over-exposure preview panel appears (neutral); the confirm checkbox gates the final button
    expect(page.get_by_text("Wer bekommt nach Veröffentlichung Einblick?")).to_be_visible()
    expect(page.get_by_text("Ich habe geprüft, wer Einblick erhält.")).to_be_visible()


# --- bulk select → confirm → result ------------------------------------------------


def test_bulk_select_confirm_apply(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The PROGRESSIVE cold start (owner 2026-08-07 — reverses the #16 cold-start ruling): with JS
    # on and NO selection, the whole Sammelbearbeitung affordance is hidden (the server renders it
    # visible; catalog_bulk.js hides it at count 0). The first tick reveals it with the live
    # count → expand → choose a field → Änderung prüfen posts the checked boxes → confirm → apply.
    page.goto(live_workbench + "/")
    expect(page.locator("details.bulk")).to_be_hidden()  # cold: no selection, no affordance
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.locator("details.bulk > summary")).to_be_visible()  # revealed on the first tick
    # unticking back to zero hides it again — the visibility tracks the live count both ways
    page.uncheck(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(page.locator("details.bulk")).to_be_hidden()
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # JS live count on tick, collapsed
    # expand by clicking THE COUNT ITSELF — the named regression: a form-associated element in
    # the summary (the old <output>) swallowed exactly this click and the disclosure never
    # opened; the status span must toggle like any other point on the summary line
    page.get_by_text("2 ausgewählt").click()
    expect(page.locator("details.bulk")).to_have_attribute("open", "")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    # the confirm page lists the field + count; apply → the result page
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()
    page.click('button:has-text("anwenden")')
    expect(page.get_by_text("abgeschlossen")).to_be_visible()


def test_bulk_url_seeded_selection_still_works(
    archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = archivist_page
    # The pagination-persistence path: a selection seeded in the URL (?auswahl=) still renders the
    # bar with the count + confirm flow — and the JS wire-time sync must KEEP it visible (count
    # ≥ 1), it only hides at zero. Cheap second assertion so the fix doesn't regress it.
    page.goto(
        live_workbench + f"/?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}"
    )
    expect(page.locator("details.bulk > summary")).to_be_visible()
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # server-rendered count, collapsed
    page.click("details.bulk > summary")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()


def _seed_second_page(root: Path, blocker: DjangoDbBlocker) -> None:
    """Grow the canonical corpus past one page (PAGE_SIZE=50): 60 extra published articles with
    fixed ULIDs sorting AFTER the canonical ones (browse order is ulid), then re-index so the live
    server actually paginates. 63 archivist-visible hits → page 1 holds the canonical articles."""
    from bundesarchiv.domain.models import Article, Lifecycle
    from bundesarchiv.index import indexer
    from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
    from bundesarchiv.persistence.repository import ArticleRepository

    store = LocalFsObjectStore(root)
    articles = ArticleRepository(store)
    for i in range(60):
        articles.save(
            Article(
                ulid=f"01KXE2EPAGE{i:015d}",  # valid Crockford base32, > the canonical 01KX8N…
                title=f"Seitenfüller {i:02d}",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                media_type="Fotografie",
            ),
            0,
        )
    with blocker.unblock():
        indexer.rebuild(store)


def _auswahl_in_url(page: Page) -> list[str]:
    return parse_qs(urlparse(page.url).query).get("auswahl", [])


def test_bulk_fresh_ticks_survive_paging(
    archivist_page: Page,
    live_workbench: str,
    e2e_corpus: CorpusHandles,
    _e2e_root: Path,
    django_db_blocker: DjangoDbBlocker,
) -> None:
    # GH #22: UNSUBMITTED ticks/unticks must survive paging. catalog_bulk.js folds the live checkbox
    # state into the prev/next + "Alle auf dieser Seite" links on every change, so the URL stays the
    # canonical shareable state — the landed page renders exactly as a cold visit to it would.
    _seed_second_page(_e2e_root, django_db_blocker)
    page = archivist_page
    # land with a URL-seeded selection (the no-JS-persisted baseline state)
    page.goto(live_workbench + f"/?auswahl={e2e_corpus.published_ulid}")
    seeded = page.locator(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    expect(seeded).to_be_checked()
    # a fresh tick + a fresh UNTICK of the URL-seeded item — both unsubmitted, DOM-only
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    seeded.uncheck()
    # "Auswahl aufheben" is NEVER rewritten — its purpose is clearing the selection
    aufheben_href = page.locator('a:has-text("Auswahl aufheben")').get_attribute("href")
    assert "auswahl" not in (aufheben_href or "")
    page.click('a[rel="next"]')
    page.wait_for_url("**seite=2**")
    # the URL carries the fresh state: the tick travelled, the untick stuck
    assert e2e_corpus.second_ulid in _auswahl_in_url(page)
    assert e2e_corpus.published_ulid not in _auswahl_in_url(page)
    # tick an item on page 2, go back — the rewritten Zurück link preserves BOTH pages' selections
    page2_box = page.locator('input[name="auswahl"]').first
    page2_ulid = page2_box.get_attribute("value")
    page2_box.check()
    page.click('a[rel="prev"]')
    page.wait_for_url("**seite=1**")
    # page 1 re-renders the selection from the URL alone: tick survived, untick survived
    expect(page.locator(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')).to_be_checked()
    expect(
        page.locator(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    ).not_to_be_checked()
    assert page2_ulid in _auswahl_in_url(page)  # the other-page selection rode along
    assert e2e_corpus.second_ulid in _auswahl_in_url(page)


# --- no-JS baseline ----------------------------------------------------------------


def test_no_js_bulk_flow_completes(
    no_js_archivist_page: Page, live_workbench: str, e2e_corpus: CorpusHandles
) -> None:
    page = no_js_archivist_page
    # The progressive pattern's no-JS half (owner 2026-08-07): the server renders the
    # Sammelbearbeitung disclosure VISIBLE, so with JavaScript OFF and no selection the archivist
    # still reaches "Alle auf dieser Seite" — the URL-borne selection path — and completes the
    # whole bulk flow: page-select → expand → choose a field → prüfen → anwenden.
    page.goto(live_workbench + "/")
    expect(page.locator("details.bulk > summary")).to_be_visible()  # server-visible, no JS hiding
    page.click("details.bulk > summary")  # native <details> toggle, no JS involved
    page.click('a:has-text("Alle auf dieser Seite")')
    page.wait_for_url("**auswahl=**")  # the selection is URL state now
    expect(page.locator("details.bulk > summary")).to_be_visible()
    page.click("details.bulk > summary")
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()
    page.click('button:has-text("anwenden")')
    expect(page.get_by_text("abgeschlossen")).to_be_visible()


def test_no_js_create_and_save_baseline(no_js_archivist_page: Page, live_workbench: str) -> None:
    page = no_js_archivist_page
    # The whole create→edit→save flow must work with JavaScript OFF: plain server-rendered forms,
    # no HTMX swap, no PE enhancements. This pins the baseline promise the other journeys (JS on)
    # take for granted. Create step → edit form (server 302, not an hx-swap).
    page.goto(live_workbench + "/artikel/neu")
    page.fill('input[name="title"]', "E2E Ohne JS")
    page.select_option('select[name="collection_id"]', "FOTOS")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    expect(page.locator('input[name="title"]')).to_have_value("E2E Ohne JS")
    # save: a plain form POST that 302s to the read view (no JS in the loop at all)
    page.select_option('select[name="media_type"]', "Fotografie")
    page.fill('input[name="creator"]', "K. Meyer")
    page.click('button:has-text("Speichern")')
    page.wait_for_url(lambda url: "/bearbeiten" not in url and "/artikel/" in url)
    assert "/bearbeiten" not in page.url
