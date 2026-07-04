#!/usr/bin/env python
"""Django management entrypoint — migrations-only.

Django is present solely as the search-index adapter (ADR 0004/0005); nothing serves
HTTP. In practice this is used for ``migrate`` (and ``makemigrations`` / ``check``)
against the derived Postgres index. See the README dev-setup section.
"""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bundesarchiv.index.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
