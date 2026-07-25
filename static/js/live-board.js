/* Live-only room filtering and poll lifecycle. URL state is bookmarkable. */
(function () {
  "use strict";
  var root = document.getElementById("bd");
  var board = document.getElementById("board");
  if (!root || !board) return;

  var search = root.querySelector('[data-filter="q"]');
  var activeBuilding = root.querySelector('[data-filter="building"][aria-pressed="true"]');
  var activeStatus = root.querySelector(
    '[data-filter="status"][aria-pressed="true"], [data-filter="alert"][aria-pressed="true"]'
  );
  var state = {
    building: activeBuilding ? activeBuilding.dataset.value : "",
    status: activeStatus
      ? (activeStatus.dataset.filter === "alert" ? "attention" : activeStatus.dataset.value)
      : "",
    q: search ? search.value.trim().toLowerCase() : ""
  };
  var nomatch = document.getElementById("bd-nomatch");
  var urlTimer = null;

  function matches(tile) {
    if (state.building && tile.dataset.building !== state.building) return false;
    if (state.status === "attention" &&
        tile.dataset.state !== "absent" && tile.dataset.state !== "starting") return false;
    if (state.status && state.status !== "attention" &&
        tile.dataset.state !== state.status) return false;
    return !state.q || tile.dataset.search.indexOf(state.q) !== -1;
  }

  function syncUrl() {
    var url = new URL(window.location.href);
    ["building", "status", "q"].forEach(function (key) {
      if (state[key]) url.searchParams.set(key, state[key]);
      else url.searchParams.delete(key);
    });
    url.searchParams.delete("view");
    window.history.replaceState({}, "", url.pathname + (url.search ? url.search : ""));
  }

  function apply(updateUrl) {
    var shown = 0;
    board.querySelectorAll("[data-group]").forEach(function (group) {
      var visible = 0;
      group.querySelectorAll("[data-tile]").forEach(function (tile) {
        var ok = matches(tile);
        tile.hidden = !ok;
        if (ok) visible++;
      });
      group.hidden = visible === 0;
      var count = group.querySelector("[data-group-count]");
      if (count) count.textContent = visible + " room" + (visible === 1 ? "" : "s");
      shown += visible;
    });
    if (nomatch) nomatch.hidden = !(shown === 0 && (state.building || state.status || state.q));
    if (updateUrl) syncUrl();
  }

  root.addEventListener("click", function (event) {
    var chip = event.target.closest("[data-filter]");
    if (chip && chip.tagName === "BUTTON") {
      var kind = chip.dataset.filter;
      if (kind === "building") {
        state.building = chip.dataset.value;
        root.querySelectorAll('[data-filter="building"]').forEach(function (item) {
          item.setAttribute("aria-pressed", String(item === chip));
        });
      } else if (kind === "alert" || kind === "status") {
        var value = kind === "alert" ? "attention" : chip.dataset.value;
        state.status = state.status === value ? "" : value;
        root.querySelectorAll('[data-filter="alert"], [data-filter="status"]').forEach(function (item) {
          var itemValue = item.dataset.filter === "alert" ? "attention" : item.dataset.value;
          item.setAttribute("aria-pressed", String(state.status === itemValue));
        });
      }
      apply(true);
      return;
    }
    if (event.target.closest("[data-clear-filters]")) {
      state = { building: "", status: "", q: "" };
      root.querySelectorAll('[data-filter="building"]').forEach(function (item) {
        item.setAttribute("aria-pressed", String(item.dataset.value === ""));
      });
      root.querySelectorAll('[data-filter="alert"], [data-filter="status"]').forEach(function (item) {
        item.setAttribute("aria-pressed", "false");
      });
      if (search) search.value = "";
      apply(true);
    }
  });

  if (search) {
    search.addEventListener("input", function () {
      state.q = search.value.trim().toLowerCase();
      apply(false);
      window.clearTimeout(urlTimer);
      urlTimer = window.setTimeout(syncUrl, 250);
    });
  }

  document.addEventListener("keydown", function (event) {
    var typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (event.key === "/" && !typing && search) {
      event.preventDefault();
      search.focus();
    } else if (event.key === "Escape" && document.activeElement === search && search.value) {
      search.value = "";
      state.q = "";
      apply(true);
    }
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "board") return;
    apply(false);
    var badge = root.querySelector("[data-alert-count]");
    if (badge) badge.textContent = board.querySelectorAll(
      '[data-tile][data-state="absent"], [data-tile][data-state="starting"]'
    ).length;
  });

  function stale(isStale) {
    var stamp = board.querySelector("[data-stamp]");
    if (!stamp) return;
    stamp.classList.toggle("is-stale", isStale);
    if (isStale) stamp.lastChild.textContent = " reconnecting...";
  }
  ["htmx:sendError", "htmx:responseError"].forEach(function (name) {
    document.body.addEventListener(name, function (event) {
      if (event.target.id === "board") stale(true);
    });
  });
  document.body.addEventListener("htmx:afterOnLoad", function (event) {
    if (event.target.id === "board") stale(false);
  });
  apply(false);
})();
