/* ============================================================================
   FluxTrack — IFO room board
   ----------------------------------------------------------------------------
   Two jobs, both of which exist because #board is replaced wholesale every poll:

     1. Filtering. Every room is already in the DOM, so filtering is a local
        show/hide -- instant, no round trip. But a poll swap rebuilds the tiles,
        so the active filters have to be re-applied after each swap or the board
        would silently "unfilter" itself every few seconds.

     2. The slide-over. It lives outside #board so a poll can't close it, and it
        needs the focus handling a dialog owes a keyboard user: focus moves in,
        Tab is trapped, Esc closes, focus returns to the tile you opened.

   ASCII-only.
   ========================================================================== */
(function () {
  "use strict";

  var bd = document.getElementById("bd");
  if (!bd) return;

  var board = document.getElementById("board");
  var nomatch = document.getElementById("bd-nomatch");
  var filters = { building: "", alert: false, q: "" };

  /* --- Filtering ---------------------------------------------------------- */

  function matches(tile) {
    if (filters.building && tile.dataset.building !== filters.building) return false;
    if (filters.alert) {
      var s = tile.dataset.state;
      if (s !== "absent" && s !== "starting") return false;
    }
    if (filters.q && tile.dataset.search.indexOf(filters.q) === -1) return false;
    return true;
  }

  function apply() {
    var shown = 0;

    board.querySelectorAll("[data-group]").forEach(function (group) {
      var visible = 0;
      group.querySelectorAll("[data-tile]").forEach(function (tile) {
        var ok = matches(tile);
        tile.hidden = !ok;
        if (ok) visible++;
      });
      // A floor with nothing left to show is noise, not information.
      group.hidden = visible === 0;
      var count = group.querySelector("[data-group-count]");
      if (count) count.textContent = visible + " room" + (visible === 1 ? "" : "s");
      shown += visible;
    });

    var filtering = filters.building || filters.alert || filters.q;
    if (nomatch) nomatch.hidden = !(filtering && shown === 0);
  }

  bd.addEventListener("click", function (e) {
    var chip = e.target.closest("[data-filter]");
    if (chip && chip.tagName === "BUTTON") {
      var kind = chip.dataset.filter;
      if (kind === "building") {
        filters.building = chip.dataset.value;
        // Building is single-select: exactly one chip is pressed at a time.
        bd.querySelectorAll('[data-filter="building"]').forEach(function (c) {
          c.setAttribute("aria-pressed", String(c === chip));
        });
      } else if (kind === "alert") {
        filters.alert = chip.getAttribute("aria-pressed") !== "true";
        chip.setAttribute("aria-pressed", String(filters.alert));
      }
      apply();
      return;
    }

    if (e.target.closest("[data-clear-filters]")) {
      filters = { building: "", alert: false, q: "" };
      bd.querySelectorAll('[data-filter="building"]').forEach(function (c) {
        c.setAttribute("aria-pressed", String(c.dataset.value === ""));
      });
      var alertChip = bd.querySelector('[data-filter="alert"]');
      if (alertChip) alertChip.setAttribute("aria-pressed", "false");
      var search = bd.querySelector('[data-filter="q"]');
      if (search) search.value = "";
      apply();
    }
  });

  var searchInput = bd.querySelector('[data-filter="q"]');
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      filters.q = this.value.trim().toLowerCase();
      apply();
    });
  }

  /* --- Poll lifecycle ----------------------------------------------------- */

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id !== "board") return;
    apply();
    // Keep the "needs attention" badge honest after a swap.
    var badge = bd.querySelector("[data-alert-count]");
    if (badge) {
      badge.textContent = board.querySelectorAll(
        '[data-tile][data-state="absent"], [data-tile][data-state="starting"]'
      ).length;
    }
  });

  // A stale-but-labelled board beats a blank one: if a poll fails, say so and
  // keep the last good tiles on screen.
  function stale(isStale) {
    var stamp = board.querySelector("[data-stamp]");
    if (!stamp) return;
    stamp.classList.toggle("is-stale", isStale);
    if (isStale) stamp.lastChild.textContent = " reconnecting...";
  }
  document.body.addEventListener("htmx:sendError", function (e) {
    if (e.target.id === "board") stale(true);
  });
  document.body.addEventListener("htmx:responseError", function (e) {
    if (e.target.id === "board") stale(true);
  });
  document.body.addEventListener("htmx:afterOnLoad", function (e) {
    if (e.target.id === "board") stale(false);
  });

  /* --- Slide-over --------------------------------------------------------- */

  var sheet = document.getElementById("sheet");
  var scrim = document.getElementById("sheet-scrim");
  var opener = null;
  var FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

  function openSheet() {
    sheet.hidden = false;
    scrim.hidden = false;
    // Two frames: `hidden` removal has to land before the class flips, or the
    // transition has nothing to animate from.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        sheet.classList.add("is-open");
        scrim.classList.add("is-open");
      });
    });
    var close = sheet.querySelector("[data-sheet-close]");
    if (close) close.focus();
  }

  function closeSheet() {
    if (sheet.hidden) return;
    sheet.classList.remove("is-open");
    scrim.classList.remove("is-open");
    var done = function () {
      sheet.hidden = true;
      scrim.hidden = true;
      sheet.removeEventListener("transitionend", done);
    };
    sheet.addEventListener("transitionend", done);
    // Belt and braces: transitionend never fires under reduced motion in some
    // engines, and a permanently-open invisible dialog would eat every click.
    setTimeout(done, 320);
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var tile = e.target.closest("[data-tile]");
    if (tile) opener = tile;
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "sheet-content") openSheet();
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-sheet-close]")) closeSheet();
  });

  document.addEventListener("keydown", function (e) {
    if (sheet.hidden) return;
    if (e.key === "Escape") {
      closeSheet();
      return;
    }
    if (e.key !== "Tab") return;

    var items = Array.prototype.filter.call(
      sheet.querySelectorAll(FOCUSABLE),
      function (el) { return el.offsetParent !== null; }
    );
    if (!items.length) return;
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  });

  apply();
})();
