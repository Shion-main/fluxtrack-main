/* ============================================================================
   FluxTrack — Request a shift (three-step flow)
   ----------------------------------------------------------------------------
   Presentation only. Every field stays in one <form>, so the server contract is
   unchanged: one POST at the end, no wizard state, and with JS off all three
   panels render in sequence and submit exactly as before. This file's first act
   is to add .is-stepped, which is what makes hiding legal at all.

   Three jobs:

     1. Stepping, with a gate: you cannot leave step 1 without picking a class,
        because "select at least one class" is a server error you should never
        have to see -- the Continue button just stays disabled instead.

     2. Conditional fields. Room preference and the time-move only apply to a
        room-based target, and a per-class room picker only applies to a class
        you actually picked. Rendering a room dropdown under a class you did not
        select (or for an Online shift, which frees the room) is the specific
        thing that made the old form feel unfinished.

     3. A live plain-language summary. It states only what the user LITERALLY
        selected -- classes, modality, window -- and never what the server will
        resolve (the room). Claiming a room here would be a promise the ticket
        cannot keep: rooms are decided at Dean approval (D-06).

   Re-inits after every htmx swap, because a 400 replaces the whole partial.
   ASCII-only.
   ========================================================================== */
(function () {
  "use strict";

  var MODALITY_WORDS = {
    online: "online",
    f2f: "face-to-face",
    blended: "blended",
  };

  function init(form) {
    if (!form || form.dataset.stepInit === "1") return;
    form.dataset.stepInit = "1";
    form.classList.add("is-stepped");

    var steps = [].slice.call(form.querySelectorAll("[data-step]"));
    var markers = [].slice.call(form.querySelectorAll("[data-steps] .ft-steps__i"));
    var picks = [].slice.call(form.querySelectorAll("[data-pick]"));
    var roomBlock = form.querySelector("[data-room-block]");
    var current = 1;

    function chosen() {
      return picks.filter(function (p) { return p.checked; });
    }

    function targetModality() {
      var r = form.querySelector("[data-target-modality]:checked");
      return r ? r.value : "";
    }

    /* --- Step navigation --------------------------------------------------- */
    function show(n, moveFocus) {
      current = n;
      steps.forEach(function (s) {
        s.hidden = Number(s.dataset.step) !== n;
      });
      markers.forEach(function (m, i) {
        var on = i + 1 === n;
        m.classList.toggle("is-on", on);
        m.classList.toggle("is-done", i + 1 < n);
        // aria-current is what a screen reader uses to report position; the
        // classes only carry the visual state.
        if (on) m.setAttribute("aria-current", "step");
        else m.removeAttribute("aria-current");
      });

      var announce = form.querySelector("[data-step-announce]");
      if (announce && markers[n - 1]) {
        var label = markers[n - 1].querySelector(".ft-steps__n");
        announce.textContent =
          "Step " + n + " of " + markers.length + ": " + (label ? label.textContent : "");
      }
      if (n === 2) syncConditional();
      if (n === 3) renderSummary();

      // Only on real navigation. Doing this on the initial render would open the
      // page already scrolled past the app bar with a focus ring sitting on the
      // heading, which reads as a bug rather than as help.
      if (!moveFocus) return;

      // Focus the new panel's heading so screen-reader and keyboard users land
      // where the content changed instead of back at the top of the form.
      var head = steps[n - 1] && steps[n - 1].querySelector(".ft-step__h");
      if (head) {
        head.setAttribute("tabindex", "-1");
        head.focus({ preventScroll: true });
      }
      form.scrollIntoView({ block: "start", behavior: "smooth" });
    }

    /* --- Gate + conditional fields ----------------------------------------- */
    function syncPicks() {
      var n = chosen().length;
      var next = steps[0].querySelector("[data-next]");
      if (next) next.disabled = n === 0;

      var out = form.querySelector("[data-pick-count]");
      if (out) {
        out.textContent = n === 0
          ? "No classes selected yet."
          : n + " class" + (n === 1 ? "" : "es") + " selected.";
      }
      syncConditional();
    }

    // Availability is the expensive half of this surface (6.5s / 5488 queries
    // if rendered for every class up front), so the picker is fetched only when
    // it is actually needed, for the picked classes only. lastRoomUrl keeps a
    // re-render of the same selection from re-hitting the server.
    var lastRoomUrl = null;

    function loadRooms() {
      var picker = form.querySelector("[data-room-picker]");
      if (!picker || !window.htmx) return;

      var ids = chosen().map(function (p) { return p.value; });
      if (!ids.length) return;

      // Carry any already-chosen preference so a re-fetch does not silently
      // reset a room the user picked.
      var params = ["schedules=" + ids.join(",")];
      ids.forEach(function (id) {
        var sel = form.querySelector('[name="preferred_room_' + id + '"]');
        if (sel && sel.value) params.push("pref_" + id + "=" + encodeURIComponent(sel.value));
      });

      var url = "/faculty/modality/rooms?" + params.join("&");
      if (url === lastRoomUrl) return;
      lastRoomUrl = url;
      window.htmx.ajax("GET", url, { target: picker, swap: "innerHTML" });
    }

    function syncConditional() {
      var online = targetModality() === "online";
      // Online frees the room, so the whole block is irrelevant, not just empty.
      if (roomBlock) roomBlock.hidden = online;
      if (online || current !== 2) return;
      loadRooms();
    }

    /* --- Live summary ------------------------------------------------------ */
    function windowPhrase() {
      var mode = form.querySelector("[data-window]:checked");
      if (mode && mode.value === "single") {
        var d = form.querySelector("[data-on-date]");
        if (d && d.value) {
          var parsed = new Date(d.value + "T00:00:00");
          return "for one session on <b>" + parsed.toLocaleDateString(undefined, {
            weekday: "long", month: "long", day: "numeric",
          }) + "</b>";
        }
        return "for <b>one session</b> (pick a date)";
      }
      var w = form.querySelector("[data-weeks]");
      var n = w && w.value ? parseInt(w.value, 10) : 1;
      if (!n || n < 1) n = 1;
      return n === 1
        ? "for <b>the next class</b>"
        : "for <b>the next " + n + " weeks</b>";
    }

    function renderSummary() {
      var line = form.querySelector("[data-summary]");
      var list = form.querySelector("[data-summary-list]");
      if (!line || !list) return;

      var sel = chosen();
      var word = MODALITY_WORDS[targetModality()] || targetModality();
      var what = sel.length === 1
        ? "<b>" + sel[0].dataset.label + "</b>"
        : "<b>" + sel.length + " classes</b>";

      line.innerHTML = "Move " + what + " to <b>" + word + "</b> " + windowPhrase() + ".";

      list.innerHTML = "";
      sel.forEach(function (p) {
        var row = document.createElement("div");
        row.className = "ft-summary__row";
        var icon = document.createElement("uk-icon");
        icon.setAttribute("icon", "calendar");
        var text = document.createElement("span");
        // textContent, not innerHTML: course codes and section names are data.
        text.textContent = p.dataset.label + " · " + p.dataset.when;
        row.appendChild(icon);
        row.appendChild(text);
        list.appendChild(row);
      });
    }

    /* --- Wiring ------------------------------------------------------------ */
    form.addEventListener("click", function (e) {
      if (e.target.closest("[data-next]")) {
        if (current === 1 && chosen().length === 0) return;
        show(Math.min(current + 1, steps.length), true);
      } else if (e.target.closest("[data-back]")) {
        show(Math.max(current - 1, 1), true);
      }
    });

    form.addEventListener("change", function (e) {
      if (e.target.matches("[data-pick]")) syncPicks();
      else if (e.target.matches("[data-target-modality]")) syncConditional();
    });

    syncPicks();

    // After a 400 the server re-renders this partial with the submitted values
    // echoed back, plus the step the failure belongs to. Reopening at step 1
    // would make the user walk past choices that are already correct to reach
    // the one that is not.
    var errStep = parseInt(form.dataset.errorStep, 10);
    if (errStep >= 1 && errStep <= steps.length) {
      show(errStep, true);
    } else {
      show(1, false);
    }
  }

  function boot() {
    init(document.querySelector("[data-modality-form]"));
  }

  document.addEventListener("DOMContentLoaded", boot);
  // A 400 swaps a fresh copy of the partial in, so re-init the new form.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "modality-panel") boot();
  });
  if (document.readyState !== "loading") boot();
})();
