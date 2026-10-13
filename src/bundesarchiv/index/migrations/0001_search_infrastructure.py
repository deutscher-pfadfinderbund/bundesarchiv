"""Search DDL from ADR 0011. The tsvector wrappers are ``IMMUTABLE``, as a generated column
requires, although the ADR expression is only ``STABLE``; safe because a config change bumps
``CONFIG_VERSION`` and rebuilds (ADR 0003).
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

# Verbatim from ADR 0011; the config is schema-qualified so lexization never depends on
# search_path.
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
