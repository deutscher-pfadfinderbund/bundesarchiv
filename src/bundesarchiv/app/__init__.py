"""The only package that imports ``bundesarchiv.index``.

An installed app (Procrastinate discovers ``tasks.py``, Django the commands), so this ``__init__``
imports nothing: the services pull in the ``ArticleIndex`` model, which cannot load at
app-``populate()`` time.
"""
