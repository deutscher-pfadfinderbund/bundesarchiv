# Full-content search v1: the text of each PDF page, found through the article

Status: Proposed (2026-10-11). Amends ADR 0003 (lifts the full-content deferral for PDF text
layers) and ADR 0015 (derived text lives in Postgres, not as a sidecar file, for now).

## Context

ADR 0003 deferred full-content search. The owner wants search to find words inside the files.
Of the 579 legacy PDFs, 244 already carry a text layer: 7,902 pages, about 62% of all PDF pages
(census 2026-10-10). Reading a text layer is parsing, not recognition: the VPS can do it with the
PDF library it already uses for thumbnails. A file has no audience of its own; the media route
serves any file of an Article the viewer may see (ADR 0001, ADR 0017).

## Decision

- **Text belongs to the file.** One row per page of a media file, keyed by the file's content
  hash and the page number (from 1, as a PDF viewer counts). A file on two Articles has one text.
- **Derived from the files, kept across rebuilds.** Media files are write-once, so a file is read
  once. The hourly rebuild keeps the rows and deletes those whose hash no Article names any more
  (a hard delete or a removed file). The fill can recreate every row from the canonical files.
- **Only bytes that match their hash.** Before reading, the fill checks the file's bytes against
  the hash its README claims. On a mismatch it stores nothing and logs a warning: text matched by
  hash must never carry another file's words into a second Article.
- **v1 source: PDF text layers only.** A page without a layer is stored empty. A PDF that cannot
  be read (broken, encrypted, no pages) is stored as one empty marker row (page 0). Either way the
  file counts as done and is not read again. Only a failed read leaves nothing, to be retried.
- **Filled by a job.** After each save that carries a PDF, a reference job reads the new files.
  The hourly reconcile enqueues that job for every Article whose files lack text;
  `manage.py rebuild_index` fills them inline.
- **Staying current.** The rows are a cache of the reader. A change to what the reader stores
  (page cap, text clean-up, a library upgrade that changes text) ships with a data migration that
  empties the table; the next fill rebuilds it. A change to the FTS config (ADR 0011) is covered
  by the existing config-version guard (ADR 0014), which also recomputes the page vectors.
- **Visibility: through the article only.** Page rows carry no audience. A query reaches them
  only from index rows that already passed the viewer's scope: a row matches if its own text
  matches, or if one of its files has a page that matches. The pages a hit shows come only from
  that hit's own files. No new visibility rule.
- **Page text is member-level content.** It never joins the archivist-only text.
- **Ranking:** a match in the record ranks above a match only in page text.
- **UI:** a result row names the matching pages ("Im Volltext S. 14 · S. 22 · +3"), each a link
  to the file at that page (`#page=14`).

## Consequences

- A query is checked per source: all its words in the record, or all on one page. A word in the
  title and another on a page do not match together.
- A query without a positive word (`-Zelt`, `Lager or -Zelt`) searches the record only. Otherwise
  a negation would match every page that lacks the word, and nearly every PDF would be a hit.
- The first fill after deploy runs as one job per Article (about 12,700 pages; seconds to minutes).
- A PDF that crashes the PDF library costs its own job, but the reconcile retries it every hour.
- Old OCR layers without German find little until better text arrives.
- The page link lands only where the browser's PDF viewer honours `#page=` and opens the file
  under the media sandbox (ADR 0017).

## Not decided here

Recognition of scans (the Mac OCR proposal), text from images, ZIP contents or audio, choosing
the better of two texts for a page, snippets, and naming the file when several files match.
Each comes with its own decision; a new source adds rows to the same table.
