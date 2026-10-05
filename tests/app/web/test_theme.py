"""The viewer's light/dark choice: the "theme" cookie (theme.js sets or deletes it) fixes the page's
color scheme in the server's render, so a saved choice paints from the first frame; without one, or
with a value it does not know, the page follows the system."""

import re

import pytest
from django.test import Client

from bundesarchiv.app.web import theme


def _scheme(cookie: str | None) -> str | None:
    client = Client()  # anonymous: the door, a screen that needs no index
    if cookie is not None:
        client.cookies[theme.COOKIE] = cookie
    html = client.get("/").content.decode()
    match = re.search(r'<html lang="de"(?: data-theme="(\w+)")?>', html)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    ("cookie", "scheme"),
    [("dark", "dark"), ("light", "light"), (None, None), ("", None), ("dunkel", None)],
)
def test_the_saved_choice_fixes_the_scheme_and_anything_else_follows_the_system(
    cookie: str | None, scheme: str | None
) -> None:
    assert _scheme(cookie) == scheme
