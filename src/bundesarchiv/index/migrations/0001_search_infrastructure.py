"""Search infrastructure: German FTS config, ICU collation, and the tsvector wrapper functions.

Pure database DDL with no ORM model:

- The ``bundesarchiv_german`` text-search configuration and the ``unaccent`` extension it
  depends on — consumed **verbatim** from [ADR 0011](../../../../docs/adr/0011-german-fts-config.md).
  The chain is ``unaccent → german_stem`` only (the Hunspell ispell dict was dropped by
  measurement). ``unaccent`` must exist before the config references it, hence the extension first.
- The ``de_numeric`` ICU collation for numeric-aware, locale-aware ``ref_code`` sorting (ADR 0011 §5).
- Two ``IMMUTABLE`` wrapper functions holding the weighted tsvector expression. They exist because a
  generated column's expression must be ``IMMUTABLE``, but the ADR expression uses only-``STABLE``
  building blocks (``array_to_string`` on ``tags``, and the ``unaccent``-based config). Wrapping the
  verbatim expression in an ``IMMUTABLE`` SQL function lets ``ArticleIndex`` (migration 0002)
  declare each generated ``tsvector`` column as a one-line call to its wrapper. Safe because the
  index is derived and disposable: a config change bumps ``config_version`` and rebuilds (ADR 0003).

``ArticleIndex`` (0002) depends on this migration; the dependency is declared there.
"""

from django.db import migrations

# Verbatim from ADR 0011 §Decision. unaccent → german_stem for word-family tokens; simple for
# number/identifier tokens; blank/tag/entity/protocol left unmapped (dropped), as pg_catalog.german.
_CREATE_CONFIG = """
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TEXT SEARCH CONFIGURATION bundesarchiv_german (COPY = pg_catalog.simple);

ALTER TEXT SEARCH CONFIGURATION bundesarchiv_german
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart,
                      word, hword, hword_part
    WITH unaccent, german_stem;

ALTER TEXT SEARCH CONFIGURATION bundesarchiv_german
    ALTER MAPPING FOR numword, hword_numpart, numhword,
                      int, uint, float, sfloat, version,
                      email, url, url_path, host, file
    WITH simple;
"""

_DROP_CONFIG = "DROP TEXT SEARCH CONFIGURATION IF EXISTS bundesarchiv_german;"

# Verbatim from ADR 0011 §5. ICU normalises 'de-u-kn-true' to 'de-u-kn' with a NOTICE; identical.
_CREATE_COLLATION = "CREATE COLLATION de_numeric (provider = icu, locale = 'de-u-kn-true');"
_DROP_COLLATION = "DROP COLLATION IF EXISTS de_numeric;"

# The weighted tsvector, verbatim from ADR 0011 / the Task 6 brief: title A; ref_code + tags B;
# creator + subject_place + media_type + document_type C; body D. Marked IMMUTABLE so it may back
# a generated column (see the module docstring). PARALLEL SAFE: no side effects, config pinned.
# The config reference is schema-qualified ('public.…') so lexization inside the persisted
# columns is search_path-independent for their whole life, not just resolvable at CREATE time.
_CREATE_FUNCTIONS = """
CREATE FUNCTION bundesarchiv_general_tsv(
    title text, ref_code text, tags text[], creator text,
    subject_place text, media_type text, document_type text, body text
) RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT setweight(to_tsvector('public.bundesarchiv_german'::regconfig, coalesce(title, '')), 'A')
        || setweight(to_tsvector('public.bundesarchiv_german'::regconfig,
                                 coalesce(ref_code, '') || ' ' || array_to_string(tags, ' ')), 'B')
        || setweight(to_tsvector('public.bundesarchiv_german'::regconfig,
                                 coalesce(creator, '') || ' ' || coalesce(subject_place, '') || ' '
                                 || coalesce(media_type, '') || ' ' || coalesce(document_type, '')), 'C')
        || setweight(to_tsvector('public.bundesarchiv_german'::regconfig, coalesce(body, '')), 'D')
$$;

CREATE FUNCTION bundesarchiv_archivist_tsv(archivist_text text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT to_tsvector('public.bundesarchiv_german'::regconfig, coalesce(archivist_text, ''))
$$;
"""

# Each op's reverse drops exactly what that op created; reverse order (3 → 2 → 1) then drops the
# wrappers before the config they reference, naturally.
_DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS bundesarchiv_general_tsv(text, text, text[], text, text, text, text, text);
DROP FUNCTION IF EXISTS bundesarchiv_archivist_tsv(text);
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(sql=_CREATE_CONFIG, reverse_sql=_DROP_CONFIG),
        migrations.RunSQL(sql=_CREATE_FUNCTIONS, reverse_sql=_DROP_FUNCTIONS),
        migrations.RunSQL(sql=_CREATE_COLLATION, reverse_sql=_DROP_COLLATION),
    ]
