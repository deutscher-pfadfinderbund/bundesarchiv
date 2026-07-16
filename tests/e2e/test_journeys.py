"""Canonical E2E journeys (Part #26) — the common flows written ONCE, driven in a real browser.

Each test walks a whole flow through the live app (server + Postgres index + browser), so a review no
longer re-derives them by hand. Marked ``e2e`` (excluded from the default run; ``-m e2e`` to run).
The ``archivist_page`` / ``public_page`` fixtures (conftest) carry the right viewer cookie; the
corpus is the canonical one from ``_corpus``.

Journeys: search+filter+pane · create draft · edit+save · CAS conflict (two contexts) · Kopieren
loop · Löschen confirm · publish preview gate · bulk select→confirm→partial result.
"""

import pytest
from playwright.sync_api import Browser, Page, Route, expect
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


def test_public_never_sees_a_draft(public_page: Page, live_workbench: str) -> None:
    # the leak spine, end to end: a public visitor's workbench shows the published articles but never
    # the draft (search scopes it out) and no archivist chrome (no bulk column, no "Neuer Artikel").
    public_page.goto(live_workbench + "/")
    expect(public_page.get_by_text("Sommerfahrt 1962")).to_be_visible()
    expect(public_page.get_by_text("Entwurf Lagerchronik")).not_to_be_visible()
    expect(public_page.get_by_text("+ Neuer Artikel")).not_to_be_visible()


# --- detail read view (4.6) --------------------------------------------------------


def test_detail_read_from_search_result(public_page: Page, live_workbench: str) -> None:
    page = public_page
    # a member/public visitor: click a result (JS opens the preview pane) → Öffnen → land on the
    # Lesesaal detail read view. (With JS on, ledger_pane.js turns the row link into a pane open; the
    # pane's Öffnen is the navigation to /artikel/<ulid>. No-JS, the row link navigates directly.)
    page.goto(live_workbench + "/")
    page.locator("a.c-ledger-titel", has_text="Sommerfahrt 1962").click()
    page.get_by_role("link", name="Öffnen").click()
    page.wait_for_url("**/artikel/**")
    # the reading structure: title, record card facts (Signatur + human + mono date), the cover
    expect(page.locator("h1.l-titel")).to_have_text("Sommerfahrt 1962")
    expect(page.locator(".l-datierung")).to_have_text("Juli 1962")  # human German under the title
    expect(page.locator(".l-akte-val--mono").first).to_have_text("1962-07")  # mono machine date
    expect(page.get_by_text("F 12")).to_be_visible()  # Signatur
    expect(page.locator(".l-platte-bild")).to_be_visible()  # cover Platte
    expect(page.locator(".l-strip .l-plate")).to_have_count(2)  # cover + one further plate
    # a plate links its gated media byte route; Zurück returns to the search
    href = page.locator(".l-strip .l-plate").first.get_attribute("href")
    assert href is not None and href.startswith("/media/")
    page.get_by_text("Zurück zur Suche").click()
    page.wait_for_url(lambda url: url.rstrip("/").endswith(live_workbench.rstrip("/")))


# --- create a Bestand (4.8) --------------------------------------------------------


def test_create_bestand_then_file_an_article_under_it(
    archivist_page: Page, live_workbench: str
) -> None:
    page = archivist_page
    # + Neuer Bestand → fill Name → Anlegen → LAND on the create-article form (create→catalog is one
    # flow), the new Bestand pre-selected + a success hinweis. File the first article under it.
    page.goto(live_workbench + "/")
    page.get_by_role("link", name="+ Neuer Bestand").click()
    page.wait_for_url("**/bestand/neu")
    page.fill('input[name="name"]', "Plakate")
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/artikel/neu?**")  # 302 to the create-article form, not the workbench
    expect(page.get_by_text("Bestand „Plakate“ angelegt.")).to_be_visible()  # success hinweis
    expect(page.locator('select[name="collection_id"]')).to_contain_text("Plakate")
    page.fill('input[name="title"]', "Ein Plakat")  # the new Bestand is already pre-selected
    page.click('button:has-text("Anlegen")')
    page.wait_for_url("**/bearbeiten**")
    # now the Bestand has an article, so it appears in the workbench collection facet (indexed name)
    page.goto(live_workbench + "/")
    expect(page.locator(".c-facet-label", has_text="Plakate")).to_be_visible()


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
        const banner = document.querySelector('.wb-error-banner');
        const btn = document.querySelector('.c-form-footer .c-btn--primary');
        const footer = document.querySelector('.c-form-footer');
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
    # from the read view, Löschen → the confirm page (the ONE red c-btn--gefahr), then delete
    page.goto(live_workbench + f"/artikel/{ulid}")
    page.click('a:has-text("Löschen")')
    expect(page.get_by_text("Artikel löschen?")).to_be_visible()
    expect(page.locator(".c-btn--gefahr")).to_be_visible()
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
    # The REAL cold-start path (#16 fix): land with NO selection. The bar's affordances are present
    # (the fix), so tick two row checkboxes → the live count appears (JS) → choose a field →
    # Änderung prüfen posts the checked boxes → confirm → apply.
    page.goto(live_workbench + "/")
    expect(page.locator(".wb-sammelleiste")).to_be_visible()  # affordances present from cold start
    page.check(f'input[name="auswahl"][value="{e2e_corpus.published_ulid}"]')
    page.check(f'input[name="auswahl"][value="{e2e_corpus.second_ulid}"]')
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()  # JS live count on tick
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
    # bar with the count + confirm flow. Cheap second assertion so the fix doesn't regress it.
    page.goto(
        live_workbench + f"/?auswahl={e2e_corpus.published_ulid}&auswahl={e2e_corpus.second_ulid}"
    )
    expect(page.locator(".wb-sammelleiste")).to_be_visible()
    expect(page.get_by_text("2 ausgewählt")).to_be_visible()
    page.select_option('select[name="feld"]', "creator")
    page.fill('input[name="wert_text"]', "Sammel-Autor")
    page.click('button:has-text("Änderung prüfen")')
    expect(page.get_by_text("Sammelbearbeitung prüfen")).to_be_visible()


# --- no-JS baseline ----------------------------------------------------------------


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
