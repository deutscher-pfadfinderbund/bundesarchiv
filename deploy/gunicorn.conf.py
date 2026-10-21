"""Gunicorn's error log as the app's JSON (``bundesarchiv.app.jsonlog``) on stdout. No access
log: nginx keeps the one access log (deploy/nginx/nginx.conf). The thread count comes from the
settings, which size the database pool by it."""

from bundesarchiv.index.settings import GUNICORN_THREADS, LOGGING

logconfig_dict = LOGGING
threads = GUNICORN_THREADS
