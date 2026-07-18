"""Frontend views: dev-login stub, role-routed home, and the PWA shell."""
import io

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import Role

User = get_user_model()

# DEBUG dev-login curated demo set: one clickable account per role (D-08).
# After the real 2nd Term import (Phase 04.1), the login page must NOT dump all
# ~200 imported instructors — it shows a short per-role demo list. The FACULTY
# demo is the REAL professor GARAY, CHRISTIAN DOMINIQUE (username ``cdgaray``,
# email local-part), replacing the old fake ``mayo`` seed. Any account absent
# from the live DB is simply omitted (e.g. cdgaray before the import is run, or
# the seed_demo role accounts before seed_demo is run). The passwordless-by-
# username POST is unchanged, so any of the ~200 imported instructors is still
# reachable by typing the username directly (only the visible list is curated).
DEMO_USERNAMES = ["cdgaray", "checker", "ifo", "hr", "guard", "dean", "sysadmin"]

# Role → home-screen surface cards. Phase 4 wired the faculty modality-shift request
# and Dean approval surfaces into the nav; remaining "#" hrefs are later-phase stubs
# (reporting/dashboards = Phase 6).
SURFACES = {
    Role.FACULTY: [
        {"title": "My schedule", "desc": "Today and this week.", "icon": "calendar", "href": "/faculty/schedule"},
        {"title": "Check in", "desc": "Scan a room QR or enter the code.", "icon": "scan-line", "href": "/faculty/scan"},
        {"title": "Request modality shift", "desc": "Shift a session online or to a room; your Dean approves.", "icon": "arrow-left-right", "href": "/faculty/modality/new"},
    ],
    Role.CHECKER: [
        {"title": "Floor view", "desc": "Coverage and priority queue.", "icon": "layout-grid", "href": "/checker/floor"},
        {"title": "Scan a room", "desc": "Verify presence on your floor.", "icon": "scan-line", "href": "/checker/scan"},
        {"title": "Online to verify", "desc": "Your assigned online sessions via Teams.", "icon": "video", "href": "/checker/online"},
    ],
    Role.IFO_ADMIN: [
        {"title": "Rooms", "desc": "Live room board, schedules, and QR posters.", "icon": "building", "href": "/ifo/rooms"},
        {"title": "Assignments", "desc": "Post Checkers/Guards; grant online duty.", "icon": "user-plus", "href": "/ifo/assignments"},
        {"title": "Reports", "desc": "Weekly consolidated attendance.", "icon": "file-text", "href": "/ifo/dashboard"},
    ],
    Role.HR_ADMIN: [
        {"title": "Attendance", "desc": "Verified records; export CSV.", "icon": "clipboard-list", "href": "/hr/attendance"},
    ],
    Role.GUARD: [
        {"title": "Floor monitor", "desc": "Live room status (read-only).", "icon": "shield", "href": "/guard/monitor"},
        {"title": "Faculty locator", "desc": "Find a professor on campus.", "icon": "search", "href": "/guard/locate"},
    ],
    Role.DEAN: [
        {"title": "Modality approvals", "desc": "Pending shift requests from your department.", "icon": "check-check", "href": "/dean/requests"},
        {"title": "Department oversight", "desc": "Reporting and scorecards.", "icon": "bar-chart", "href": "/dean/dashboard"},
    ],
    Role.SYSTEM_ADMIN: [
        {"title": "Job monitor", "desc": "Scheduled-job status: last run, success/failure, rows.", "icon": "activity", "href": "/sys/jobs"},
        {"title": "Users & settings", "desc": "Provision users, policy values.", "icon": "settings", "href": "/admin/"},
        {"title": "Audit log", "desc": "All write events.", "icon": "list", "href": "/admin/ops/auditlog/"},
    ],
}


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Login surface. Microsoft Entra ID SSO (Authorization Code + PKCE) is the
    real sign-in path — the "Sign in with Microsoft" button starts the round-trip
    via social-auth (see config/settings.py AUTHENTICATION_BACKENDS). In DEBUG,
    a passwordless dev-login also lets you sign in as any seeded user by username;
    it stays gated behind settings.DEBUG (D-08) and is never reachable in prod."""
    if request.user.is_authenticated:
        return redirect("/")

    if request.method == "POST" and settings.DEBUG:
        username = request.POST.get("username", "")
        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return render(request, "web/login.html", _login_ctx(error="Unknown user."))
        # Two AUTHENTICATION_BACKENDS are configured (Entra PKCE + ModelBackend),
        # so login() cannot infer the backend and would raise ValueError — name
        # ModelBackend explicitly for the dev-login path (RESEARCH Pitfall 2, D-09#3).
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("/")

    return render(request, "web/login.html", _login_ctx())


def _login_ctx(error=None):
    dev_users = (list(User.objects.filter(username__in=DEMO_USERNAMES, is_active=True)
                      .order_by("role")) if settings.DEBUG else [])
    return {"dev_mode": settings.DEBUG, "dev_users": dev_users, "error": error}


def logout_view(request):
    logout(request)
    return redirect("/login")


@login_required
def home(request):
    # Each role opens straight into its primary working surface so navigation is
    # immediate on sign-in. Roles that carry their own persistent nav -- Faculty
    # and Checker (bottom tab bars) and HR (a single surface) -- redirect into it.
    # Multi-surface roles without a persistent console yet (IFO, Dean, Guard,
    # SysAdmin, and break-glass superusers) land on the role hub, which lists the
    # surfaces they own. The demo-scaffold launcher is gone (web/home.html).
    _direct_home = {
        Role.FACULTY: "faculty_home",
        Role.CHECKER: "checker_floor",
        Role.HR_ADMIN: "hr_attendance",
        Role.IFO_ADMIN: "ifo_rooms",
        Role.DEAN: "dean_dashboard",
        Role.GUARD: "guard_monitor",
    }
    target = _direct_home.get(request.user.role)
    if target:
        return redirect(target)
    return render(request, "web/home.html", {"surfaces": SURFACES.get(request.user.role, [])})


# --- PWA shell ---------------------------------------------------------------
def manifest(request):
    return JsonResponse({
        "name": "FluxTrack", "short_name": "FluxTrack",
        "start_url": "/", "scope": "/", "display": "standalone", "orientation": "portrait",
        "background_color": "#ffffff", "theme_color": "#0a0a0a",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }, content_type="application/manifest+json")


SW_JS = r"""
const CACHE = 'fluxtrack-shell-v5';
// Precache only stable, non-redirecting assets. '/' redirects when anonymous,
// so caching it (and replaying the redirect) breaks navigation — never precache it.
const SHELL = ['/login', '/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => e.waitUntil(
  caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())
));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;

  // HTML navigations: network-first, fall back to the login shell offline.
  // Never cache navigations — they may be redirects, which break when replayed.
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/login')));
    return;
  }

  // Static assets: cache-first, and only cache clean 200 same-origin responses.
  e.respondWith(
    caches.match(req).then((hit) =>
      hit || fetch(req).then((resp) => {
        if (resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      })
    )
  );
});

// Web push (NOTIF-02). EVERY push MUST show a notification: iOS revokes the
// subscription for a silent push (RESEARCH Pitfall 2), so there is no early
// return -- a parse failure falls back to a generic FluxTrack alert and still
// calls showNotification. The payload (title/body/link) is written by the 05-03
// outbox sender.
self.addEventListener('push', (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (err) { data = {}; }
  const title = data.title || 'FluxTrack';
  const link = data.link || '/notifications';
  const options = {
    body: data.body || 'You have a new notification.',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { link: link },
    tag: data.tag || 'fluxtrack',
  };
  e.waitUntil(self.registration.showNotification(title, options));
});

// Deep-link a notification tap to its target (data.link). Focus an already-open
// client on that URL if one exists, otherwise open a new window; fall back to
// /notifications when no link was supplied.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const link = (e.notification.data && e.notification.data.link) || '/notifications';
  const target = new URL(link, self.location.origin).href;
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === target && 'focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(link);
      return undefined;
    })
  );
});
"""


def service_worker(request):
    return HttpResponse(SW_JS, content_type="text/javascript")


def icon(request, size):
    """PWA / favicon icon: the MMCM crest, resized to the requested size.

    Serves static/brand/mmcm-crest.png — resolved via the staticfiles finders
    in dev and via STATIC_ROOT after collectstatic in prod. Falls back to a
    procedural mark if the asset or Pillow is unavailable, so the icon
    endpoints (used by the manifest, apple-touch-icon, and the service worker
    precache) never 500.
    """
    from PIL import Image
    s = int(size)
    try:
        from django.contrib.staticfiles import finders
        path = finders.find("brand/mmcm-crest.png")
        if not path and settings.STATIC_ROOT:
            from pathlib import Path
            candidate = Path(settings.STATIC_ROOT) / "brand" / "mmcm-crest.png"
            path = str(candidate) if candidate.exists() else None
        if path:
            img = Image.open(path).convert("RGBA").resize((s, s), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return HttpResponse(buf.getvalue(), content_type="image/png")
    except Exception:
        pass
    # Fallback: procedural placeholder keeps the endpoint alive (navy on-brand).
    from PIL import ImageDraw
    img = Image.new("RGB", (s, s), "#0f2554")
    d = ImageDraw.Draw(img)
    pad = s // 4
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=s // 12,
                        outline="white", width=max(2, s // 24))
    d.line([s // 2, pad, s // 2, s - pad], fill="white", width=max(2, s // 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")
