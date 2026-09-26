# R2 Seitenleiste (light first, dark finished)
Thesis: the archive is a working tool, so its navigation is a fixed left sidebar (wordmark, search, Archiv · Bestände · Erfassen, all 9 Bestände, account), and the content area holds only the work.
How it differs in structure: there is no top bar, no hero and no page heading. Search and the Bestände live in the sidebar on every page. So the start page is a work surface, not a search page: Meine Entwürfe leads, then Zuletzt hinzugefügt, with a thin Zeitleiste column beside them and Highlights · Empfohlen below. Picking a Bestand is a click in the sidebar, which archiv.html then shows as the active filter. On a phone the sidebar folds into a top strip: wordmark, Menü and search always visible, the rest behind Menü (a CSS checkbox toggle, no JS).
| token | light | dark |
| --- | --- | --- |
| ground / ink / ink-2 (text only) | #fff / #0a0a0a / #5c5c5c | #0e0e0e / #f2f2f2 / #a3a3a3 |
| rule / fill-inverse / error | #d9d9d9 / #0a0a0a / #b3261e | #383838 / #f2f2f2 / #ff6b61 |
Entwurf is an outlined caps mark with an italic title. Future compartments have dashed rules and a dashed "später" tag. Signatur is the last, quiet column. On artikel, Standort and Signatur are quiet rows at the end.
Owner to judge: (1) The Bestände always in the sidebar: does it replace a Bestände page, and does the start page still guide without a big search? (2) On a phone the search stays outside the menu. Is that right, or should everything fold away? (3) Start leads with Meine Entwürfe for archivists. What should members see in that slot?

## Cost/gain (kept against SCREEN-JOBS, and why)
- The search is first in the sidebar, not the largest thing on the start page. The sidebar carries it on every page, so a second big field on start would repeat it.
- Zuletzt hinzugefügt is shown, though the table says to hide it while every date is the import date. The mock has to show the slot.
- Small ink-2 counts stay next to the Bestände and the decades, and in the onward links ("Alle 1.187", "Alle 226"). They are small and tell the size of the jump. The Zeitleiste bars are 1px hairlines.
- Meine Entwürfe (BA 1216, 1035, 1886) is mock state. The real data holds no drafts.
- Not built: bulk checkboxes and row actions for archivists. The table asks for them only on hover or focus, which static shots cannot show.
- Artikel: media comes right after the title, not before it, on a phone. The title tells a link-holder they have the right thing.
