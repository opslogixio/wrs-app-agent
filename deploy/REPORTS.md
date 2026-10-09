# Background PDF exports

PDF exports use the MariaDB `reports_reportjob` table and one dedicated worker. No broker or extra Python dependency is required. Queue pages show 50 distinct claims per page; table sorting applies to the current page. Dashboard totals use three database queries across all selected dealerships.

After pulling the repository, `sudo bash deploy/setup-host.sh` applies migrations and installs both `wrs-app.service` and `wrs-report-worker.service`. The worker uses the same environment file and restricted database account as Django. No email is sent by this worker.

- `sudo systemctl status wrs-report-worker`: check worker health.
- `sudo journalctl -u wrs-report-worker -n 50`: inspect completed job IDs and errors.
- `sudo systemctl restart wrs-report-worker`: restart processing.
- `python manage.py process_report_jobs --once`: process one eligible job with the configured environment.

“Export to PDF” submits a CSRF-protected request, then displays progress and an authorized download. “My PDF exports” lists the user's requests. Duplicate pending requests are reused; each user can have five pending exports. Access is checked at submission, processing, status viewing, and download. Membership or role revocation prevents access.

Interrupted jobs become eligible again after a 30-minute lease, with at most three attempts. An expired attempt cannot publish over a newer worker. Rendering failures show a generic message and are logged with the job UUID. Completed PDFs live in `REPORT_ROOT/jobs/`, are excluded from static collection/public Nginx access, and are removed after seven days. The worker cleans expired records and orphaned files hourly and restarts hourly to bound retained memory. Existing archived daily PDFs are unaffected by this cleanup.

Run checks on `wrs-agentic` using the installed virtual environment:

```bash
/opt/wrs-app/.venv/bin/python manage.py test --settings=core.test_settings --noinput
sudo /opt/wrs-app/.venv/bin/python manage.py test --settings=core.mariadb_test_settings --noinput
```

The MariaDB suite creates and drops `wrs_security_baseline`; it does not test against `wrs_app`.
