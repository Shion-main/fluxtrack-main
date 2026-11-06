#!/usr/bin/env bash
set -euo pipefail

# Trusted administrator-owned file; use the same environment as systemd.
ENV_FILE="${ENV_FILE:-/etc/fluxtrack/fluxtrack.env}"
if [[ ! -r "$ENV_FILE" ]]; then
  echo "Cannot read production environment: $ENV_FILE" >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
if [[ "${FLUXTRACK_ENV:-}" != "production" && "${FLUXTRACK_ENV:-}" != "prod" ]]; then
  echo "Deployment requires FLUXTRACK_ENV=production" >&2
  exit 1
fi

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
  --header "Host: ${DEPLOY_HEALTH_HOST:-${ALLOWED_HOSTS%%,*}}" \
  --header 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8000/healthz/ >/dev/null

echo "FluxTrack deploy completed successfully."
