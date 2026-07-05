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
        {"title": "Rooms", "desc": "Per-room schedules and QR posters.", "icon": "building", "href": "/ifo/rooms"},
        {"title": "Live today", "desc": "Room status, polled.", "icon": "radio", "href": "/ifo/live"},
        {"title": "Assignments", "desc": "Post Checkers/Guards; grant online duty.", "icon": "user-plus", "href": "/ifo/assignments"},
        {"title": "Reports", "desc": "Weekly consolidated attendance.", "icon": "file-text", "href": "#"},
    ],
    Role.HR_ADMIN: [
        {"title": "Attendance", "desc": "Verified records; export CSV.", "icon": "clipboard-list", "href": "#"},
    ],
    Role.GUARD: [
        {"title": "Floor monitor", "desc": "Live room status (read-only).", "icon": "shield", "href": "#"},
        {"title": "Faculty locator", "desc": "Find a professor on campus.", "icon": "search", "href": "#"},
    ],
    Role.DEAN: [
        {"title": "Modality approvals", "desc": "Pending shift requests from your department.", "icon": "check-check", "href": "/dean/requests"},
        {"title": "Department oversight", "desc": "Reporting and scorecards.", "icon": "bar-chart", "href": "#"},
    ],
    Role.SYSTEM_ADMIN: [
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
    dev_users = list(User.objects.filter(is_active=True).order_by("role")) if settings.DEBUG else []
    return {"dev_mode": settings.DEBUG, "dev_users": dev_users, "error": error}


def logout_view(request):
    logout(request)
    return redirect("/login")


@login_required
def home(request):
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
const CACHE = 'fluxtrack-shell-v2';
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
"""


def service_worker(request):
    return HttpResponse(SW_JS, content_type="text/javascript")


def icon(request, size):
    from PIL import Image, ImageDraw
    s = int(size)
    img = Image.new("RGB", (s, s), "#0a0a0a")
    d = ImageDraw.Draw(img)
    pad = s // 4
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=s // 12,
                        outline="white", width=max(2, s // 24))
    d.line([s // 2, pad, s // 2, s - pad], fill="white", width=max(2, s // 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")
