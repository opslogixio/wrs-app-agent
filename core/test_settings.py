"""Isolated regression tests: never connect to the imported production database."""
import os
os.environ.setdefault('DJANGO_SECRET_KEY', 'isolated-test-key-only')
os.environ.setdefault('DB_PASSWORD', 'unused-in-tests')
from .settings import *

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
ALLOWED_HOSTS = ['testserver', 'wrs-agentic', 'localhost']
LOGGING = {'version': 1, 'disable_existing_loggers': False}
