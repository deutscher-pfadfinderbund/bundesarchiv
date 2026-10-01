"""Gunicorn's error log as the app's JSON (``bundesarchiv.app.jsonlog``) on stdout. No access
log: nginx keeps the one access log (deploy/nginx/nginx.conf)."""

from bundesarchiv.index.settings import LOGGING

logconfig_dict = LOGGING
