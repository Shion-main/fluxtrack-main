"""
FluxTrack UI proof-of-concept: Django + htmx + Franken UI (no React, no Node).

Pages:
  /          Live room grid (htmx polling), confirmation modal, datepicker.
  /checker   Checker workflow proving the two hardest client-side pieces:
               - SCAN-07: QR scan (camera + file-decode) feeding the scan resolver,
                 plus the six-digit manual-code fallback.
               - CHK-08: offline scan queue in IndexedDB with replay-on-reconnect,
                 server re-validating each scan before applying/flagging.

Run:  py -3.12 poc/app.py runserver 127.0.0.1:8010
"""
import io
import json
import sys
from datetime import datetime

from django.conf import settings

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="poc-not-secret",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        MIDDLEWARE=["django.middleware.common.CommonMiddleware"],  # no CSRF: POC only
        TEMPLATES=[],
    )

import django  # noqa: E402
django.setup()

from django.http import HttpResponse, JsonResponse  # noqa: E402
from django.urls import path  # noqa: E402

# --- Franken UI + htmx CDN head + PWA shell (manifest + service worker) ---
HEAD = """
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="theme-color" content="#0a0a0a">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <link rel="apple-touch-icon" href="/icon-192.png">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/franken-ui@2.1.2/dist/css/core.min.css"/>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/franken-ui@2.1.2/dist/css/utilities.min.css"/>
  <script src="https://cdn.jsdelivr.net/npm/franken-ui@2.1.2/dist/js/core.iife.js" defer></script>
  <script src="https://cdn.jsdelivr.net/npm/franken-ui@2.1.2/dist/js/icon.iife.js" defer></script>
  <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.6/dist/htmx.min.js" defer></script>
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js'));
    }
  </script>
"""


def _page(body, extra_head=""):
    return HttpResponse(f"""<!doctype html>
<html lang="en" class="uk-theme-neutral uk-radii-md uk-shadows-sm uk-font-sm">
  <head>{HEAD}{extra_head}<title>FluxTrack UI POC</title></head>
  <body class="bg-background text-foreground">{body}</body>
</html>""")


# =====================================================================
# Page 1: live room grid (unchanged POC)
# =====================================================================
ROOMS = [
    {"code": "IT-301", "name": "Programming Lab 1", "faculty": "Prof. Mayo",    "course": "CS131"},
    {"code": "IT-302", "name": "Programming Lab 2", "faculty": "Prof. Ong",     "course": "IT221"},
    {"code": "IT-303", "name": "Lecture Room A",    "faculty": "Prof. Sabuero", "course": "CS142"},
    {"code": "IT-304", "name": "Lecture Room B",    "faculty": "Prof. Dellosa", "course": "IS101"},
]
STATUSES = [
    ("Present",  "uk-label-primary"),
    ("Occupied", "uk-label"),
    ("Absent",   "uk-label-destructive"),
    ("Vacant",   "uk-label-secondary"),
]
_tick = {"n": 0}


def _room_card(room, status_idx):
    label, label_cls = STATUSES[status_idx]
    return f"""
      <div class="uk-card uk-card-body">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="uk-card-title">{room['code']}</h3>
            <p class="uk-text-small uk-text-muted">{room['name']}</p>
          </div>
          <span class="uk-label {label_cls}">{label}</span>
        </div>
        <div class="mt-4 uk-text-small">
          <p><uk-icon icon="user" class="size-4"></uk-icon> {room['faculty']}</p>
          <p><uk-icon icon="book-open" class="size-4"></uk-icon> {room['course']}</p>
        </div>
        <button class="uk-btn uk-btn-primary uk-btn-sm mt-4 w-full"
                data-uk-toggle="target: #handover-modal">Force Handover</button>
      </div>"""


def rooms_partial(request):
    _tick["n"] += 1
    n = _tick["n"]
    cards = "".join(_room_card(r, (n + i) % len(STATUSES)) for i, r in enumerate(ROOMS))
    stamp = datetime.now().strftime("%H:%M:%S")
    return HttpResponse(f"""
      <div class="flex items-center justify-between mb-3">
        <p class="uk-text-small uk-text-muted">Live room status &middot; polled via htmx</p>
        <span class="uk-label uk-label-secondary">updated {stamp} &middot; poll #{n}</span>
      </div>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{cards}</div>""")


def index(request):
    body = """
    <div class="uk-container mt-8 mb-16">
      <div class="flex items-center gap-2 mb-1">
        <h1 class="uk-h2">FluxTrack</h1>
        <span class="uk-label uk-label-secondary">UI POC</span>
        <a href="/checker" class="uk-btn uk-btn-secondary uk-btn-sm ml-auto">Checker workflow &rarr;</a>
      </div>
      <p class="uk-text-muted mb-8">Django + htmx + Franken UI &mdash; no React, no Node runtime.</p>

      <div class="uk-card uk-card-body mb-8 max-w-sm">
        <h3 class="uk-card-title mb-4">Standalone datepicker</h3>
        <p class="uk-text-small uk-text-muted mb-2">Report date range (Franken UI web component):</p>
        <uk-input-date></uk-input-date>
      </div>

      <div id="room-grid" hx-get="/partials/rooms" hx-trigger="load, every 3s" hx-swap="innerHTML">
        <p class="uk-text-muted">Loading live room status&hellip;</p>
      </div>
    </div>

    <div id="handover-modal" data-uk-modal class="uk-modal">
      <div class="uk-modal-dialog uk-modal-body" role="dialog" aria-modal="true">
        <h2 class="uk-modal-title">Confirm Force Handover</h2>
        <p class="my-4 uk-text-small">This room holds a prior active session. Force Handover will
          auto-complete the prior session and start yours. This action is audit-logged.</p>
        <div class="flex justify-end gap-2">
          <button class="uk-btn uk-btn-default uk-btn-sm uk-modal-close" type="button">Cancel</button>
          <button class="uk-btn uk-btn-primary uk-btn-sm uk-modal-close" type="button">Confirm handover</button>
        </div>
      </div>
    </div>
    """
    return _page(body)


# =====================================================================
# Page 2: Checker workflow  (SCAN-07 + CHK-08)
# =====================================================================
def room_qr(request, code):
    """Server-generated QR poster (maps to IFO-01). Encodes a resolver deep link."""
    import qrcode
    deep = f"fluxtrack://scan?room={code}&t=QRTOKEN-{code}"
    img = qrcode.make(deep)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


def scan_resolve(request):
    """Single role-aware resolver (SCAN-01/02). Returns a discrete outcome as htmx HTML."""
    payload = (request.POST.get("payload") or "").strip()
    if payload.startswith("MANUAL:"):
        method, code = "manual code", payload.split(":", 1)[1].strip()
    else:
        method, code = "QR scan", payload

    # Deterministic demo mapping to show the discrete-outcome variety from SCAN-02.
    if method == "QR scan" and "room=" in payload:
        room = payload.split("room=")[1].split("&")[0]
        kind, title, msg, cls, confirm = (
            "room-occupied", f"Room {room} is occupied",
            "A prior session is still active in this room. Confirm a Force Handover to take over.",
            "uk-alert-destructive", True)
    elif code == "301301":
        kind, title, msg, cls, confirm = (
            "checked-in", "Checked in – Present",
            "IT-301 · CS131 · within the 15-min grace window. Actual start stamped.",
            "uk-alert-primary", False)
    elif code == "000000":
        kind, title, msg, cls, confirm = (
            "too-early", "Too early",
            "Check-in opens closer to the scheduled start time. Try again during the window.",
            "uk-alert-secondary", False)
    else:
        kind, title, msg, cls, confirm = (
            "no-schedule", "No schedule found",
            f"No session is scheduled for code '{code}' right now.",
            "uk-alert-secondary", False)

    confirm_btn = (
        '<button class="uk-btn uk-btn-primary uk-btn-sm mt-3" '
        'data-uk-toggle="target: #handover-modal">Confirm Force Handover</button>'
        if confirm else "")
    return HttpResponse(f"""
      <div class="uk-alert {cls}" data-outcome="{kind}">
        <div class="uk-alert-title flex items-center gap-2">
          <uk-icon icon="scan-line" class="size-4"></uk-icon> {title}
        </div>
        <div class="uk-alert-description">{msg}<div class="uk-text-muted mt-1">resolved via {method}</div>{confirm_btn}</div>
      </div>""")


def checker_verify(request):
    """Batch verify endpoint (CHK-08). Server re-validates each queued scan."""
    data = json.loads(request.body or b"{}")
    results = []
    for s in data.get("scans", []):
        room = s.get("room", "")
        ok = room.startswith("IT-")  # stand-in for real re-validation
        results.append({"room": room, "at": s.get("at"),
                        "status": "applied" if ok else "flagged"})
    return JsonResponse({"count": len(results), "results": results})


def checker_js(request):
    return HttpResponse(CHECKER_JS, content_type="text/javascript")


def checker(request):
    """Mobile-first Checker surface (§2.5: Faculty + Checker are mobile-first, phone role)."""
    extra = ('<script src="https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>'
             '<script src="/assets/checker.js" defer></script>')
    # Layout: single column by default (phone). max-w-md keeps it phone-width even on desktop.
    # Full-width, large tap targets (min h-11), camera-first ordering.
    body = """
    <!-- Sticky mobile app bar -->
    <header class="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border">
      <div class="max-w-md mx-auto px-4 h-14 flex items-center gap-3">
        <a href="/" class="uk-btn uk-btn-ghost uk-btn-icon" aria-label="Back">
          <uk-icon icon="arrow-left" class="size-5"></uk-icon></a>
        <div class="leading-tight">
          <p class="font-semibold">Checker</p>
          <p class="uk-text-small uk-text-muted">Floor 3 &middot; on duty</p>
        </div>
        <span id="net-state" class="uk-label uk-label-primary ml-auto">ONLINE</span>
      </div>
    </header>

    <main class="max-w-md mx-auto px-4 pt-4 pb-28 space-y-4">
      <!-- SCAN-07: camera-first, full-width primary action -->
      <section class="uk-card uk-card-body">
        <h3 class="uk-card-title mb-1">Scan a room</h3>
        <p class="uk-text-small uk-text-muted mb-4">Point the camera at the room QR, or enter the code.</p>

        <button class="uk-btn uk-btn-primary w-full h-12 text-base" onclick="startCamera()">
          <uk-icon icon="camera" class="size-5"></uk-icon> Open camera</button>
        <div id="qr-reader" class="mt-3"></div>
        <p id="cam-status" class="uk-text-small uk-text-muted mt-2"></p>

        <div class="flex items-center gap-3 my-4">
          <div class="h-px flex-1 bg-border"></div>
          <span class="uk-text-small uk-text-muted">or</span>
          <div class="h-px flex-1 bg-border"></div>
        </div>

        <label class="uk-text-small font-medium">Six-digit room code</label>
        <form onsubmit="manualResolve(event)" class="mt-2 space-y-2">
          <input id="manual-code" class="uk-input h-12 text-center text-xl tracking-widest"
                 inputmode="numeric" placeholder="000000" maxlength="6"/>
          <button class="uk-btn uk-btn-secondary w-full h-11" type="submit">Resolve code</button>
        </form>
        <p class="uk-text-small uk-text-muted mt-2">Demo: 301301 present &middot; 000000 too early.</p>

        <!-- Poster + file-decode kept for headless testing (no camera in CI) -->
        <details class="mt-3">
          <summary class="uk-text-small uk-text-muted">Test without a camera</summary>
          <img src="/room/IT-301.png" width="120" height="120" alt="IT-301 QR" class="border border-border rounded mt-2"/>
          <button class="uk-btn uk-btn-default uk-btn-sm mt-2" onclick="decodeSampleQr()">
            <uk-icon icon="scan-line" class="size-4"></uk-icon> Decode poster</button>
          <p id="qr-result" class="uk-text-small uk-text-muted mt-1"></p>
          <div id="qr-reader-file" class="hidden"></div>
        </details>

        <div id="scan-outcome" class="mt-4"></div>
      </section>

      <!-- CHK-08: offline queue -->
      <section class="uk-card uk-card-body">
        <div class="flex items-center justify-between mb-1">
          <h3 class="uk-card-title">Offline queue</h3>
          <button class="uk-btn uk-btn-ghost uk-btn-sm" onclick="toggleOffline()">
            <uk-icon icon="wifi-off" class="size-4"></uk-icon> Offline</button>
        </div>
        <p class="uk-text-small uk-text-muted mb-3">Verifications made offline are queued and replay on reconnect.</p>
        <div class="grid grid-cols-3 gap-2 mb-3">
          <button class="uk-btn uk-btn-default h-11" onclick="verifyRoom('IT-301')">301</button>
          <button class="uk-btn uk-btn-default h-11" onclick="verifyRoom('IT-302')">302</button>
          <button class="uk-btn uk-btn-default h-11" onclick="verifyRoom('IT-303')">303</button>
        </div>
        <button class="uk-btn uk-btn-primary w-full h-11 mb-3" onclick="replay()">
          <uk-icon icon="refresh-cw" class="size-4"></uk-icon> Reconnect &amp; replay</button>
        <div class="uk-text-small">
          <p>Queued in IndexedDB: <span id="queue-count" class="uk-label uk-label-secondary">0</span></p>
          <p class="uk-text-muted mt-1" id="queue-list">(empty)</p>
          <p id="verify-status" class="mt-2"></p>
        </div>
      </section>
    </main>

    <div id="handover-modal" data-uk-modal class="uk-modal">
      <div class="uk-modal-dialog uk-modal-body" role="dialog" aria-modal="true">
        <h2 class="uk-modal-title">Confirm Force Handover</h2>
        <p class="my-4 uk-text-small">Auto-completes the prior active session and starts the new one. Audit-logged.</p>
        <div class="flex justify-end gap-2">
          <button class="uk-btn uk-btn-default uk-btn-sm uk-modal-close" type="button">Cancel</button>
          <button class="uk-btn uk-btn-primary uk-btn-sm uk-modal-close" type="button">Confirm handover</button>
        </div>
      </div>
    </div>
    """
    return _page(body, extra_head=extra)


# =====================================================================
# PWA shell: manifest + service worker + icons (plain files Django serves)
# =====================================================================
def manifest(request):
    data = {
        "name": "FluxTrack", "short_name": "FluxTrack",
        "start_url": "/checker", "scope": "/",
        "display": "standalone", "orientation": "portrait",
        "background_color": "#ffffff", "theme_color": "#0a0a0a",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


def service_worker(request):
    return HttpResponse(SW_JS, content_type="text/javascript")


def icon(request, size):
    """Generate a simple branded PWA icon so the app is installable."""
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


SW_JS = r"""
const CACHE = 'fluxtrack-shell-v1';
const SHELL = ['/checker', '/assets/checker.js', '/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// Cache-first for same-origin GETs (app shell works offline); POSTs always hit the network.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return resp;
      }).catch(() => caches.match('/checker'))
    )
  );
});
"""


# Client JS kept as a raw string (never an f-string) to avoid brace collisions.
CHECKER_JS = r"""
const $ = (s, r=document) => r.querySelector(s);

// ---------- SCAN-07: QR decode (file + camera) + manual fallback ----------
async function decodeSampleQr() {
  const out = $('#qr-result');
  out.textContent = 'Decoding poster QR (no camera needed)...';
  try {
    const resp = await fetch('/room/IT-301.png');
    const file = new File([await resp.blob()], 'room.png', { type: 'image/png' });
    const decoded = await new Html5Qrcode('qr-reader-file', false).scanFile(file, false);
    out.textContent = 'Decoded deep link: ' + decoded;
    resolveScan(decoded);
  } catch (e) {
    out.textContent = 'Decode failed: ' + e;
  }
}

function startCamera() {
  const scanner = new Html5Qrcode('qr-reader');
  scanner.start({ facingMode: 'environment' }, { fps: 10, qrbox: 200 },
    (txt) => { scanner.stop(); resolveScan(txt); },
    () => {}
  ).catch((e) => {
    $('#cam-status').textContent =
      'No camera in this environment (' + e + '). Real phones use the rear camera; use Decode/manual here.';
  });
}

async function resolveScan(payload) {
  const fd = new FormData();
  fd.append('payload', payload);
  const r = await fetch('/scan/resolve', { method: 'POST', body: fd });
  $('#scan-outcome').innerHTML = await r.text();
  if (window.htmx) window.htmx.process($('#scan-outcome'));
}

function manualResolve(ev) {
  ev.preventDefault();
  resolveScan('MANUAL:' + $('#manual-code').value);
}

// ---------- CHK-08: IndexedDB offline queue + replay ----------
let simulateOffline = false;
const DB = 'fluxtrack-poc', STORE = 'scan-queue';

function idb() {
  return new Promise((res, rej) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
}
async function tx(mode, fn) {
  const db = await idb();
  return new Promise((res, rej) => {
    const t = db.transaction(STORE, mode);
    const out = fn(t.objectStore(STORE));
    t.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
    t.onerror = () => rej(t.error);
  });
}
const enqueue   = (item) => tx('readwrite', (s) => s.add(item));
const allQueued = ()     => tx('readonly',  (s) => s.getAll());
const clearAll  = ()     => tx('readwrite', (s) => s.clear());

async function refreshQueueBadge() {
  const q = await allQueued();
  $('#queue-count').textContent = q.length;
  $('#queue-list').textContent = q.length ? q.map((x) => x.room + ' @ ' + x.at).join(', ') : '(empty)';
}

async function verifyRoom(room) {
  const item = { room, at: new Date().toISOString().slice(11, 19), action: 'verified' };
  if (simulateOffline) {
    await enqueue(item);
    await refreshQueueBadge();
    $('#verify-status').textContent = 'Offline → queued locally: ' + room;
  } else {
    const j = await postScans([item]);
    $('#verify-status').textContent = 'Online → server ' + JSON.stringify(j.results);
  }
}

async function postScans(scans) {
  const r = await fetch('/checker/verify', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scans }),
  });
  return r.json();
}

async function replay() {
  const q = await allQueued();
  if (!q.length) { $('#verify-status').textContent = 'Nothing queued to replay.'; return; }
  const j = await postScans(q);        // server re-validates each before applying/flagging
  await clearAll();
  await refreshQueueBadge();
  $('#verify-status').textContent =
    'Reconnected → replayed ' + q.length + ' scan(s); server ' + JSON.stringify(j.results);
}

function toggleOffline() {
  simulateOffline = !simulateOffline;
  const el = $('#net-state');
  el.textContent = simulateOffline ? 'OFFLINE (simulated)' : 'ONLINE';
  el.className = simulateOffline ? 'uk-label uk-label-destructive ml-auto' : 'uk-label uk-label-primary ml-auto';
  if (!simulateOffline) replay();      // auto-replay on reconnect
}

window.addEventListener('DOMContentLoaded', refreshQueueBadge);
"""


urlpatterns = [
    path("", index),
    path("partials/rooms", rooms_partial),
    path("checker", checker),
    path("assets/checker.js", checker_js),
    path("room/<str:code>.png", room_qr),
    path("scan/resolve", scan_resolve),
    path("checker/verify", checker_verify),
    # PWA shell
    path("manifest.webmanifest", manifest),
    path("sw.js", service_worker),
    path("icon-<int:size>.png", icon),
]

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
