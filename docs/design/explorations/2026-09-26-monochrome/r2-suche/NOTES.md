# R2 Suche

Thesis: search comes first. The start page's first screen holds only the wordmark, one field and quiet entry lines. Everything else sits below the fold, and every other page is a plain working tool.

Structural difference: in round 1 the wordmark sat in a top bar on every page, and the start page was a stack of compartments. Here the start page has no masthead. It is a thin nav line, a centered wordmark and a field. The compartments move below the fold into a narrow index column. Browsing starts from text links ("Stöbern" / "Zeitraum"), not from panels. Archiv is the only page with a side column: a faceted filter list, with the table on the right. Artikel is one reading column.

Tokens (light / dark): ground #fff / #0e0e0e · ink #0a0a0a / #f2f2f2 · ink-2 #5c5c5c / #a3a3a3 · rule #d9d9d9 / #3a3a3a · fill-inverse = ink · error #b3261e / #ff6b61. Light is primary; dark uses the same tokens. Entwurf is a 1px solid ink outline. "später" is a dashed ink-2 outline.

Owner to judge:
1. The empty first screen: is it calm, or does it hide too much of the archive?
2. "Meine Entwürfe" as a third entry line above the fold, shown to archivists only. The alternative is a compartment below the fold.
3. Facets as plain checkbox lists that show a few options and collapse the rest ("+ 4 weitere"), next to the table. Signatur is the last column and drawn quiet.

## Cost/gain

- Bestand counts in the facet list are kept (small, ink-2). They are true counts under OR-within-facet. Jahrzehnt and Typ show no counts, because their counts within "Gruppen des DPB" are not in the data.
- Zuletzt hinzugefügt is kept as five title + year lines. The table says to hide it while every date is the import date, so production should hide it until real additions exist.
- Bestände and Zeitleiste counts are kept as small ink-2 figures. The Zeitleiste has no bars.
- Not built: bulk checkboxes for archivists, and a Beschreibung row (the sample has none, so nothing is rendered).
- The archiv query field is empty: only a Bestand filter is active. A free-text result count would be made up.
