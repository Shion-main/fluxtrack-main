# FluxTrack AWS deployment runbook

This package targets one Ubuntu EC2 host running Nginx, Gunicorn, and exactly one
APScheduler process, with SQL Server Express on private-subnet RDS. Replace every
`fluxtrack.example.edu` placeholder before installation.

## Provision and install

1. Put EC2 in a public subnet and RDS in private subnets. Permit public 80/443 to
   EC2, restrict SSH to administrator addresses, and permit RDS 1433 only from the
   EC2 security group. Keep RDS public access disabled.
2. Install Python 3.12, Nginx, `util-linux` (`flock`), curl, and Microsoft ODBC
   Driver 18. Create user `fluxtrack`, `/srv/fluxtrack/current`, the virtualenv,
   and `/srv/fluxtrack/shared/media`; make the last path writable by
   `fluxtrack:www-data`.
3. Store production variables at `/etc/fluxtrack/fluxtrack.env`, mode `0640`, owned
   by `root:fluxtrack`. Set `FLUXTRACK_ENV=production`, strong secrets, explicit
   hosts, the HTTPS Entra redirect, `MEDIA_ROOT=/srv/fluxtrack/shared/media`, and
   encrypted RDS settings. Never run `seed_demo` in production.
4. Register that exact HTTPS callback in Entra, keep Authorization Code + PKCE,
   pre-provision users, and create one audited break-glass Django superuser with a
   generated password held in the institutional password vault.
5. Copy the systemd files to `/etc/systemd/system/`, the Nginx file to
   `/etc/nginx/sites-available/fluxtrack`, enable the site, issue a trusted TLS
   certificate, then run `systemctl daemon-reload` and `sudo deploy/deploy.sh`.

## Deploy and rollback

Deploy only a reviewed commit. Take an RDS snapshot before schema changes, update
the checkout, and run `deploy/deploy.sh`; it installs dependencies, runs Django's
deployment checks, migrates, collects hashed static assets, validates Nginx,
restarts both processes, starts the watchdog timer, and probes `/healthz/`.

For rollback, restore the prior code commit and rerun the script only when its
migrations are backward-compatible. Otherwise restore the pre-deploy RDS snapshot
to a new instance, point the environment at it, and restart both units. Never
reverse an irreversible migration against the only production database.

## Monitoring

Use `journalctl -u fluxtrack-web -u fluxtrack-scheduler` for structured process
logs. Monitor Nginx 5xx rate, EC2 disk/memory, RDS CPU/storage/connections, TLS
expiry, and `/healthz/`. The five-minute systemd watchdog runs `checkscheduler`;
a stale heartbeat both fails visibly in systemd and creates a deduplicated in-app
alert for System Administrators. Inspect failed `JobRun` rows after every alert.

## Backups and recovery

- Enable RDS automated backups with the institution's retention window and
  point-in-time recovery. Take a manual snapshot before every migration release.
- EC2-local media is outside RDS backups. Snapshot the encrypted EBS volume daily
  and copy `/srv/fluxtrack/shared/media` to a versioned, encrypted backup target.
  Imports and reports are private; do not publish the backup or the parent media
  directory through Nginx.
- Run a quarterly restore drill: restore RDS point-in-time data to a new private
  instance, restore media to a clean volume, deploy the matching commit, run
  `check --deploy`, and verify login, one authorized report download, one profile
  photo, scheduler heartbeat, and audit history. Record recovery time and findings.

After any credential exposure, rotate the Django secret, DB login, Entra client
secret, VAPID key, TLS key, and break-glass password as applicable, then invalidate
active sessions.
