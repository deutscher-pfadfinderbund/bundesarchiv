# Postgres 18 with a German Hunspell (ispell) dictionary baked in for full-text search.
#
# The Debian `hunspell-de-de` package installs /usr/share/hunspell/de_DE.{aff,dic}.
# PostgreSQL's ispell template expects them under $(pg_config --sharedir)/tsearch_data/
# named de_de.{affix,dict} and encoded UTF-8. We convert here so the FTS spike (Task 5)
# and the config migration (Task 6) can do:
#   CREATE TEXT SEARCH DICTIONARY de_de (TEMPLATE = ispell,
#       DictFile = de_de, AffFile = de_de, StopWords = german);
#
# The de_DE (igerman98/frami) dictionary declares its encoding in the .aff `SET` line;
# it is UTF-8 in current Debian, but we detect + iconv defensively so an upstream switch
# back to ISO-8859-1 can't silently corrupt umlauts (the whole point of German FTS).
# Pinned to the exact minor we built and tested against (VPS rebuilds must not drift
# across the 18.x series unseen) — bump deliberately.
FROM postgres:18.4

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends hunspell-de-de; \
    rm -rf /var/lib/apt/lists/*; \
    src=/usr/share/hunspell; \
    dst="$(pg_config --sharedir)/tsearch_data"; \
    enc="$(sed -n 's/^SET[[:space:]]\+//p' "$src/de_DE.aff" | head -n1 | tr -d '\r')"; \
    : "${enc:=UTF-8}"; \
    echo "de_DE.aff declares encoding: $enc"; \
    if [ "$enc" = "UTF-8" ] || [ "$enc" = "utf-8" ] || [ "$enc" = "UTF8" ]; then \
        # Already UTF-8: copy verbatim.
        cp "$src/de_DE.aff" "$dst/de_de.affix"; \
        cp "$src/de_DE.dic" "$dst/de_de.dict"; \
    else \
        # Convert both files to UTF-8 and rewrite the .aff SET directive to match.
        iconv -f "$enc" -t UTF-8 "$src/de_DE.aff" \
            | sed 's/^SET[[:space:]]\+.*/SET UTF-8/' > "$dst/de_de.affix"; \
        iconv -f "$enc" -t UTF-8 "$src/de_DE.dic" > "$dst/de_de.dict"; \
    fi; \
    # Prove the files landed and are valid UTF-8 (build fails otherwise).
    ls -l "$dst/de_de.affix" "$dst/de_de.dict"; \
    iconv -f UTF-8 -t UTF-8 "$dst/de_de.affix" > /dev/null; \
    iconv -f UTF-8 -t UTF-8 "$dst/de_de.dict" > /dev/null
