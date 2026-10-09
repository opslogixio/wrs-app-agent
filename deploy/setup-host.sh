#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run with sudo: sudo bash deploy/setup-host.sh' >&2
    exit 1
fi
DEPLOY_SOURCE=$(cd "$(dirname "$0")/.." && pwd)
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-dev build-essential pkg-config default-libmysqlclient-dev mariadb-server nginx rsync certbot python3-certbot-nginx
id wrs-app >/dev/null 2>&1 || useradd --system --home-dir /var/lib/wrs-app --shell /usr/sbin/nologin wrs-app
install -d -m 0755 /opt/wrs-app /var/lib/wrs-app /var/lib/wrs-app/staticfiles
install -d -m 0700 /etc/wrs-app
if systemctl is-active --quiet wrs-report-worker; then systemctl stop wrs-report-worker; fi
if systemctl is-active --quiet wrs-app; then systemctl stop wrs-app; fi
rsync -a --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='*.pyc' --exclude='.env*' --exclude='*.log' --exclude=staticfiles "$DEPLOY_SOURCE/" /opt/wrs-app/
python3 -m venv /opt/wrs-app/.venv
/opt/wrs-app/.venv/bin/pip install -r /opt/wrs-app/requirements.lock.txt
/opt/wrs-app/.venv/bin/pip freeze > /opt/wrs-app/requirements.lock.txt
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('/etc/wrs-app/wrs-app.env')
if not p.exists():
    p.write_text('\n'.join([
        'DJANGO_SECRET_KEY=' + secrets.token_hex(48),
        'DB_PASSWORD=' + secrets.token_hex(32),
        'DB_NAME=wrs_app', 'DB_USER=wrs_app', 'DB_HOST=127.0.0.1', 'DB_PORT=3306',
        'DJANGO_ALLOWED_HOSTS=wrs.opslogix.io,wrs-agentic,54.166.216.124,localhost,127.0.0.1',
        'DJANGO_CSRF_TRUSTED_ORIGINS=https://wrs.opslogix.io,http://wrs-agentic,http://54.166.216.124',
        'DJANGO_STATIC_ROOT=/var/lib/wrs-app/staticfiles',
        'DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend',
    ]) + '\n')
    p.chmod(0o600)
else:
    text = p.read_text()
    text = text.replace('DJANGO_ALLOWED_HOSTS=wrs-agentic,localhost,127.0.0.1', 'DJANGO_ALLOWED_HOSTS=wrs.opslogix.io,wrs-agentic,54.166.216.124,localhost,127.0.0.1')
    text = text.replace('DJANGO_CSRF_TRUSTED_ORIGINS=http://wrs-agentic\n', 'DJANGO_CSRF_TRUSTED_ORIGINS=https://wrs.opslogix.io,http://wrs-agentic,http://54.166.216.124\n')
    text = text.replace('DJANGO_ALLOWED_HOSTS=wrs-agentic,54.166.216.124,localhost,127.0.0.1', 'DJANGO_ALLOWED_HOSTS=wrs.opslogix.io,wrs-agentic,54.166.216.124,localhost,127.0.0.1')
    text = text.replace('DJANGO_CSRF_TRUSTED_ORIGINS=http://wrs-agentic,http://54.166.216.124', 'DJANGO_CSRF_TRUSTED_ORIGINS=https://wrs.opslogix.io,http://wrs-agentic,http://54.166.216.124')
    p.write_text(text)
PY
systemctl enable --now mariadb
# Django calendar-day lookups on timestamps require named database time zones.
if ! mariadb -N -e "SELECT CONVERT_TZ('2026-01-01 00:00:00', 'UTC', 'America/New_York')" | grep -qv NULL; then
    mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb mysql
fi
python3 - <<'PY'
from pathlib import Path
import subprocess
values = dict(line.split('=', 1) for line in Path('/etc/wrs-app/wrs-app.env').read_text().splitlines() if line and not line.startswith('#'))
password = values['DB_PASSWORD'].replace('\\', '\\\\').replace("'", "''")
sql = "CREATE DATABASE IF NOT EXISTS wrs_app CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
sql += "CREATE USER IF NOT EXISTS 'wrs_app'@'127.0.0.1' IDENTIFIED BY '" + password + "';\n"
sql += "ALTER USER 'wrs_app'@'127.0.0.1' IDENTIFIED BY '" + password + "';\n"
sql += "GRANT ALL PRIVILEGES ON wrs_app.* TO 'wrs_app'@'127.0.0.1';\n"
subprocess.run(['mariadb'], input=sql, text=True, check=True)
PY
chown -R wrs-app:wrs-app /var/lib/wrs-app
install -d -o wrs-app -g wrs-app /opt/wrs-app/static/upload /opt/wrs-app/static/daily-report-pdf
touch /opt/wrs-app/django_errors.log
chown wrs-app:wrs-app /opt/wrs-app/django_errors.log
python3 - <<'PY'
import os, subprocess
from pathlib import Path
values = dict(line.split('=', 1) for line in Path('/etc/wrs-app/wrs-app.env').read_text().splitlines() if line and not line.startswith('#'))
env = {**os.environ, **values}
for args in (['check'], ['migrate', '--noinput'], ['collectstatic', '--noinput']):
    subprocess.run(['runuser', '-u', 'wrs-app', '--', '/opt/wrs-app/.venv/bin/python', 'manage.py', *args], cwd='/opt/wrs-app', env=env, check=True)
subprocess.run(['runuser', '-u', 'wrs-app', '--', '/opt/wrs-app/.venv/bin/python', 'deploy/check_application.py'], cwd='/opt/wrs-app', env=env, check=True)
PY
# Runtime connections can change data but cannot alter or drop the schema.
mariadb -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'wrs_app'@'127.0.0.1'; GRANT SELECT, INSERT, UPDATE, DELETE ON wrs_app.* TO 'wrs_app'@'127.0.0.1';"
install -m 0644 /opt/wrs-app/deploy/wrs-app.service /etc/systemd/system/wrs-app.service
install -m 0644 /opt/wrs-app/deploy/wrs-report-worker.service /etc/systemd/system/wrs-report-worker.service
if [ ! -f /etc/letsencrypt/live/wrs.opslogix.io/fullchain.pem ]; then
    install -m 0644 /opt/wrs-app/deploy/wrs-agentic-http.nginx /etc/nginx/sites-available/wrs-agentic
    ln -sfn /etc/nginx/sites-available/wrs-agentic /etc/nginx/sites-enabled/wrs-agentic
    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
    certbot certonly --webroot -w /var/www/html -d wrs.opslogix.io --non-interactive --agree-tos --email poit@opslogix.io
fi
python3 - <<'TLSENV'
from pathlib import Path
p = Path('/etc/wrs-app/wrs-app.env')
lines = [line for line in p.read_text().splitlines() if not line.startswith(('DJANGO_HTTPS=', 'DJANGO_CSRF_TRUSTED_ORIGINS='))]
lines.extend(['DJANGO_HTTPS=true', 'DJANGO_CSRF_TRUSTED_ORIGINS=https://wrs.opslogix.io'])
p.write_text('\n'.join(lines) + '\n')
TLSENV
install -m 0755 /opt/wrs-app/deploy/renew-certificate.sh /etc/letsencrypt/renewal-hooks/deploy/wrs-nginx-reload
install -m 0644 /opt/wrs-app/deploy/wrs-agentic.nginx /etc/nginx/sites-available/wrs-agentic
ln -sfn /etc/nginx/sites-available/wrs-agentic /etc/nginx/sites-enabled/wrs-agentic
nginx -t
systemctl daemon-reload
systemctl enable --now wrs-app wrs-report-worker nginx
systemctl restart wrs-app wrs-report-worker
systemctl reload nginx
systemctl is-active mariadb wrs-app wrs-report-worker nginx

python3 - <<'REPORTCHECK'
import os, subprocess
from pathlib import Path
values = dict(line.split('=', 1) for line in Path('/etc/wrs-app/wrs-app.env').read_text().splitlines() if line and not line.startswith('#'))
for script in ('deploy/check_report_worker.py', 'deploy/check_queue_context.py', 'deploy/check_dealer_workflows.py'):
    subprocess.run(['runuser', '-u', 'wrs-app', '--', '/opt/wrs-app/.venv/bin/python', script],
        cwd='/opt/wrs-app', env={**os.environ, **values}, check=True)
REPORTCHECK
