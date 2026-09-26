# Screen jobs and element cost (owner method, 2026-09-26)

Owner: explain first what each screen is for, who uses it and what they try to achieve. Then give
every element a psychological cost (attention, reading, deciding it can be ignored) and compare it
with its gain for those people. High cost + low gain → cut. Example: a large article count costs a
lot and tells nobody anything they act on → cut.

Scale: cost and gain each low / mid / high. "Size" is part of cost: the same element costs more at
display size than as a quiet line.

## Who

- **Members** — adults interested in the Bund's history. Occasional visits. They look for
  something they remember (their group, a Lager, a year, a person, a place) or want to browse
  without a plan. Signaturen mean nothing to them.
- **Archivists** — volunteers, weekly. They find a record fast, check or correct it, add new ones,
  and finish drafts. Signatur and Standort matter to them (physical holdings).
- **Link-holders** — arrive from chat/mail at ONE article, usually on a phone. They want to see
  that thing; the rest of the app is secondary.

## Door (logged out)

Job: get in. Success: one tap. Users: members and archivists without a session.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Wordmark | low | high (you are at the right place) | keep |
| One sentence (what this is, who may enter) | low | mid | keep |
| "Anmelden mit DPB Login" | low | high | keep, the one action |
| Anything else (teaser, counts, contact) | — | none | cut |

## Start (logged in)

Job: orientation and a first step. Members: "what is in here, where do I start?" — mostly a
search for something they remember, sometimes browsing. Archivists: get to work (find a record,
finish a draft, create one).

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Search field | low | high — the most common intent | keep, first and largest |
| Bestände names (9) | mid | high — shows how the archive is organized, a browse entry | keep, as plain links |
| Counts next to Bestände | low when small | low (size only; "Unsortiert 196" helps archivists a bit) | small ink-2 or drop |
| Zeitleiste as decade links | low | mid — people remember by decade | keep, compact |
| Zeitleiste bars | mid | low — shows distribution, nobody acts on it | drop, or hairline-thin at most |
| Zuletzt hinzugefügt (5 lines) | mid | low for members, mid for archivists; meaningless until real additions exist | keep small; hide while every date is the import date |
| Meine Entwürfe (archivists) | low | high — continue work | ADD, archivists only (missing in round 1) |
| Highlights / Empfohlen | mid | high once curated; none as empty placeholder | show only as the idea in mocks; not built now |
| Total "2.506 Artikel", section folios, big numerals | high | none | cut |
| Footer text | low | none | cut |

## Archiv (search results)

Job: scan results, narrow down, open one. Both roles; archivists also bulk-edit.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Query in the search field | low | high | keep |
| Active filters, each removable | low | high (where am I, how do I undo) | keep, right above the results |
| Filter options (Bestand, Jahrzehnt, Typ) | mid | high | keep; show few, collapse the rest |
| Result count | low when small | mid ("too many? did my filter work?") | small line, never display size |
| Titel column | low | high | keep, widest |
| Datierung column | low | high — history is time | keep |
| Typ column | low | mid | keep |
| Signatur column | mid | low for members, high for archivists | quiet, last or archivist-only |
| Bulk checkboxes, row actions | high if always shown | high for archivists only | archivists only, revealed on hover/focus |
| Big page heading ("Archiv") | mid | low — the nav already says it | small or cut |
| Pagination | low | high | keep |

## Artikel (one article)

Job: understand one thing and look at it; archivists correct it. The link-holder's landing page.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Title | low | high | keep, largest |
| Media (photo, scan, object) | mid | highest — the thing itself | keep, large, first on phone |
| Datierung, Ort, Urheber | low | high | keep, top of the facts |
| Beschreibung | mid | high when present | keep; absent = nothing rendered |
| Typ, Bestand | low | mid (context + a way onward) | keep, Bestand as a link |
| Standort, Signatur | low when quiet | low for members, high for archivists | quiet rows at the end |
| Onward: more from this Bestand / this decade | low | mid-high for browsing members | ADD (missing in round 1) |
| Bearbeiten | low | high for archivists | archivists only, one quiet action |
| Oversized year folio | mid | low beyond the Datierung row | cut or small |
