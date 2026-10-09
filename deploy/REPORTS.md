# Background PDF exports

PDF exports use the MariaDB `reports_reportjob` table and one dedicated worker. No broker or extra Python dependency is required. Queue pages show 50 distinct claims per page; table sorting applies to the current page. Dashboard totals use three database queries across all selected dealerships.

After pulling the repository, `sudo bash deploy/setup-host.sh` applies migrations and installs both `wrs-app.service` and `wrs-report-worker.service`. The worker uses the same environment file and restricted database account as Django. No email is sent by this worker.

- `sudo systemctl status wrs-report-worker`: check worker health.
- `sudo journalctl -u wrs-report-worker -n 50`: inspect completed job IDs and errors.
- `sudo systemctl restart wrs-report-worker`: restart processing.
- `python manage.py process_report_jobs --once`: process one eligible job with the configured environment.

“Export to PDF” submits a CSRF-protected request from the current report page, polls progress, and automatically downloads the PDF without navigating away. There is no export history or regeneration page. Duplicate pending requests are reused; each user can have five pending exports. Access is checked at submission, processing, status viewing, and download. Membership or role revocation prevents access.

Interrupted jobs become eligible again after a 30-minute lease, with at most three attempts. An expired attempt cannot publish over a newer worker. Rendering failures show a generic message and are logged with the job UUID. Completed PDFs live in `REPORT_ROOT/jobs/`, are excluded from static collection/public Nginx access, and are removed immediately after download. Abandoned exports expire after one hour. The worker cleans expired records and orphaned files hourly and restarts hourly to bound retained memory. Existing archived daily PDFs are unaffected by this cleanup.

Run checks on `wrs-agentic` using the installed virtual environment:

```bash
/opt/wrs-app/.venv/bin/python manage.py test --settings=core.test_settings --noinput
sudo /opt/wrs-app/.venv/bin/python manage.py test --settings=core.mariadb_test_settings --noinput
```

The MariaDB suite creates and drops `wrs_security_baseline`; it does not test against `wrs_app`.

## Timestamp migration

The model timestamp migrations convert legacy dates to midnight in
`America/New_York`; the original time of day cannot be recovered. New events
retain their actual timestamps. Report date selectors still select whole local
calendar days, including late-evening activity. Named MariaDB timezone tables
are loaded by `setup-host.sh` for Django date lookups.

Before applying these migrations, take a database backup and restore it into a
separate database. With that database configured in the environment, run
`python deploy/verify_timestamp_migration.py snapshot /secure/path/before.json`,
`python manage.py migrate`, then the same verifier with `verify` instead of
`snapshot`. It checks every application row, legacy local dates, nulls, and row
counts. Repeat the snapshot/verification on the active database while app and
worker services are stopped. Keep the backup: these data migrations are
intentionally irreversible rather than discarding timestamp precision.
