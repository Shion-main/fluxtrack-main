/* Faculty Liquid Glass behaviour. Loaded only on Faculty pages (base.html).
 *
 * One passive scroll listener, throttled to one update per frame:
 *  - .ft-top gets .is-scrolled once the page leaves the top (frosted bar);
 *  - .ft-tabbar gets .is-compact while scrolling DOWN past 64px, and loses it
 *    on any upward scroll or near the bottom of the page.
 * The CSS animates both; under reduced motion the classes still toggle but
 * nothing moves. ASCII-only.
 */
(function () {
  "use strict";
  var root = document.documentElement;
  if (!root.classList.contains("ft-glass")) return;

  var top = document.querySelector(".ft-top");
  var bar = document.querySelector(".ft-tabbar");
  /* The bar only shrinks on phones; from 48rem it sits at the top centre.
     Re-sync when the width crosses that line (rotation, split view, resize),
     or a bar shrunk on a phone would stay shrunk on a tablet. */
  var phone = window.matchMedia("(max-width: 767.98px)");
  var lastY = window.scrollY;
  var ticking = false;

  function update() {
    ticking = false;
    var y = window.scrollY;
    if (top) top.classList.toggle("is-scrolled", y > 8);
    if (bar) {
      var nearBottom = window.innerHeight + y >= root.scrollHeight - 48;
      if (!phone.matches || y < lastY || nearBottom || y <= 64) {
        bar.classList.remove("is-compact");
      } else if (y > lastY + 2) {
        bar.classList.add("is-compact");
      }
    }
    lastY = y;
  }

  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  }, { passive: true });

  if (phone.addEventListener) phone.addEventListener("change", update);
  else if (phone.addListener) phone.addListener(update);

  /* Back/forward cache restores mid-page: sync the bars without a scroll. */
  window.addEventListener("pageshow", update);
  update();

  /* Large title (spec goal 4): once the page title scrolls under the bar, a
     small copy fades in at the bar's centre. The copy is aria-hidden: screen
     readers already have the real title. Pages with their own app bar
     (sub-flows) have no large title and are skipped. */
  var big = document.querySelector(".ft-greet__hi");
  if (top && big && "IntersectionObserver" in window) {
    var tab = document.querySelector(".ft-tab.is-active .ft-tab__short");
    var mirror = document.createElement("span");
    mirror.className = "ft-top__title";
    mirror.setAttribute("aria-hidden", "true");
    mirror.textContent = (tab || big).textContent.trim();
    top.appendChild(mirror);
    new IntersectionObserver(function (entries) {
      var e = entries[0];
      top.classList.toggle("is-titled", !e.isIntersecting && e.boundingClientRect.top < top.offsetHeight);
    }, { rootMargin: "-" + top.offsetHeight + "px 0px 0px 0px" }).observe(big);
  }
})();
