#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/fluxtrack/current}"
VENV_DIR="${VENV_DIR:-/srv/fluxtrack/venv}"
cd "$APP_DIR"

# Serialize deploys so migrations and restarts cannot overlap.
exec 9>/run/lock/fluxtrack-deploy.lock
/usr/bin/flock --nonblock 9

"$VENV_DIR/bin/pip" install --requirement requirements.txt
"$VENV_DIR/bin/python" manage.py check --deploy
"$VENV_DIR/bin/python" manage.py migrate --noinput
"$VENV_DIR/bin/python" manage.py collectstatic --noinput

nginx -t
systemctl restart fluxtrack-web.service
systemctl restart fluxtrack-scheduler.service
systemctl enable --now fluxtrack-scheduler-watch.timer

# Nginx supplies the production proxy scheme that Django requires.
curl --fail --silent --show-error \
  --header 'Host: fluxtrack.example.edu' \
  --header 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8000/healthz/ >/dev/null

echo "FluxTrack deploy completed successfully."
