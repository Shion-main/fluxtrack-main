/* Shared Rooms & buildings behaviors: drawers, mobile filters, and URL forms. */
(function () {
  "use strict";
  var sheet = document.getElementById("sheet");
  var scrim = document.getElementById("sheet-scrim");
  if (!sheet || !scrim) return;
  var opener = null;
  var reopenFilters = false;
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea,[tabindex]:not([tabindex="-1"])';

  function openSheet() {
    sheet.hidden = false;
    scrim.hidden = false;
    requestAnimationFrame(function () {
      sheet.classList.add("is-open");
      scrim.classList.add("is-open");
    });
    var close = sheet.querySelector("[data-sheet-close]");
    if (close) close.focus();
  }

  function closeSheet() {
    if (sheet.hidden) return;
    sheet.classList.remove("is-open");
    scrim.classList.remove("is-open");
    window.setTimeout(function () {
      sheet.hidden = true;
      scrim.hidden = true;
    }, 260);
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }

  function toggleFilters(open) {
    var panel = document.getElementById("directory-filter-panel");
    var filterScrim = document.querySelector(".dir__filter-scrim");
    var button = document.querySelector("[data-filters-open]");
    if (!panel || !button) return;
    panel.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", String(open));
    if (filterScrim) {
      filterScrim.hidden = !open;
      filterScrim.classList.toggle("is-open", open);
    }
    document.documentElement.classList.toggle("dir-filters-open", open);
    if (open) {
      var first = panel.querySelector("select, input, button");
      if (first) first.focus();
    } else {
      button.focus();
    }
  }

  document.addEventListener("change", function (event) {
    if (event.target.closest(".dir__filters") &&
        document.querySelector(".dir__advanced.is-open")) {
      reopenFilters = true;
    }
  });

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-sheet-close]")) closeSheet();
    if (event.target.closest("[data-filters-open]")) toggleFilters(true);
    if (event.target.closest("[data-filters-close]")) toggleFilters(false);
    var remove = event.target.closest("[data-remove-filter]");
    if (remove) {
      var form = document.querySelector(".dir__filters");
      var field = form && form.elements[remove.dataset.removeFilter];
      if (field) {
        field.value = "";
        form.requestSubmit();
      }
    }
  });

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    if (event.detail.target && event.detail.target.id === "sheet-content") {
      opener = event.target.closest("a,button");
    }
    var directory = document.getElementById("directory-workspace");
    if (directory && event.target.closest(".dir__filters")) {
      reopenFilters = reopenFilters ||
        !!document.querySelector(".dir__advanced.is-open");
      directory.setAttribute("aria-busy", "true");
    }
  });
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id === "sheet-content") openSheet();
  });
  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.target.id !== "directory-workspace") return;
    var url = new URL(window.location.href);
    Array.from(url.searchParams.entries()).forEach(function (entry) {
      if (!entry[1]) url.searchParams.delete(entry[0]);
    });
    window.history.replaceState({}, "", url.pathname + "?" + url.searchParams.toString());
    if (reopenFilters) {
      reopenFilters = false;
      toggleFilters(true);
    }
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.detail.xhr && event.detail.xhr.status === 204 &&
        event.target.closest("#sheet-content")) closeSheet();
  });
  document.body.addEventListener("roomsStructureChanged", function () {
    var directory = document.getElementById("directory-workspace");
    if (directory && window.htmx) {
      window.htmx.ajax("GET", window.location.pathname + window.location.search, {
        target: "#directory-workspace", swap: "outerHTML"
      });
    }
  });

  sheet.addEventListener("wheel", function (event) {
    var body = sheet.querySelector(".sheet__body");
    if (!body || body.contains(event.target) || body.scrollHeight <= body.clientHeight) return;
    body.scrollTop += event.deltaY;
    event.preventDefault();
  }, { passive: false });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      if (document.querySelector(".dir__advanced.is-open")) toggleFilters(false);
      else if (!sheet.hidden) closeSheet();
      return;
    }
    if (sheet.hidden || event.key !== "Tab") return;
    var items = Array.prototype.filter.call(sheet.querySelectorAll(FOCUSABLE), function (el) {
      return el.offsetParent !== null;
    });
    if (!items.length) return;
    if (event.shiftKey && document.activeElement === items[0]) {
      event.preventDefault();
      items[items.length - 1].focus();
    } else if (!event.shiftKey && document.activeElement === items[items.length - 1]) {
      event.preventDefault();
      items[0].focus();
    }
  });
})();
