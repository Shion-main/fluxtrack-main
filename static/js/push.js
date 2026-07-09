/**
 * Web-push client flow (NOTIF-02, D-07).
 *
 * Vanilla JS, no wrapper library (project constraint). Drives the soft
 * pre-prompt banner and the settings-page push control:
 *
 *   currentState() -> 'unsupported' | 'default' | 'subscribed' | 'granted' | 'denied'
 *   enablePush()   -> requests the REAL browser permission (only on an explicit
 *                     Enable tap, D-07) then PushManager.subscribe + POST the
 *                     subscription to the server.
 *
 * D-07 hazard: the browser permission prompt fires ONLY from enablePush(), never
 * automatically -- so a stray "Block" can never be triggered by an ignored or
 * dismissed banner, keeping the origin re-askable from the settings page.
 *
 * The banner and the settings control read the VAPID public key + CSRF token from
 * data attributes on their host element (supplied by the server templates). All
 * source comments are ASCII-only (Windows console is cp1252).
 */
(function () {
  "use strict";

  var NOT_NOW_KEY = "fluxtrack-push-not-now";
  var SUBSCRIBE_URL = "/notifications/push/subscribe";
  var UNSUBSCRIBE_URL = "/notifications/push/unsubscribe";

  function supported() {
    return ("serviceWorker" in navigator)
        && ("PushManager" in window)
        && ("Notification" in window);
  }

  // Convert the base64url VAPID public key into the Uint8Array PushManager wants
  // for applicationServerKey (RESEARCH Pattern 3).
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var raw = window.atob(base64);
    var output = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) {
      output[i] = raw.charCodeAt(i);
    }
    return output;
  }

  function getRegistration() {
    return navigator.serviceWorker.ready;
  }

  // Promise of the current push state. 'granted' means the browser permission is
  // granted but no PushSubscription exists yet; 'subscribed' means both hold.
  function currentState() {
    if (!supported()) {
      return Promise.resolve("unsupported");
    }
    var perm = Notification.permission; // 'default' | 'granted' | 'denied'
    if (perm === "denied") {
      return Promise.resolve("denied");
    }
    if (perm === "default") {
      return Promise.resolve("default");
    }
    return getRegistration().then(function (reg) {
      return reg.pushManager.getSubscription().then(function (sub) {
        return sub ? "subscribed" : "granted";
      });
    }).catch(function () {
      return "granted";
    });
  }

  function postJSON(url, csrftoken, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken, // Pitfall 5: the raw fetch must send CSRF itself
      },
      body: JSON.stringify(body),
    });
  }

  // Subscribe through PushManager and persist to the server. Assumes the browser
  // permission is already 'granted' (enablePush requests it first).
  function subscribe(vapidKey, csrftoken) {
    return getRegistration().then(function (reg) {
      return reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      });
    }).then(function (sub) {
      return postJSON(SUBSCRIBE_URL, csrftoken, sub.toJSON());
    });
  }

  // D-07: the ONLY place the real Notification.requestPermission() fires.
  function enablePush(vapidKey, csrftoken) {
    if (!supported() || !vapidKey) {
      return Promise.resolve("unsupported");
    }
    return Notification.requestPermission().then(function (perm) {
      if (perm !== "granted") {
        return perm; // 'denied' or 'default' (dismissed) -- nothing persisted
      }
      return subscribe(vapidKey, csrftoken).then(function () {
        return "subscribed";
      });
    });
  }

  function unsubscribe(csrftoken) {
    return getRegistration().then(function (reg) {
      return reg.pushManager.getSubscription().then(function (sub) {
        if (!sub) {
          return Promise.resolve();
        }
        var endpoint = sub.endpoint;
        return sub.unsubscribe().then(function () {
          return postJSON(UNSUBSCRIBE_URL, csrftoken, { endpoint: endpoint });
        });
      });
    });
  }

  // The global soft pre-prompt banner. Shows only when we can still ask
  // (state 'default') and the user has not dismissed it (D-07). If permission is
  // already 'granted' but no subscription exists, silently re-subscribe (no
  // prompt) so a cache bump / cleared subscription self-heals.
  function initBanner(banner, vapidKey, csrftoken) {
    var enableBtn = document.getElementById("push-enable");
    var dismissBtn = document.getElementById("push-dismiss");

    currentState().then(function (state) {
      if (state === "granted" && vapidKey) {
        subscribe(vapidKey, csrftoken).catch(function () {});
        return;
      }
      if (state === "default" && vapidKey && !readNotNow()) {
        banner.hidden = false;
      }
    });

    if (enableBtn) {
      enableBtn.addEventListener("click", function () {
        enablePush(vapidKey, csrftoken).then(function () {
          banner.hidden = true;
        });
      });
    }
    if (dismissBtn) {
      dismissBtn.addEventListener("click", function () {
        writeNotNow();
        banner.hidden = true;
      });
    }
  }

  function readNotNow() {
    try {
      return !!window.localStorage.getItem(NOT_NOW_KEY);
    } catch (e) {
      return false;
    }
  }

  function writeNotNow() {
    try {
      window.localStorage.setItem(NOT_NOW_KEY, "1");
    } catch (e) {
      // localStorage unavailable (private mode) -- banner simply reappears.
    }
  }

  // Populate the settings-page #push-controls placeholder with the state-driven
  // control: Enable, a "turn off" for an active subscription, or a passive note
  // for a denied/unsupported origin (a denied origin cannot be re-prompted from
  // the page -- T-05-16).
  function initSettings(controls, vapidKey, csrftoken) {
    function render(state) {
      controls.innerHTML = "";
      if (state === "unsupported" || !vapidKey) {
        controls.appendChild(note("Push notifications are not available on this browser."));
        return;
      }
      if (state === "denied") {
        controls.appendChild(note("Blocked -- re-enable notifications in your browser settings."));
        return;
      }
      if (state === "subscribed") {
        controls.appendChild(note("Push notifications are on for this device."));
        controls.appendChild(button("Turn off", "uk-btn-default", function () {
          unsubscribe(csrftoken).then(refresh);
        }));
        return;
      }
      // 'default' or 'granted' without a subscription -> offer Enable.
      controls.appendChild(button("Enable push", "uk-btn-primary", function () {
        enablePush(vapidKey, csrftoken).then(refresh);
      }));
    }
    function refresh() {
      currentState().then(render);
    }
    refresh();
  }

  function note(text) {
    var p = document.createElement("p");
    p.className = "uk-text-small uk-text-muted";
    p.textContent = text;
    return p;
  }

  function button(label, variant, onClick) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "uk-btn uk-btn-sm " + variant;
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }

  function boot() {
    var banner = document.getElementById("push-banner");
    var controls = document.getElementById("push-controls");
    var host = banner || controls;
    if (!host) {
      return;
    }
    var vapidKey = host.getAttribute("data-vapid-key") || "";
    var csrftoken = host.getAttribute("data-csrftoken") || "";
    if (banner) {
      initBanner(banner, vapidKey, csrftoken);
    }
    if (controls) {
      initSettings(controls, vapidKey, csrftoken);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // Exposed for inline handlers / tests.
  window.FluxTrackPush = {
    urlBase64ToUint8Array: urlBase64ToUint8Array,
    currentState: currentState,
    enablePush: enablePush,
    unsubscribe: unsubscribe,
  };
})();
