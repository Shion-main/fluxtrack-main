/**
 * Checker offline scan queue (CHK-08).
 *
 * Vanilla JS, no wrapper library (project constraint) — a small IndexedDB
 * object store keyed by a client-generated `client_uuid`, holding
 * `{client_uuid, token, action, note, scanned_at}` for each scan a Checker
 * records while offline. On reconnect the whole queue is POSTed as a batch to
 * `/checker/replay`, which RE-VALIDATES every item against CURRENT state
 * through the same pure gating core the live scan uses — never blindly
 * trusted. Items the server reports as "applied", "flagged", or "duplicate"
 * are all TERMINAL outcomes and are removed from the local queue; a network
 * failure during drain leaves the queue untouched so the next reconnect
 * retries.
 *
 * Feature-detected: if IndexedDB is unavailable, offline queueing is disabled
 * and the surface degrades (no crash) — `FluxTrackOfflineQueue.available`
 * stays false and `enqueue()` rejects.
 */
(function () {
  "use strict";

  var DB_NAME = "fluxtrack_checker_offline";
  var DB_VERSION = 1;
  var STORE = "queue";
  var REPLAY_URL = "/checker/replay";

  var available = !!window.indexedDB;
  var dbPromise = null;

  function openDB() {
    if (!available) return Promise.reject(new Error("IndexedDB unavailable"));
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      var req = window.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, {keyPath: "client_uuid"});
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
    return dbPromise;
  }

  function withStore(mode, fn) {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var store = tx.objectStore(STORE);
        var result = fn(store);
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function getAllItems() {
    if (!available) return Promise.resolve([]);
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readonly");
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function countItems() {
    return getAllItems().then(function (items) { return items.length; });
  }

  function removeItem(clientUuid) {
    return withStore("readwrite", function (store) {
      store.delete(clientUuid);
    });
  }

  function extractToken(payload) {
    payload = (payload || "").trim();
    if (!payload) return null;
    if (payload.indexOf("t=") !== -1) {
      var m = payload.match(/[?&]t=([^&]+)/);
      if (m) {
        try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
      }
    }
    if (/^\d{6}$/.test(payload)) return payload;
    return null;
  }

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
  }

  function randomUUID() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    // Fallback for browsers without crypto.randomUUID (rare, degrade gracefully).
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  /**
   * Enqueue one offline scan. `item.payload` is the raw scanned text (QR deep
   * link or six-digit manual code) — the room token is extracted client-side
   * the same way the server's `_room_from_payload` parses it. Returns the
   * stored record (with its generated client_uuid) or rejects if IndexedDB is
   * unavailable.
   */
  function enqueue(item) {
    if (!available) return Promise.reject(new Error("offline capture unavailable"));
    var token = item.token || extractToken(item.payload);
    if (!token) return Promise.reject(new Error("invalid scan payload"));
    var record = {
      client_uuid: randomUUID(),
      token: token,
      action: item.action,
      note: item.note || "",
      scanned_at: item.scanned_at || new Date().toISOString(),
    };
    return withStore("readwrite", function (store) {
      store.put(record);
    }).then(function () {
      refreshBanner();
      return record;
    });
  }

  /**
   * Drain the queue: POST every queued item as a batch to /checker/replay,
   * which re-validates each one against CURRENT state. Applied / flagged /
   * duplicate are all terminal — removed locally. A network failure leaves
   * the queue intact for the next reconnect attempt.
   */
  function drain() {
    if (!available) return Promise.resolve();
    return getAllItems().then(function (items) {
      if (!items.length) return;
      var body = JSON.stringify({
        items: items.map(function (r) {
          return {
            client_uuid: r.client_uuid, token: r.token, action: r.action,
            note: r.note, scanned_at: r.scanned_at,
          };
        }),
      });
      return fetch(REPLAY_URL, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken")},
        body: body,
      }).then(function (res) {
        if (!res.ok) return; // leave queue intact; try again next reconnect
        return res.json().then(function (data) {
          var applied = 0, flagged = 0;
          var results = (data && data.results) || [];
          return Promise.all(results.map(function (r) {
            if (r.status === "applied" || r.status === "flagged" || r.status === "duplicate") {
              if (r.status === "applied") applied += 1;
              if (r.status === "flagged") flagged += 1;
              return removeItem(r.uuid);
            }
            return Promise.resolve();
          })).then(function () {
            showSyncSummary(applied, flagged);
          });
        });
      }).catch(function () {
        // Offline again mid-drain — queue stays intact, retry on next 'online'.
      });
    });
  }

  // --- banner ----------------------------------------------------------------
  function bannerEls() {
    return {
      banner: document.getElementById("offline-banner"),
      text: document.getElementById("offline-banner-text"),
    };
  }

  function refreshBanner() {
    var els = bannerEls();
    if (!els.banner || !els.text) return;
    if (!available) {
      if (!navigator.onLine) {
        els.banner.classList.remove("hidden");
        els.text.classList.remove("text-destructive");
        els.text.textContent = "Offline — capture unavailable in this browser. Reconnect to scan.";
      } else {
        els.banner.classList.add("hidden");
      }
      return;
    }
    countItems().then(function (n) {
      els.text.classList.remove("text-destructive");
      if (!navigator.onLine) {
        els.banner.classList.remove("hidden");
        els.text.textContent = "Offline — " + n + " scan(s) queued. " +
          "They'll sync and re-check when you're back online.";
      } else if (n > 0) {
        els.banner.classList.remove("hidden");
        els.text.textContent = n + " scan(s) queued — syncing…";
      } else {
        els.banner.classList.add("hidden");
      }
    });
  }

  function showSyncSummary(applied, flagged) {
    var els = bannerEls();
    if (!els.banner || !els.text) { refreshBanner(); return; }
    if (!applied && !flagged) { refreshBanner(); return; }
    els.banner.classList.remove("hidden");
    var parts = [];
    if (applied) parts.push(applied + " queued scan(s) applied.");
    if (flagged) {
      parts.push(flagged + " queued scan(s) couldn't apply (the room changed) — sent to IFO to resolve.");
      els.text.classList.add("text-destructive");
    } else {
      els.text.classList.remove("text-destructive");
    }
    els.text.textContent = parts.join(" ");
    setTimeout(refreshBanner, 6000);
  }

  function initBanner() {
    refreshBanner();
    window.addEventListener("online", function () {
      refreshBanner();
      drain();
    });
    window.addEventListener("offline", refreshBanner);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBanner);
  } else {
    initBanner();
  }

  window.FluxTrackOfflineQueue = {
    available: available,
    enqueue: enqueue,
    drain: drain,
    count: countItems,
    initBanner: initBanner,
    extractToken: extractToken,
  };
})();
