# Repository Guidelines

## Project Structure & Module Organization

`core/` contains Django settings, root URLs, and WSGI/ASGI entry points; `manage.py` is the command-line entry point. Feature apps are `accounts/` (custom users and dealerships), `claim/` (claims and repair orders), `reports/` (historical reports and PDF/email output), `dashboard/`, and `auditlog/`. Keep models, views, forms, and migrations in their owning app. Shared access helpers live in `decorators/` and `context_processors.py`. HTML lives in `templates/`, organized by feature; frontend assets live in `static/`. Each app has a `tests.py` module.

## Build, Test, and Development Commands

Activate a Python virtual environment and install the project dependencies before running commands. This checkout has no dependency manifest; confirm compatible versions rather than assuming a reproducible installation. Settings identify Django 4.2 and crispy forms integrations; reporting imports `xhtml2pdf`, and the database backend requires a MySQL driver.

After configuring local services:

- `python manage.py check`: run Django system checks.
- `python manage.py runserver`: start the local development server.
- `python manage.py makemigrations <app>`: generate migrations for model changes.
- `python manage.py migrate`: apply migrations to the configured development database.
- `python manage.py test`: run all discovered tests.
- `python manage.py test claim`: run one app's tests.

Static collection uses `python manage.py collectstatic`; inspect the destination first because `STATIC_ROOT` currently points to `static/`.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` for functions and variables, and `PascalCase` for classes. Follow nearby Django patterns and preserve existing URL names. Keep template changes within the relevant feature directory. Commit generated migrations with model changes. No formatter or lint configuration is present; avoid unrelated formatting changes.

## Testing Guidelines

Existing test modules import Django's `TestCase` but contain placeholders. Add `test_*` methods covering changed behavior, especially dealership access, authentication, claim updates, and report calculations. Use isolated fixtures and mock email delivery. No coverage threshold is configured.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so no established commit convention can be verified. Use concise, imperative subjects. Describe behavior changes, validation performed, related issues, and migration impacts in pull requests; include screenshots for template changes.

## Security & Configuration

`core/settings.py` reads secrets from environment variables listed in `.env.example`; export them before running Django. Database/SMTP defaults still target production. Configure separate local settings before development tests. Keep new secrets outside version control and exclude uploads, logs, and Python cache files from contributions.
