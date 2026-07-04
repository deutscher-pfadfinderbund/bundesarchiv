# Migration Feasibility Memo — Old Dataset → New Article Model

**Status:** spike complete  
**Corpus:** `tests/test_data/archive_items.txt` — psql `\copy` dump, 2 485 main rows + 1 261 keywords-continuation rows  
**New model reference:** `docs/design/bundesarchiv-v1.md` §5, `CONTEXT.md`

---

## 1. Column Inventory

Verified against file header (row 1):

| # | Old column | Type | Non-empty rows (approx.) | Notes |
|---|---|---|---|---|
| 1 | `id` | integer PK | 2 485 | Old surrogate; discarded |
| 2 | `signature` | text | ~2 000 | `BA NNN` pattern; some `BA B80` etc. |
| 3 | `author` | text | ~2 200 | Free text; occasionally multi-person |
| 4 | `title` | text | 2 485 | Main descriptor |
| 5 | `pub_date` | timestamptz | 2 485 | Django admin entry timestamp; **not** content date |
| 6 | `active` | boolean | 2 485 | All `t` in dump |
| 7 | `amount` | integer | 2 485 | Count of physical items (1–12); reflects media quantity |
| 8 | `collection` | text | ~2 289 | 8 distinct top-level strings; 196 rows empty |
| 9 | `crossreference` | text | 0 | Empty in entire dump |
| 10 | `date` | text | ~2 036 | Free-form content date string (see §4) |
| 11 | `doctype` | text | ~1 860 | Free-text label; mostly matches `document_type_id` |
| 12 | `keywords` | text | ~2 400 | Space-separated; some entries also use `--` delimiter; contains `\r` artifacts |
| 13 | `location` | text | ~2 400 | Physical archive path (e.g. `Gruppen des DPB -- Gau Franken -- Zeitschrift`) |
| 14 | `medartanalog` | text | ~2 485 | Media-type vocabulary (11 distinct values) |
| 15 | `notes` | text | 3 | Very sparse; provenance notes |
| 16 | `owner` | text | 3 | Very sparse; original owner note |
| 17 | `place` | text | ~1 800 | City/place of publication or origin |
| 18 | `reviewed` | boolean | 2 485 | All `t` in dump |
| 19 | `source` | text | ~200 | Donor/collector name (e.g. `bolko`, `Burgarchiv`) |
| 20 | `year` | integer | ~2 000 | Derived integer year; redundant with `date` |
| 21 | `file_id` | integer FK | ~1 400 | django-filer primary file |
| 22 | `modified` | timestamptz | 2 485 | Last admin edit timestamp; import provenance only |
| 23 | `file2_id` | integer FK | ~270 | django-filer secondary file |
| 24 | `file3_id` | integer FK | ~30 | django-filer tertiary file |
| 25 | `document_type_id` | integer FK | ~1 860 | FK to a `document_type` lookup table |
| 26 | `day` | integer | 0 | Empty in entire dump |
| 27 | `month` | integer | 0 | Empty in entire dump |

---

## 2. Column → New Model Mapping

| Old column | New field | Transformation | Confidence |
|---|---|---|---|
| `signature` | `ref_code` | Direct copy; strip trailing spaces | High |
| `author` | `creator` | Direct copy | High |
| `title` | `title` | Direct copy | High |
| `place` | `subject_place` | Direct copy; strip `(…)` wrapper (uncertainty marker — keep or convert to `?` qualifier) | High |
| `location` | `physical_location` | Direct copy; `--`-delimited path maps naturally to `Magazin / Regal / …` convention | High |
| `medartanalog` | `media_type` | Direct copy (vocabulary preserved; 11 values) | High |
| `doctype` | `document_type` | Use `doctype` text; fallback to resolving `document_type_id` via lookup table (not in dump — requires separate FK export) | Medium |
| `document_type_id` | `document_type` | FK lookup needed; 1 660 rows have both, 199 have only id | Medium |
| `keywords` | `tags` | Split on `--` first; then space-split remainder; strip `\r` artifacts; deduplicate | Medium |
| `date` | `date` (EDTF) | Complex — see §4; ~450 rows empty; ~338 patterns are non-trivial | Low–Medium |
| `year` | derived / discard | Use only as fallback when `date` is empty | Low |
| `day`, `month` | discard | Empty throughout dump | — |
| `notes` | `custom` | Key: `"Notiz"`; 3 rows only | High |
| `owner` | `custom` | Key: `"Herkunft_Original"`; 3 rows only | High |
| `source` | `custom` | Key: `"Quelle"`; ~200 rows | High |
| `crossreference` | `custom` | Key: `"Querverweis"`; empty in dump — omit | — |
| `amount` | `custom` | Key: `"Anzahl_Objekte"` when > 1; provides physical-object count | Medium |
| `collection` | Collection lookup | 8 distinct strings; must map to new Collection tree (§5) | Medium |
| `file_id`, `file2_id`, `file3_id` | `media` tuple | Django-filer FK → requires separate filer export to resolve filenames/paths | Medium |
| `id` | discard | Replaced by ULID | — |
| `pub_date` | import log only | Admin entry timestamp; not archival date | — |
| `modified` | import log only | Last-edit timestamp; import provenance | — |
| `active` | discard | All `t`; all rows are active | — |
| `reviewed` | discard | All `t`; all rows reviewed | — |

### Keywords encoding detail

Three patterns observed:

1. `-- ` delimiter: `Filmaufnahmen -- Jugendbewegung` → tags `["Filmaufnahmen", "Jugendbewegung"]`
2. Space-separated: `Pfadfinder Gedicht Michael Konventsarbeit` → one tag per token
3. Mixed (most rows): split `--` first, then strip trailing spaces and `\r`

Tags contain multi-word terms (`Blätter St. Georg`) mixed with single words. Import script must not split on every space when `--` delimiter is present.

### `doctype` vs `document_type_id`

Both carry the same vocabulary but are not always consistent (e.g. `Schriftwechsel` maps to both id 12 and 13; `Sonstiges` also maps to 13). Strategy: prefer `doctype` text when non-empty; use `document_type_id` lookup as fallback; flag discrepancies for archivist review.

---

## 3. End-to-End Row Examples

### Row A — id 2039 (BA 1074): simple Schrifttum with German month date

Old data:

```
id=2039 | signature=BA 1074 | author=Gau Franken | title=Fränkischer Rechen Nummer 6
date=Januar 1986 | doctype=Zeitschrift | keywords=Fränkischer Rechen Nummer 6 -- Gaubrief der Franken
location=Gruppen des DPB -- Gau Franken -- Zeitschrift -- Fränkischer Rechen
medartanalog=Schrifttum | place=Mainz | source=bolko | year=1986
document_type_id=14 | file_id=(empty)
```

New `README.md` front-matter:

```yaml
ulid: 01HV2ZK5P8X3NFRQ7D4CBJM9TE
title: "Fränkischer Rechen Nummer 6"
ref_code: "BA 1074"
creator: "Gau Franken"
date: "1986-01"
media_type: "Schrifttum"
document_type: "Zeitschrift"
tags:
  - "Fränkischer Rechen Nummer 6"
  - "Gaubrief der Franken"
subject_place: "Mainz"
physical_location: "Gruppen des DPB / Gau Franken / Zeitschrift / Fränkischer Rechen"
collection: <id of "Gruppen des DPB">
lifecycle: published
custom:
  - ["Quelle", "bolko"]
```

### Row B — id 1221 (BA 242): Zeitschrift with file2_id, notes field

Old data:

```
id=1221 | signature=BA 242 | author=Orden St. Georg | title=Blätter St. Georg, Heft 18
date=Juni 1982 | doctype=Zeitschrift | keywords=Blätter St. Georg 18
location=Orden St. Georg -- Zeitschrift -- Blätter St. Georg
medartanalog=Schrifttum | place=Berlin | year=1982 | notes=inkl. Beilage: Bündische Pfadfinder
file_id=373 | file2_id=374 | document_type_id=14
```

New `README.md` front-matter:

```yaml
ulid: 01HV2ZK5P8X3NFRQ7D4CBJM9TF
title: "Blätter St. Georg, Heft 18"
ref_code: "BA 242"
creator: "Orden St. Georg"
date: "1982-06"
media_type: "Schrifttum"
document_type: "Zeitschrift"
tags:
  - "Blätter St. Georg 18"
subject_place: "Berlin"
physical_location: "Orden St. Georg / Zeitschrift / Blätter St. Georg"
collection: <id of "Orden St. Georg">
lifecycle: published
custom:
  - ["Notiz", "inkl. Beilage: Bündische Pfadfinder"]
media:
  - path: "media/<filer-373-filename>"
    caption: ""
  - path: "media/<filer-374-filename>"
    caption: ""
```

Note: filer filenames must be resolved from the django-filer export (not in this dump).

---

## 4. EDTF Composition Rules

`day` and `month` columns are empty throughout the dump. All date information lives in the free-text `date` column plus the integer `year` column. Rules observed from the corpus:

### Unambiguous patterns (automate)

| Old `date` value pattern | EDTF output | Example |
|---|---|---|
| `YYYY` | `YYYY` | `1984` → `1984` |
| `(YYYY)` | `YYYY~` (approximate) | `(1974)` → `1974~` |
| `Monat YYYY` | `YYYY-MM` | `Januar 1986` → `1986-01` |
| `D. Monat YYYY` | `YYYY-MM-DD` | `1. April 1961` → `1961-04-01` |
| `DD.MM.YYYY` | `YYYY-MM-DD` | `01.12.1984` → `1984-12-01` |
| `(Monat YYYY)` | `YYYY-MM~` | `(Mai 1994)` → `1994-05~` |
| empty | `null` | — |
| `year` integer only (date empty) | `YYYY` | `year=1970`, `date=` → `1970` |

### Needs human review or script flag

| Old value | Proposed handling |
|---|---|
| `(1969/1970)` | `1969/1970` (EDTF interval, uncertain) |
| `1934 - 1962` | `1934/1962` (EDTF interval) |
| `(ca. 1981)` | `1981~` (approximate) |
| `(nach 1983)` | `1983/..` (open-end interval) |
| `vor 1945` | `../1945` (open-start interval) |
| `Herbst 1997` | `1997-23` (EDTF season 23 = Autumn) |
| `Sommer 1974` | `1997-22` (EDTF season 22 = Summer) |
| `Winter 1961` | `1961-24` (EDTF season 24 = Winter) |
| `Pfingsten 1985` | `1985` + flag `Pfingsten` as note |
| `Weihnachten 1960` | `1960-12` approximate |
| `50er Jahre` | `195X` (EDTF decade) |
| `Mitte/Ende 70er Jahre` | `197X~` |
| `(o.J.)` | `null` (unknown year) |
| `(vermutlich 2008-2010)` | `2008~/2010~` |
| `(1969) oder später` | `1969~/..` |
| `April/Mai 1933` | `1933-04/1933-05` |
| `Ostern 2016` | `2016` + note |
| `Oktober-Nov.-Dez. 1961` | `1961-10/1961-12` |
| `07/25` | ambiguous — month/year 2025 or Jul 25? Flag for review |
| `nonen zit 1958` | unparseable — flag for archivist |
| `Febuar1962` (typo) | `1962-02` after normalisation |
| `März1985` (no space) | `1985-03` after normalisation |

**Summary:** ~450 rows have no date at all. Of the remainder, roughly 70% are `YYYY` or `Monat YYYY` and automate cleanly. ~300–340 rows need a script flag or archivist pass. No additional model fields are required; the `date` EDTF string field absorbs all cases.

---

## 5. Unrepresentable / Risky Items

### Multi-valued fields

- **Keywords**: multi-token field with inconsistent delimiters (space vs `--`). Must split carefully; space-only keywords will produce many granular tags. Recommend: prefer `--` split when present; otherwise treat the entire string as a single tag (less noise, loss of some granularity). Needs archivist review pass.
- **Keywords contain `\r`**: literal carriage-return bytes embedded in text. Strip before splitting.

### Multiple media per Article (`file2_id`, `file3_id`)

273 rows (11%) have 2–3 filer files. The new `media` tuple field handles this correctly. **However:** this dump contains only integer FKs — the actual filenames, MIME types, and paths live in the django-filer tables (`filer_file`, `filer_image`). A separate filer export is required before media can be migrated. The amount field (1–12) sometimes exceeds the count of file IDs, suggesting additional files may exist in filer beyond the three columns captured here.

### Collection string → Collection tree

The dump stores collection as a flat string (8 values). The new system requires a Collection tree with ULIDs. The 8 strings map 1-to-1 to obvious top-level collections, but the `location` column encodes deeper sub-paths (e.g. `Gruppen des DPB -- Gau Franken -- Zeitschrift -- Fränkischer Rechen`). The import script should:
1. Create Collection nodes from the distinct `collection` strings.
2. Optionally derive sub-collections from the `--`-delimited `location` paths (if the new tree is to be pre-populated).
3. 196 rows have an empty `collection` field — these need assignment before import.

### `doctype` inconsistency

`Sonstiges` (catch-all) appears mapped to `document_type_id=13`, which also maps to `Schriftwechsel`. The free-text `doctype` column is the more reliable source; the FK lookup table is not in this dump and needs a separate export.

### `source` field as person names

`source` contains names like `bolko`, `Monika Bischoff`, `Nachlass Burkhart Schäder`. These are donor/collector names, not archivally structured data. Mapping to `custom["Quelle"]` is correct; they are not suitable for `creator` (which is the content creator).

### `active` / `reviewed` always `t`

All 2 485 rows are active and reviewed. Either the dump was pre-filtered or inactive records were deleted. No action needed.

### `pub_date` vs `modified`

`pub_date` is the Django admin record-creation timestamp, not an archival date. It must not be mapped to `date`. It can be stored in the import log for audit purposes.

### Pre-Part-7 model changes needed

**NONE.** All old columns land in existing fields or in `custom`. No new Article fields are required to represent the old dataset.

---

## 6. German Title Corpus (FTS validation appendix)

50 representative titles from the corpus, covering compound nouns, diacritics, numbers, abbreviations, and varied vocabulary. For use in ADR 0011 German FTS benchmarking.

```
(Heft zur Erinnerung an Michael)
Adlerhorstrunden 1986-98
Artikelsammlung Meißnertag 1963
Berliner Singewettstreit 1979-2001 - Einladungen u.a.
Berliner Singewettstreit 2014 - Liederheft
Berliner Tagblatt - Käsepapier zum BundesLager, No.1
Blätter St. Georg, Heft 2
Blätter St. Georg, Heft 18
Blätter St. Georg, Heft 44
Briefwechsel zu Bundesordnungen, Rechtsordnungen, Satzungen - 1981-1983 - pingi
Bünde des Meißnerlagers 2013
Bundeslager 1981
Bundeslager Mönchwinkel/Brandenburg 1993, Heft 2
Bündische Jugend und Hitlerjugend. Zur Geschichte von Anpassung und Widerstand von 1930 - 1939
Das Pfadfinderbuch. Nach General Baden-Powells Scouting for Boys
Der Burgunden-Bote, Nr. 4
Der Jungenschafter ohne Fortune
Der Pfad / von uns - für uns, Heft 8
Der Planwagen: Unternehmungen für Jugendgruppen
Der Spurkalender 1933 - Kalender des deutschen Jungen
Der Thingruf: Nachrichtenblätter 4
Der Turm, Nr. 1
Die deutsche Jugendbewegung. Eine historische Studie
Die Feuerrunde 19
Die Frau, die wollt ins Wirtshaus - Frauen-Volksliederbuch - Texte und Noten mit Begleitakkorden
Die Kompassnadel, Nr. 57
Die Lupe 1973/74 - Lagerzeitung Führerschulung
Die Pfadfinder in der deutschen Jugendgeschichte. Teil 1 - Darstellung
Die Waldläuferschule Heft 31. Jugendbewegung zwischen den Kriegen
Edelweiß: Meine Jugend als Widerstandskämpferin
Einladungen, Protokolle Bundesthing, Bundesrat, Mitgliederversammlungen, 1955-1964
Fotoalbum: Dem Bundesvogt Michael zum 27.10.57
Fränkischer Rechen Frühjahr 2000
Fränkischer Rechen Nummer 6
Grundschriften der Deutschen Jugendbewegung
Hoher Meißner 2013: Festschrift 100 Jahre Freideutscher Jugendtag
Ich spring in diesem Ringe. Mädchen und Frauen in der deutschen Jugenbewegung
Jahrbuch. Achter Band
Kleines Kommersbuch - Liederbuch fahrender Schüler
Liedersammlung Edelweiß: Bundeslager 2011
Lob der Musik - Ein Spruchbüchlein
Mädchenbundheft 3/87
Meissnertag 1963: Teilnehmerheft
Pfadfinderinnen
RJB Mitteilungen, Nr. 115
Speerjungenlager 2018/2019: Lagerheft der Jungenschaft Geralt von Riva
Stahlträume und Stadtträume, Lagerheft zum Bundeslager 2024
Stammesecho: Zeitung der Js Raubritter und Ms Volee, Nr. 16
Wartburg-Bote, Nr. 100
Wimpel, Horte Attinghausen (Speerjungenlager 2011/2012)
```
