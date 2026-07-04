# German full-text search: unaccent + german_stem, no compound splitting in v1

## Context

[ADR 0003](0003-search-index.md) commits to German full-text search in Postgres:
umlaut folding, stemming, and — as an aspiration — compound splitting (so *Fahrtenbericht*
would also match *Fahrt*). Task 4 baked the Debian `hunspell-de-de` dictionary into the
image and proved it loads (`Häuser` → {häuser, haus}), but also found that stock `de_de`
does not split *Fahrtenbericht*. This spike measured the real behaviour against a corpus of
50 real DPB titles (see [migration-feasibility appendix §6](../plans/migration-feasibility.md))
and gates the v1 text-search configuration. All numbers below are from Postgres 18.4 in the
project container. No production code was written; the SQL here is applied in Task 6.

## Decision

v1 ships **without compound decomposition**. The text-search configuration folds accents and
stems, and does **not** use the Hunspell ispell dictionary at all:

```sql
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TEXT SEARCH CONFIGURATION bundesarchiv_german (COPY = pg_catalog.simple);

-- Word-like tokens: fold accents (umlaut-insensitive), then German stem.
ALTER TEXT SEARCH CONFIGURATION bundesarchiv_german
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart,
                      word, hword, hword_part
    WITH unaccent, german_stem;

-- Number-bearing and identifier tokens: index verbatim.
ALTER TEXT SEARCH CONFIGURATION bundesarchiv_german
    ALTER MAPPING FOR numword, hword_numpart, numhword,
                      int, uint, float, sfloat, version,
                      email, url, url_path, host, file
    WITH simple;

-- blank, tag, entity, protocol: left UNMAPPED (dropped), as in pg_catalog.german.
```

Task 6 consumes this SQL block verbatim. Callers apply **prefix matching** on the last query
token (see below) as the Part 4 UX mitigation for the missing decomposition.

Numeric-aware `ref_code` sort uses an ICU collation (unchanged from ADR 0003):

```sql
CREATE COLLATION de_numeric (provider = icu, locale = 'de-u-kn-true');
```

## Measurements

### 1. Compound splitting — stock `de_de` ispell: 0 / 28

`ts_lexize` with the baked `de_de` ispell dictionary on 28 real compounds from the corpus.
Every one returned `NULL` (unrecognised — falls through to the stemmer): *Fahrtenbericht,
Bundeslager, Bundesordnungen, Rechtsordnungen, Meißnerlagers, Meißnertag, Singewettstreit,
Liederheft, Käsepapier, Jugendbewegung, Pfadfinderbuch, Bundesvogt, Bundesthing,
Mitgliederversammlungen, Waldläuferschule, Lagerzeitung, Führerschulung, Nachrichtenblätter,
Frauen-Volksliederbuch, Spruchbüchlein, Speerjungenlager, Lagerheft, Widerstandskämpferin,
Festschrift, Mädchenbundheft, Kommersbuch, Teilnehmerheft, Stahlträume.* Split rate **0 %**.

The base words *are* recognised (`Bund` → bund, `Lager` → {lager, lagern}, `Bericht` →
bericht), so the failure is specifically compound decomposition, not a broken dictionary.

**Root cause.** The baked dict is the igerman98-derived Debian `hunspell-de-de`. Its affix
file marks compounds with the modern Hunspell directives `COMPOUNDBEGIN / COMPOUNDMIDDLE /
COMPOUNDEND`. Postgres's ispell template **implements only the basic compound operations of
Hunspell** — the [Postgres 18 docs](https://www.postgresql.org/docs/current/textsearch-dictionaries.html)
state this outright ("At present, PostgreSQL implements only the basic compound word
operations of Hunspell"). Postgres honours only the legacy Ispell `compoundwords controlled
<flag>` mechanism, where each compoundable word carries an explicit flag. The Hunspell
affix directives are silently ignored, so nothing splits.

We proved the mechanism directly: a hand-built two-line affix with `compoundwords controlled
z` and a six-word dict flagged `/z` splits correctly — `ts_lexize` returned
`Fahrtenbericht` → {fahrten, bericht} and `Bundeslager` → {bundes, lager}. So Postgres *can*
split; the baked dictionary just does not use the format it needs.

### 2. Option 1 (compound-enabled dictionary) — rejected, no straightforward route

For a compound-enabled dict we would need a German word list flagged with the legacy
`compoundwords controlled` mechanism. The only candidates:

- **Debian `ingerman`** (the ispell binary of igerman98). Installed and inspected. Its affix
  ships `compoundwords off`, and its word list carries inflection flags only, no compound
  flags. Its words use TeX-escaped umlauts (`A"bte`) and it delivers a compiled `.hash`, not
  a plain `.dict` Postgres can load. Not usable without heavy rework.
- **The postgrespro/hunspell_dicts `de_DE`** is the same igerman98 source — same
  `COMPOUNDBEGIN/END` limitation, no splitting through Postgres.
- **The legacy `ispell-german-compound` file** (pre-1996 orthography, ISO-8859-1, unmaintained
  since ~2003, not packaged) does use the flag mechanism, but is old-orthography and stale.

Making any of these split would mean converting encodings, rewriting the affix to enable
`compoundwords controlled`, and mass-annotating ~75–96k words with a compound flag — bespoke
dictionary engineering, not a Dockerfile line. That fails the standing "straightforward
Dockerfile/dict change" bar and the decade-maintenance constraint. **Option 1 rejected.**

### 3. Umlaut handling order and unaccent's role

The spike required proving the ispell dict sees umlauts before any folding. With an
**ispell-first** chain (`de_de, german_stem`), `ts_debug('…', 'fährt')` confirms the dict
receives the token `'fährt'` — umlaut intact, not `'fahrt'` — and returns `['fährt']`:

```
alias=word  token='fährt'  candidate_dicts={de_de,german_stem}  chosen=de_de  lexemes={fährt}
```

So the ordering constraint is satisfiable. **But keeping the ispell dict measurably hurts
recall on our corpus**, because when it recognises a correctly-umlauted word it emits a
lexeme that umlaut-less typing can never reach:

| query → title  | `de_de, german_stem` | `unaccent, german_stem` |
|----------------|----------------------|--------------------------|
| Blatt → Blätter | miss | **hit** |
| Bund → Bünde   | miss | **hit** |
| Buch → Bücher  | miss | **hit** |
| Fuhrer → Führer | miss | **hit** |
| Madchen → Mädchen | miss | **hit** |
| singular/plural spot-check | **5 / 8** | **8 / 8** |

Since the ispell dict adds no compound splitting (§1) — its only unique value — and degrades
recall, **it is dropped from the configuration**. `german_stem` already folds umlauts and ß
during stemming; `unaccent` in front makes the fold explicit and covers the cases the stemmer
alone misses.

**unaccent's role: a folding step in front of the stemmer** (not a separate lexeme, not
last-resort). Because it precedes `german_stem`, both umlaut and umlaut-less spellings reduce
to the same lexeme. Query-side test under the final config: searching `Baume` finds `Bäume`,
`Hauser` finds `Häuser`, `Fuhrer` finds `Führer`, `Meissner` finds `Meißner` — and `Baeume`
(ae-digraph) finds `Bäume` too. `Straße` and `Strasse` both → `strass`. This is what a member
typing without a German keyboard expects, so umlaut-insensitivity is a deliberate yes.

Note the earlier ordering rule now applies to `unaccent`, not the dropped dict: `unaccent`
must sit *first* so folding happens before stemming. Verbatim `ts_debug` output under the
final config (recreated from the SQL block above in a scratch database, then dropped):

```
adr_check=# SELECT alias, token, dictionaries, dictionary, lexemes
            FROM ts_debug('bundesarchiv_german', 'fährt Bäume');
 alias | token |      dictionaries      | dictionary | lexemes
-------+-------+------------------------+------------+---------
 word  | fährt | {unaccent,german_stem} | unaccent   | {fahrt}
 blank |       | {}                     |            |
 word  | Bäume | {unaccent,german_stem} | unaccent   | {Baume}

adr_check=# SELECT to_tsvector('bundesarchiv_german', 'fährt Bäume');
    to_tsvector
--------------------
 'baum':2 'fahrt':1
```

`unaccent` fires first (chosen dictionary) — the intended behaviour. One `ts_debug` nuance:
`unaccent` is a *filtering* dictionary, so the lexemes column shows its intermediate output
(`Bäume` → `{Baume}`), which then passes to `german_stem`; the final indexed lexeme is
`baum`, as the `to_tsvector` line proves.

### 4. Final configuration SQL

The SQL block under **Decision** above. Each token type is mapped exactly once. Verified
applied against the live container: word-family tokens → `{unaccent, german_stem}`,
number/identifier tokens → `{simple}`, and `blank, entity, protocol, tag` left unmapped
(dropped), matching `pg_catalog.german`.

### 5. ICU numeric collation — confirmed

```sql
CREATE COLLATION de_numeric (provider = icu, locale = 'de-u-kn-true');
SELECT ref_code FROM (VALUES ('B 2'),('B 10'),('B 1'),('Ä 3')) t(ref_code)
ORDER BY ref_code COLLATE de_numeric;
--  Ä 3
--  B 1
--  B 2
--  B 10
```

Exactly as expected: Ä sorts with A (locale-aware), and `B 10` sorts after `B 2` (numeric,
not lexicographic). ICU normalises the locale tag `de-u-kn-true` to `de-u-kn` with a NOTICE;
behaviour is identical.

### 6. Recall spot-check — 12 realistic member queries over the 50-title corpus

Final config `bundesarchiv_german`. "plain" = `websearch_to_tsquery`; "+ prefix" = last token
given the `:*` prefix form (the Part 4 mitigation).

| query | plain | + prefix | note |
|-------|:-----:|:--------:|------|
| Pfadfinder | 2 | 3 | whole word |
| Pfadfinderin | 2 | 3 | plural → singular |
| Lieder | **0** | 3 | compound head (Liederheft, …) |
| Lager | **0** | 3 | compound head (Bundeslager, …) |
| Bundeslager | 5 | 5 | whole compound |
| Meissnertag | 2 | 2 | umlaut-less |
| Meißner | 1 | 4 | umlaut |
| Madchen | 1 | 2 | umlaut-less |
| Fuhrer | **0** | 1 | umlaut-less into a compound |
| Jugendbewegung | 3 | 3 | compound |
| Blatter | 3 | 3 | umlaut-less plural |
| Bote | 2 | 2 | hyphenated compound part (hword_part tokenisation) |
| **queries with ≥1 hit** | **9 / 12** | **12 / 12** | |

Plain queries reach **9 / 12**; the misses are all compound-head queries (`Lieder`, `Lager`,
`Fuhrer`-into-`Führerschulung`) — exactly the recall that compound splitting would have
provided. Adding `:*` prefix on the last token recovers all three, reaching **12 / 12**,
because the query lexeme then matches the start of the compound (`lied:*` matches
`liederheft`). Prefix matching does not fix umlaut-less *mid*-word matching, but `unaccent`
already handles that.

**Prefix syntax verified.** `websearch_to_tsquery` does not accept `:*` inline. The working
Part 4 pattern: build the `websearch_to_tsquery`, cast to text, append `:*` to the trailing
lexeme, cast back to `tsquery`. Proven: `websearch_to_tsquery('Berliner Lieder')::text ||
':*'` → `'berlin' & 'lied':*`, which reparses cleanly. `to_tsquery('Lager:*')` → `'lag':*`.

## Consequences

- **No compound decomposition in v1.** A bare-word query like *Lager* does not match
  *Bundeslager* on its own. Mitigated by prefix matching (`:*` on the last token), which the
  Part 4 search UI applies by default — it lifts the corpus spot-check from 9/12 to 12/12.
- **Umlaut-insensitive by design.** `unaccent + german_stem` means *Baume* finds *Bäume* and
  *Meissner* finds *Meißner*. Intended: members type on non-German keyboards.
- **The baked `hunspell-de-de` dictionary is unused by the FTS config.** Task 4's dictionary
  files stay in the image (harmless, ~1 MB) and remain available if a future PG-compatible
  compound format appears. No Dockerfile change is needed for this decision.
- **The index is derived and disposable** ([ADR 0003](0003-search-index.md)), so the config is
  swappable. If prefix-plus-stemming recall proves too coarse in real use, Meilisearch remains
  the escape hatch — no data migration, just a different index build.
- **Rejected — a compound-enabled ispell dictionary (option 1).** No Debian-packaged or
  upstream German word list uses the legacy `compoundwords controlled` flag Postgres needs;
  producing one is bespoke, unmaintained dictionary work (§2).
- **Rejected — keeping the ispell dict in the chain.** It splits nothing and lowers recall on
  umlaut plurals and umlaut-less typing (§3): 5/8 vs 8/8 on the singular/plural spot-check.
- **Rejected — exotic tokenizers / custom C extensions.** Out of scope for a decade-maintenance
  project by standing policy.
