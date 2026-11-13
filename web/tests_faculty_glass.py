"""Faculty Liquid Glass contract tests (plan 2026-11-08-faculty-liquid-glass).

One class per plan task. They read the shipped CSS, JS and templates, and render
the Faculty pages, so the glass layer cannot leak into Checker or Guard and its
text cannot drop below AA without a test failing first.
"""
import colorsys
import re

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from accounts.models import Role
from web.tests_design_system import ROOT, _read, _theme_block

GLASS = "static/faculty/glass.css"
TAB_PAGES = ["/faculty/home", "/faculty/schedule", "/faculty/online",
             "/faculty/history", "/faculty/modality/mine"]


def _css(rel=GLASS):
    return re.sub(r"/\*.*?\*/", "", _read(rel), flags=re.S)


def _token(name):
    m = re.search(rf"{re.escape(name)}\s*:\s*([^;]+);", _theme_block())
    if not m:
        raise AssertionError(f"{name} is not set in tokens.css")
    return m.group(1).strip()


def _hsl_rgb(name):
    h, s, l = (float(v.rstrip("%")) for v in _token(name).split())
    return colorsys.hls_to_rgb(h / 360, l / 100, s / 100)


def _composite(fg, alpha, bg):
    return tuple(alpha * f + (1 - alpha) * b for f, b in zip(fg, bg))


def _lum(rgb):
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _faculty_nav(body):
    m = re.search(r'<nav class="ft-tabbar" aria-label="Faculty">(.*?)</nav>', body, re.S)
    return m.group(1) if m else ""


def _html_tag(body):
    m = re.search(r"<html[^>]*>", body)
    return m.group(0) if m else ""


class _Login:
    def login_as(self, role, name):
        u = get_user_model().objects.create(username=name, role=role, first_name="Ana")
        self.client.force_login(u)
        return u


class GlassShellTests(_Login, TestCase):
    def test_faculty_pages_load_the_glass_layer(self):
        self.login_as(Role.FACULTY, "glass_fac")
        body = self.client.get("/faculty/home").content.decode()
        self.assertIn("ft-glass", _html_tag(body))
        self.assertIn("faculty/glass.css", body)
        self.assertIn("faculty/glass.js", body)

    def test_other_floor_roles_do_not(self):
        for role, name, path in ((Role.CHECKER, "glass_chk", "/checker/floor"),
                                 (Role.GUARD, "glass_grd", "/guard/monitor")):
            with self.subTest(role=role):
                self.login_as(role, name)
                body = self.client.get(path, follow=True).content.decode()
                self.assertNotIn("ft-glass", _html_tag(body))
                self.assertNotIn("glass.css", body)
                self.assertNotIn("glass.js", body)
                self.client.logout()

    def test_scan_button_sits_beside_the_tab_bar(self):
        self.login_as(Role.FACULTY, "glass_scan")
        for path in TAB_PAGES:
            with self.subTest(path=path):
                nav = _faculty_nav(self.client.get(path).content.decode())
                self.assertRegex(nav, r'<a href="/faculty/scan" class="ft-scanbtn" aria-label="Scan room QR">')

    def test_short_labels_keep_full_names_for_screen_readers(self):
        self.login_as(Role.FACULTY, "glass_short")
        nav = _faculty_nav(self.client.get("/faculty/home").content.decode())
        shorts = re.findall(r'<span class="ft-tab__short">([^<]+)</span>', nav)
        self.assertEqual(shorts, ["Home", "Schedule", "Online", "Attendance", "Requests"])
        self.assertIn('aria-label="My attendance"', nav)
        self.assertIn('aria-label="Online classes"', nav)


class GlassContractTests(SimpleTestCase):
    def test_every_rule_is_scoped_to_faculty(self):
        src = _css()
        selectors = [s.strip() for s in re.findall(r"([^{};]+)\{", src)]
        self.assertTrue(selectors, "glass.css has no rules")
        for sel in selectors:
            if sel.startswith("@") or re.fullmatch(r"(from|to|[\d.]+%)(\s*,\s*(from|to|[\d.]+%))*", sel):
                continue
            for part in sel.split(","):
                self.assertTrue(part.strip().startswith("html.ft-glass"),
                                f"unscoped selector in glass.css: {part.strip()!r}")

    def test_motion_and_transparency_fallbacks(self):
        src = _css()
        self.assertIn("@view-transition", src)
        rm = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}", src, re.S)
        self.assertIsNotNone(rm, "no reduced-motion block")
        self.assertIn("navigation: none", rm.group(1))
        self.assertIn("animation: none", rm.group(1))
        self.assertIn("@media (prefers-reduced-transparency: reduce)", src)
        self.assertRegex(src, r"@supports not \(\(backdrop-filter:[^;{]*?\)\)\s*or\s*\(-webkit-backdrop-filter:")

    def test_glass_text_clears_aa(self):
        white = (1.0, 1.0, 1.0)
        hero = _composite(_hsl_rgb("--primary"), float(_token("--glass-hero-alpha")), white)
        on_hero = _hsl_rgb("--primary-foreground")
        self.assertGreaterEqual(_ratio(on_hero, hero), 4.5)
        self.assertGreaterEqual(_ratio(_composite(on_hero, 0.78, hero), hero), 4.5)

        # Tab labels on the bar while it floats over the navy card.
        bar = _composite(_hsl_rgb("--glass-fill"), float(_token("--glass-strong-alpha")), hero)
        self.assertGreaterEqual(_ratio(_hsl_rgb("--foreground"), bar), 4.5)

        backdrop = _composite(_hsl_rgb("--glow-navy"), 0.35, _hsl_rgb("--glass-base"))
        surface = _composite(_hsl_rgb("--glass-fill"), float(_token("--glass-strong-alpha")), backdrop)
        for text in ("--foreground", "--muted-foreground"):
            with self.subTest(text=text):
                self.assertGreaterEqual(_ratio(_hsl_rgb(text), surface), 4.5)

    def test_glass_tokens_are_defined(self):
        for name in ("--glass-fill", "--glass-edge", "--glass-alpha", "--glass-strong-alpha",
                     "--glass-hero-alpha", "--glass-blur", "--glow-navy", "--glow-red",
                     "--glow-blue", "--font-ios", "--glass-base"):
            with self.subTest(name=name):
                _token(name)
        self.assertTrue((ROOT / "static/faculty/glass.js").exists())


def _rule(src, selector):
    """Body of the first top-level rule whose selector list contains `selector`."""
    for m in re.finditer(r"([^{};]+)\{([^{}]*)\}", src):
        if selector in [p.strip() for p in m.group(1).split(",")]:
            return m.group(2)
    return ""


class GlassLookTests(SimpleTestCase):
    def test_backdrop_uses_the_glow_tokens(self):
        body = _rule(_css(), "html.ft-glass .ft-app")
        for glow in ("--glow-navy", "--glow-red", "--glow-blue"):
            self.assertIn(glow, body)
        self.assertIn("radial-gradient", body)

    def test_floating_tab_bar_and_scan_button(self):
        src = _css()
        bar = _rule(src, "html.ft-glass .ft-tabbar")
        self.assertIn("position: fixed", bar)
        row = _rule(src, "html.ft-glass .ft-tabbar__row")
        self.assertIn("border-radius: 999px", row)
        self.assertIn("backdrop-filter", row)
        # The bar floats over the navy check-in card too: its glass must stay
        # near-opaque so the muted labels keep AA over navy (contrast itself is
        # pinned in GlassTabStateTests).
        self.assertIn("var(--glass-strong-alpha)", row)
        btn = _rule(src, "html.ft-glass .ft-scanbtn")
        self.assertIn("border-radius: 50%", btn)
        self.assertRegex(btn, r"width:\s*(var\(--touch\)|calc\([^)]*var\(--touch\))")
        self.assertIn("display: none", _rule(src, "html.ft-glass .ft-tab__label"))
        self.assertIn("display: block", _rule(src, "html.ft-glass .ft-tab__short"))

    def test_hero_is_navy_glass(self):
        hero = _rule(_css(), "html.ft-glass .ft-hero")
        self.assertIn("--primary", hero)
        self.assertIn("--glass-hero-alpha", hero)
        self.assertIn("backdrop-filter", hero)

    def test_pages_clear_the_floating_bar(self):
        body = _rule(_css(), "html.ft-glass body:has(.ft-tabbar) .ft-page")
        self.assertIn("calc(", body)
        self.assertIn("env(safe-area-inset-bottom", body)

    def test_font_is_the_system_stack(self):
        self.assertIn("font-family: var(--font-ios)", _rule(_css(), "html.ft-glass body"))


class GlassMotionTests(SimpleTestCase):
    def test_active_tab_morphs_between_pages(self):
        src = _css()
        self.assertIn("view-transition-name: ft-active-tab", _rule(src, "html.ft-glass .ft-tab.is-active"))
        group = _rule(src, "html.ft-glass::view-transition-group(ft-active-tab)")
        self.assertRegex(group, r"animation-timing-function:\s*(var\(--glass-ease\)|cubic-bezier)")

    def test_scroll_states_are_driven_by_one_listener(self):
        js = _read("static/faculty/glass.js")
        for needle in ("passive: true", "requestAnimationFrame", "is-scrolled", "is-compact"):
            self.assertIn(needle, js)
        self.assertNotIn("setInterval", js)
        self.assertEqual(js.count("addEventListener(\"scroll\""), 1)

    def test_request_form_rises_like_a_sheet(self):
        src = _css()
        body = _rule(src, "html.ft-glass .ft-sheet-page")
        m = re.search(r"animation:\s*([\w-]+)", body)
        self.assertIsNotNone(m, "no animation on .ft-sheet-page")
        frames = re.search(rf"@keyframes\s+{m.group(1)}\s*\{{\s*from\s*\{{([^}}]*)\}}", src)
        self.assertIsNotNone(frames, "keyframes missing")
        self.assertIn("translateY(", frames.group(1))
        self.assertIn('class="ft-app ft-sheet-page"', _read("templates/faculty/modality_new.html"))


def _media_rules(src, width):
    """Selector -> joined bodies of the rules inside every @media (min-width: <width>) block."""
    out = {}
    for m in re.finditer(r"@media\s*\(min-width:\s*" + re.escape(width) + r"\)\s*\{", src):
        depth, i = 1, m.end()
        while depth and i < len(src):
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        for r in re.finditer(r"([^{};]+)\{([^{}]*)\}", src[m.end():i - 1]):
            for sel in r.group(1).split(","):
                out[sel.strip()] = out.get(sel.strip(), "") + r.group(2)
    return out


class GlassResponsiveTests(SimpleTestCase):
    def test_bar_floats_top_centre_from_48rem(self):
        rules = _media_rules(_css(), "48rem")
        bar = rules.get("html.ft-glass .ft-tabbar", "")
        self.assertRegex(bar, r"top:\s*calc\(")
        self.assertIn("bottom: auto", bar)
        self.assertIn("left: 50%", bar)
        self.assertIn("--glass-bar-h", rules.get("html.ft-glass .ft-top", ""))

    def test_side_rail_is_overridden_for_faculty(self):
        """faculty.css turns the bar into a side rail at 64rem; every property it
        sets there must be overridden by a glass rule that applies at 64rem."""
        src = _css()
        glass = {}
        for w in ("48rem", "64rem"):
            for sel, body in _media_rules(src, w).items():
                glass[sel] = glass.get(sel, "") + body
        rail = _media_rules(re.sub(r"/\*.*?\*/", "", _read("static/faculty/faculty.css"), flags=re.S), "64rem")
        for sel in (".ft-tabbar", ".ft-tabbar__row", ".ft-tabbar__role", ".ft-tab",
                    "body:has(.ft-tabbar) .ft-page"):
            mine = glass.get("html.ft-glass " + sel, "")
            for prop in re.findall(r"(?:^|;|\s)([a-z-]+)\s*:", rail.get(sel, "")):
                with self.subTest(selector=sel, prop=prop):
                    self.assertRegex(mine, rf"(^|;|\s){re.escape(prop)}\s*:",
                                     f"{sel} {prop} from the faculty.css side rail is not overridden")

    def test_home_two_columns_from_64rem(self):
        self.assertIn("grid-template-columns", _media_rules(_css(), "64rem").get("html.ft-glass .ft-home-grid", ""))


FACULTY_ROUTES = ["/faculty/home", "/faculty/schedule", "/faculty/online", "/faculty/history",
                  "/faculty/modality/mine", "/faculty/modality/new", "/faculty/scan",
                  "/faculty/profile", "/notifications"]

# Blocks that carry no surface of their own: layout wrappers and plain text.
# Everything else a Faculty template uses must have a glass rule.
STRUCTURAL = {
    "ft-page", "ft-list", "ft-inline", "ft-form", "ft-field", "ft-dot", "ft-num",
    "ft-label", "ft-help", "ft-legend", "ft-history-cards", "ft-divide",
    # wrappers whose visible surface is an __element styled in glass.css
    "ft-history-filter", "ft-otp", "ft-keypad", "ft-pick", "ft-steps", "ft-photo",
    "ft-viewfinder", "ft-scan", "ft-step",
    # layout or text only
    "ft-navrow", "ft-push-settings", "ft-or-ink", "ft-subrow", "ft-setting-row",
}


def _faculty_blocks():
    """Base component classes (no __element, no --modifier) used on Faculty screens."""
    paths = list((ROOT / "templates/faculty").glob("*.html"))
    paths += [ROOT / "templates/_floor_top.html"]
    paths += [p for p in (ROOT / "templates/notifications").glob("*.html")]
    found = set()
    for p in paths:
        for attr in re.findall(r'class="([^"]*)"', p.read_text("utf-8")):
            for cls in re.findall(r"\bft-[a-z0-9-]+", attr):
                if "__" not in cls and "--" not in cls:
                    found.add(cls)
    return found


class GlassScreensTests(_Login, TestCase):
    def test_every_faculty_screen_is_in_the_glass_shell(self):
        self.login_as(Role.FACULTY, "glass_screens")
        for path in FACULTY_ROUTES:
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                body = r.content.decode()
                self.assertIn("ft-glass", _html_tag(body))
                self.assertIn("faculty/glass.css", body)
                self.assertEqual(len(re.findall(r"<header\b", body)), 1)

    def test_screens_have_glass_rules(self):
        src = _css()
        missing = sorted(b for b in _faculty_blocks() - STRUCTURAL
                         if not re.search(rf"html\.ft-glass[^{{]*\.{re.escape(b)}(?![\w-])", src))
        self.assertEqual(missing, [], "Faculty components with no glass rule")


# ---------------------------------------------------------------------------
# Final-review fixes (one class per finding; each failed before its fix)
# ---------------------------------------------------------------------------

def _all_rules(src):
    """Flat list of (selector_parts, body, enclosing_at_rules) for every rule."""
    out = []

    def walk(text, ctx):
        i = 0
        while i < len(text):
            j = text.find("{", i)
            if j < 0:
                return
            head = text[i:j].strip().split(";")[-1].strip()
            depth, k = 1, j + 1
            while depth and k < len(text):
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            inner = text[j + 1:k - 1]
            if head.startswith("@"):
                walk(inner, ctx + (head,))
            elif head:
                out.append(([p.strip() for p in head.split(",")], inner, ctx))
            i = k
    walk(src, ())
    return out


def _props(body):
    return {m.group(1) for m in re.finditer(r"(?:^|;|\s)([a-z-]+)\s*:", body)}


FLOATING = {  # the only surfaces that may blur what is behind them
    "html.ft-glass .ft-top.is-scrolled", "html.ft-glass .ft-top #notif-bell-toggle",
    "html.ft-glass .ft-chip", "html.ft-glass .ft-hero", "html.ft-glass .ft-tabbar__row",
    "html.ft-glass .ft-scanbtn", "html.ft-glass .ft-appbar",
}


class GlassStateRuleTests(SimpleTestCase):
    """Final review #1: the glass base rules (0,2,1) outrank faculty.css state
    rules (0,2,0), so any property glass sets on a class must be set again for
    that class's :focus / :focus-visible / :hover states, or the state is lost."""

    STATES = ("focus-visible", "focus", "hover")

    def test_states_survive_the_glass_restyle(self):
        fac = _all_rules(re.sub(r"/\*.*?\*/", "", _read("static/faculty/faculty.css"), flags=re.S))
        glass = _all_rules(_css())
        base = {}
        for sels, body, ctx in glass:
            if not ctx:
                for s in sels:
                    base.setdefault(s, set()).update(_props(body))
        glass_sel = {s for sels, _, _ in glass for s in sels}
        for sels, body, ctx in fac:
            if ctx:
                continue
            for s in sels:
                m = re.fullmatch(r"\.(ft-[\w-]+)(:(?:" + "|".join(self.STATES) + r')|\[aria-invalid="true"\]|\.is-[\w-]+)', s)
                if not m:
                    continue
                cls, state = m.groups()
                clash = _props(body) & base.get(f"html.ft-glass .{cls}", set()) - {"outline"}
                if clash:
                    with self.subTest(selector=s, props=sorted(clash)):
                        self.assertTrue(
                            any(g.startswith("html.ft-glass") and f".{cls}{state}" in g for g in glass_sel),
                            f"glass restyles {sorted(clash)} on .{cls} but has no .{cls}{state} rule")

    def test_check_in_card_controls_stay_inside_the_card(self):
        """The hero's white-on-navy segment styles must not reach the light
        segmented control on the request form (white text on a pale sheet)."""
        for sels, body, ctx in _all_rules(_css()):
            for sel in sels:
                if re.search(r"\.ft-seg(?![\w-]*label)", sel):
                    with self.subTest(selector=sel):
                        self.assertIn(".ft-hero ", sel)

    def test_live_status_keeps_its_green(self):
        body = _rule(_css(), "html.ft-glass .ft-hero__status.is-live")
        self.assertIn("--success", body)


class GlassCompactTests(SimpleTestCase):
    """Final review #2: the shrunk bar must not survive a widen past 48rem."""

    def test_compact_rules_only_apply_on_phones(self):
        for sels, body, ctx in _all_rules(_css()):
            if any(".is-compact" in s for s in sels):
                with self.subTest(selectors=sels):
                    self.assertIn("@media (max-width: 767.98px)", ctx)

    def test_script_resyncs_when_the_width_crosses_48rem(self):
        js = _read("static/faculty/glass.js")
        self.assertIn('matchMedia("(max-width: 767.98px)")', js)
        self.assertRegex(js, r'phone\.addEventListener\("change"')


class GlassTabStateTests(SimpleTestCase):
    """Final review #3: the current tab must stand out, not by a 1.06:1 tint."""

    def test_inactive_labels_are_muted_and_readable_on_the_bar(self):
        self.assertIn("color: hsl(var(--muted-foreground))", _rule(_css(), "html.ft-glass .ft-tab"))
        white = (1.0, 1.0, 1.0)
        hero = _composite(_hsl_rgb("--primary"), float(_token("--glass-hero-alpha")), white)
        for name, behind in (("over the navy card", hero), ("over the page", _hsl_rgb("--glass-base"))):
            bar = _composite(_hsl_rgb("--glass-fill"), float(_token("--glass-strong-alpha")), behind)
            with self.subTest(where=name):
                self.assertGreaterEqual(_ratio(_hsl_rgb("--muted-foreground"), bar), 4.5)

    def test_active_tab_is_a_solid_navy_capsule(self):
        body = _rule(_css(), "html.ft-glass .ft-tab.is-active")
        self.assertIn("background: hsl(var(--primary))", body)
        self.assertIn("color: hsl(var(--primary-foreground))", body)
        # the capsule against the bar it sits on (non-text contrast, 3:1)
        bar = _composite(_hsl_rgb("--glass-fill"), float(_token("--glass-strong-alpha")), _hsl_rgb("--glass-base"))
        self.assertGreaterEqual(_ratio(_hsl_rgb("--primary"), bar), 3.0)


class GlassGlowContrastTests(SimpleTestCase):
    """Final review #4: muted text can land straight on a glow."""

    GLOWS = (("--glow-navy", "--glow-navy-alpha"), ("--glow-red", "--glow-red-alpha"),
             ("--glow-blue", "--glow-blue-alpha"))

    def test_muted_text_clears_aa_on_every_glow_peak(self):
        base = _hsl_rgb("--glass-base")
        for glow, alpha in self.GLOWS:
            with self.subTest(glow=glow):
                behind = _composite(_hsl_rgb(glow), float(_token(alpha)), base)
                self.assertGreaterEqual(_ratio(_hsl_rgb("--muted-foreground"), behind), 4.5)

    def test_backdrop_reads_the_alpha_tokens(self):
        body = _rule(_css(), "html.ft-glass .ft-app")
        self.assertNotRegex(body, r"hsl\(var\(--glow-[a-z]+\)\s*/\s*[\d.]+\)", "literal glow alpha")
        for _, alpha in self.GLOWS:
            self.assertIn(f"var({alpha})", body)


class GlassBlurBudgetTests(SimpleTestCase):
    """Final review #5: blur only on floating chrome, never on dense lists."""

    def test_only_floating_surfaces_blur(self):
        for sels, body, ctx in _all_rules(_css()):
            m = re.search(r"(?<!-)backdrop-filter:\s*([^;]+)", body)
            if not m or m.group(1).strip() == "none":
                continue
            for s in sels:
                with self.subTest(selector=s):
                    self.assertIn(s, FLOATING)


class GlassSmallPhoneTests(SimpleTestCase):
    """Final review #6: the plan wants five labelled tabs at 360px."""

    def test_narrow_bar_tightens_instead_of_hiding_labels(self):
        for sels, body, ctx in _all_rules(_css()):
            if any(c.startswith("@container") for c in ctx) and any("ft-tab__short" in s for s in sels):
                with self.subTest(selectors=sels):
                    self.assertNotIn("display: none", body)


class GlassLargeTitleTests(SimpleTestCase):
    """Final review #7 (spec goal 4): the large title moves into the top bar."""

    def test_script_mirrors_the_title_into_the_bar(self):
        js = _read("static/faculty/glass.js")
        for needle in ("IntersectionObserver", "is-titled", "ft-top__title", 'aria-hidden'):
            self.assertIn(needle, js)

    def test_bar_title_fades_in_when_the_large_title_leaves(self):
        src = _css()
        self.assertIn("opacity: 0", _rule(src, "html.ft-glass .ft-top__title"))
        self.assertIn("opacity: 1", _rule(src, "html.ft-glass .ft-top.is-titled .ft-top__title"))
