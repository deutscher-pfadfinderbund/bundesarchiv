# R2 Druckschwarz, consolidated
Thesis: X2's printed register (black masthead, heavy rules, serif headings, black on white) with counts moved to the margin, so headings and names carry the page and numbers do not.
Structure: navigation sits only in the black masthead. The search leads the start page, then Meine Entwürfe (archivists only), then Bestände | Zeitleiste in two columns, then Zuletzt hinzugefügt as five ruled lines, then Highlights | Empfohlen as a dashed pair, marked "später". The article page leads with the title, then the media (first tile large), then the facts, then "Mehr aus diesem Bestand | diesem Jahrzehnt". Of the round-2 set this is the conservative control: same topology as X2, consolidated.
Counts: no display-size figure anywhere, and no year folio on the article. Counts are 0.85rem mono, ink-2, beside their label. The Zeitleiste marks are 1px hairlines; "Unbekannt" sits below a hairline, with a dashed mark.
Signatur is quiet: the last column in the table, the last fact on the article, absent from the members' start lists (it stays in Meine Entwürfe, which only archivists see).
Light first. Dark is the inversion (#000 / #fff / ink-2 #a6a6a6 / hair #4a4a4a). The masthead stays black in both themes; in dark a white heavy rule closes it.
Judge: (1) Meine Entwürfe placed directly under the search, above Bestände. (2) Zeitleiste with 1px hairline marks instead of no marks. (3) Article order: title → media → facts → onward links.

## Cost/gain (elements kept against SCREEN-JOBS.md)
- Zeitleiste hairlines: the table says "drop, or hairline-thin at most", so I took the upper bound. A 1px line costs almost nothing and lets a member see at a glance which decades hold material before clicking one. Drop them if that still reads as a chart.
- Zuletzt hinzugefügt: kept at five small lines. The table says to hide it while every date is the import date; that is a data condition for the real app, not something a mock can show.
- Bestand heading on archiv.html: kept, reduced to 1.75rem. It names the current scope rather than repeating the nav's "Archiv"; the filter chip says it again, so it can go.
- Not built: bulk checkboxes and row actions for archivists (revealed on hover/focus). They are out of scope for this batch.
