"""Design-system contract tests for the unified responsive UI plan.

One class per plan task. These read the shipped CSS and templates, so a later
edit that drifts from the shadcn-in-MMCM contract fails here first.
"""
import colorsys
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from accounts.models import Role

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text("utf-8")


def _theme_block():
    src = _read("static/css/tokens.css")
    m = re.search(r"html\.uk-theme-neutral\s*\{(.*?)\}", src, re.S)
    return m.group(1) if m else ""


def _role(name):
    m = re.search(rf"{re.escape(name)}\s*:\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\s*;", _theme_block())
    if not m:
        raise AssertionError(f"{name} is not set as an HSL triplet in tokens.css")
    return tuple(float(v) for v in m.groups())


def _luminance(hsl):
    h, s, l = hsl
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg, bg):
    a, b = sorted((_luminance(_role(fg)), _luminance(_role(bg))), reverse=True)
    return (a + 0.05) / (b + 0.05)


class TokenContractTests(SimpleTestCase):
    root = ROOT
    CSS = ["static/css/tokens.css", "static/css/app.css", "static/css/ui.css",
           "static/css/console.css", "static/css/board.css",
           "static/css/timetable.css", "static/faculty/faculty.css"]
    LADDER = {"640px", "768px", "1024px", "1280px", "639.98px", "767.98px",
              "1023.98px", "1279.98px", "40rem", "48rem", "64rem", "80rem"}

    def test_every_media_query_uses_the_breakpoint_ladder(self):
        for rel in self.CSS:
            p = self.root / rel
            if not p.exists():
                continue
            for w in re.findall(r"@media[^{]*?(?:min|max)-width:\s*([\d.]+(?:px|rem))", p.read_text("utf-8")):
                self.assertIn(w, self.LADDER, f"{rel} uses off-ladder breakpoint {w}")

    ROLES = {  # exact values from the plan's "shadcn fidelity" table
        "--primary": "215 100% 13%", "--destructive": "357 84% 52%",
        "--ring": "215 90% 25%", "--sidebar": "220 33% 98%",
        "--sidebar-accent": "220 40% 94%", "--sidebar-primary": "215 100% 13%",
        "--radius": "0.625rem",
    }

    def test_tokens_set_every_shadcn_role_with_mmcm_values(self):
        block = _theme_block()
        for name in ("--background", "--foreground", "--card", "--card-foreground",
                     "--popover", "--popover-foreground", "--primary-foreground",
                     "--secondary", "--secondary-foreground", "--muted", "--muted-foreground",
                     "--accent", "--accent-foreground", "--destructive-foreground",
                     "--border", "--input", "--chart-1", "--chart-5",
                     "--sidebar-foreground", "--sidebar-primary-foreground",
                     "--sidebar-accent-foreground", "--sidebar-border", "--sidebar-ring",
                     "--success", "--warning", "--info", "--radius-sm", "--radius-xl",
                     "--uk-global-radius"):
            self.assertRegex(block, rf"{re.escape(name)}\s*:", name)
        for name, value in self.ROLES.items():
            self.assertRegex(block, rf"{re.escape(name)}\s*:\s*{re.escape(value)}\s*;")

    def test_tokens_define_font_and_layout(self):
        src = _read("static/css/tokens.css")
        for name in ("--font-sans", "--tabbar-h", "--content-max", "--touch"):
            self.assertIn(name + ":", src)
        self.assertIn("@font-face", src)
        self.assertIn("Geist-Variable.woff2", src)
        self.assertTrue((self.root / "static/vendor/geist/Geist-Variable.woff2").exists())

    def test_muted_foreground_clears_aa_on_white_and_muted(self):
        self.assertGreaterEqual(contrast("--muted-foreground", "--background"), 4.5)
        self.assertGreaterEqual(contrast("--muted-foreground", "--muted"), 4.5)
        self.assertGreaterEqual(contrast("--primary-foreground", "--primary"), 4.5)
        self.assertGreaterEqual(contrast("--sidebar-foreground", "--sidebar"), 4.5)
        self.assertGreaterEqual(contrast("--sidebar-accent-foreground", "--sidebar-accent"), 4.5)

    def test_body_uses_the_shared_font(self):
        src = _read("static/css/tokens.css")
        self.assertRegex(src, r"body\s*\{[^}]*font-family:\s*var\(--font-sans\)")


class ComponentSheetTests(SimpleTestCase):
    root = ROOT

    def test_ui_sheet_defines_the_component_contract(self):
        src = _read("static/css/ui.css")
        for sel in (".ui-pagehead", ".ui-stats", ".ui-stat__value", ".ui-filterbar",
                    ".ui-field__error", ".ui-empty", ".ui-steps", ".ui-sidebar",
                    ".ui-sheet", ".ui-brand", ".ui-acct", ".uk-badge-success",
                    ".uk-badge-warning", ".uk-badge-info", "--uk-btn-height"):
            self.assertIn(sel, src)

    RAW_COLOUR_FILES = ["static/css/ui.css", "static/css/app.css", "static/css/console.css",
                        "static/faculty/faculty.css", "static/css/board.css"]

    def test_no_raw_colours_outside_tokens(self):
        for rel in self.RAW_COLOUR_FILES:
            src = re.sub(r"/\*.*?\*/", "", _read(rel), flags=re.S)
            m = re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", src)
            self.assertIsNone(m, f"{rel}: raw colour {m and src[max(0, m.start() - 40):m.end() + 20]!r}")

    def test_stack_tables_label_cells_from_data_label(self):
        src = _read("static/css/app.css")
        self.assertIn("content: attr(data-label)", src)
        self.assertIn(".tbl--stack", src)

    def test_base_loads_ui_between_app_and_faculty(self):
        src = _read("templates/base.html")
        self.assertLess(src.index("css/app.css"), src.index("css/ui.css"))
        self.assertLess(src.index("css/ui.css"), src.index("faculty/faculty.css"))

    def test_ui_sheet_has_no_side_stripes_or_franken_token_names(self):
        src = _read("static/css/ui.css")
        self.assertNotRegex(src, r"border-left:\s*[3-9]px")
        self.assertNotRegex(src, r"--(muted|border|primary|background)\s*:")


def _root_count(body, cls):
    """Count elements whose class attribute STARTS with exactly `cls` (root only)."""
    return len(re.findall(rf'class="{re.escape(cls)}(?:\s[^"]*)?"', body))


class SharedChromeTests(TestCase):
    PAGES = [(Role.FACULTY, "/faculty/home"), (Role.CHECKER, "/checker/floor"),
             (Role.GUARD, "/guard/monitor"), (Role.IFO_ADMIN, "/ifo/rooms"),
             (Role.DEAN, "/dean/dashboard")]

    def test_every_shell_renders_one_brand_and_one_account_menu(self):
        User = get_user_model()
        for role, path in self.PAGES:
            with self.subTest(role=role):
                u = User.objects.create(username=f"chrome_{role}", role=role)
                self.client.force_login(u)
                body = self.client.get(path, follow=True).content.decode()
                self.assertEqual(body.count('class="ui-brand"'), 1)
                self.assertEqual(_root_count(body, "ui-acct"), 1)
                self.assertIn("brand/mmcm-crest.png", body)
                self.client.logout()


class ConsoleEverywhereTests(TestCase):
    DESK = [(Role.IFO_ADMIN, ["/notifications", "/notifications/settings", "/profile"]),
            (Role.DEAN, ["/notifications", "/profile"]),
            (Role.HR_ADMIN, ["/hr/attendance", "/notifications", "/profile"]),
            (Role.SYSTEM_ADMIN, ["/sys/jobs", "/notifications", "/profile"])]

    def test_desk_pages_render_inside_the_console_with_one_header(self):
        User = get_user_model()
        for role, paths in self.DESK:
            u = User.objects.create(username=f"cns_{role}", role=role)
            self.client.force_login(u)
            for path in paths:
                with self.subTest(role=role, path=path):
                    body = self.client.get(path, follow=True).content.decode()
                    self.assertIn('class="cns"', body)
                    self.assertIn('<header class="cns__bar"', body)
                    self.assertEqual(body.count("<header"), 1)
                    self.assertNotIn("uk-label uk-label-secondary", body)
            self.client.logout()

    def test_role_console_maps_each_role_once(self):
        from web.context import role_console
        rf = RequestFactory()
        cases = {Role.IFO_ADMIN: "ifo/_console.html", Role.DEAN: "dean/_console.html",
                 Role.HR_ADMIN: "hr/_console.html", Role.SYSTEM_ADMIN: "sys/_console.html",
                 Role.FACULTY: None, Role.CHECKER: None, Role.GUARD: None}
        for role, expected in cases.items():
            req = rf.get("/")
            req.user = get_user_model()(username=f"m_{role}", role=role)
            self.assertEqual(role_console(req)["console_template"], expected)

    def test_active_nav_item_marks_the_current_desk_page(self):
        u = get_user_model().objects.create(username="cns_hr_nav", role=Role.HR_ADMIN)
        self.client.force_login(u)
        body = self.client.get("/hr/attendance").content.decode()
        self.assertIn('class="cns__link is-active"', body)


class ConsoleShellTests(SimpleTestCase):
    root = ROOT

    def test_console_collapses_at_lg_and_hides_chrome_in_print(self):
        css = _read("static/css/console.css")
        self.assertIn("@media (max-width: 1023.98px)", css)
        self.assertRegex(css, r"@media print\s*\{[^@]*\.cns__side[^}]*display:\s*none")

    def test_drawer_script_traps_focus_and_locks_scroll(self):
        html = _read("templates/_console.html")
        self.assertIn("inert", html)          # main region inert while drawer open
        self.assertIn("overflow", html)       # body scroll lock toggled
        # The sidebar is only a modal dialog while it is the open drawer, so the
        # script sets these attributes; a desktop sidebar must not be modal.
        self.assertIn('"aria-modal"', html)
        self.assertIn('"dialog"', html)
        self.assertIn('key === "Tab"', html)  # focus stays inside the drawer

    def test_sidebar_follows_the_shadcn_light_sidebar(self):
        css = _read("static/css/console.css")
        side = re.search(r"\.cns__side\s*\{([^}]*)\}", css).group(1)
        self.assertIn("hsl(var(--sidebar))", side)
        active = re.search(r"\.cns__link\.is-active\s*\{([^}]*)\}", css).group(1)
        self.assertIn("hsl(var(--sidebar-accent))", active)
        self.assertNotIn("--primary)", active)

    def test_console_has_one_main_landmark(self):
        html = _read("templates/_console.html")
        self.assertNotIn("<main", html)  # base.html already provides <main id="main">


class FloorShellTests(SimpleTestCase):
    root = ROOT

    def test_pages_with_a_tab_bar_clear_it(self):
        css = _read("static/faculty/faculty.css")
        self.assertRegex(css, r"body:has\(\.ft-tabbar\) \.ft-page\s*\{[^}]*padding-bottom:\s*calc\([^)]*var\(--tabbar-h\)")

    def test_floor_radius_reads_the_shared_ladder(self):
        css = _read("static/faculty/faculty.css")
        self.assertNotRegex(css, r"border-radius:\s*(26|18|14)px")

    def test_home_has_a_two_column_desktop_layout(self):
        css = _read("static/faculty/faculty.css")
        self.assertIn(".ft-home-grid", css)
        html = _read("templates/faculty/home.html")
        self.assertIn('class="ft-home-grid"', html)

    def test_floor_lists_become_grids_on_wide_screens(self):
        css = _read("static/faculty/faculty.css")
        self.assertIn(".ft-board-grid", css)
        for tpl in ("templates/checker/floor.html", "templates/guard/monitor.html"):
            self.assertIn("ft-board-grid", _read(tpl), tpl)


class FloorShadcnTests(SimpleTestCase):
    root = ROOT

    def css(self):
        return _read("static/faculty/faculty.css")

    def test_floor_reads_only_shadcn_roles(self):
        src = re.sub(r"/\*.*?\*/", "", self.css(), flags=re.S)
        self.assertNotRegex(src, r"var\(--(nv|ft)-")   # legacy floor tokens gone
        self.assertNotRegex(src, r"var\(--(ink|body|line|green|amber|red|purple|surface|panel-2|on-nv|r-|shadow-card|shadow-nav)")
        self.assertIn("hsl(var(--primary))", src)

    def test_legacy_alias_block_is_deleted(self):
        tokens = _read("static/css/tokens.css")
        self.assertNotIn("--nv-hero", tokens)
        for rel in ("static/css/app.css", "static/css/board.css", "static/css/console.css",
                    "static/css/ui.css", "static/css/timetable.css"):
            src = re.sub(r"/\*.*?\*/", "", _read(rel), flags=re.S)
            self.assertNotRegex(src, r"var\(--(nv-|ink|body|ft-muted|line|green|amber|red|red-|purple|navy|info-bg|info-ink|surface|panel-2|on-nv|r-hero|r-card|r-btn|r-pill|shadow-card|shadow-nav|neutral-wash|info-wash)", rel)

    def test_floor_primary_actions_meet_touch_size(self):
        src = self.css()
        self.assertRegex(src, r"\.ft-btn-navy[^{]*\{[^}]*min-height:\s*var\(--touch\)")
        self.assertRegex(src, r"\.ft-control[^{]*\{[^}]*min-height:\s*var\(--touch\)")

    def test_pinned_strings_survive(self):
        src = self.css()
        for s in (".ft-tab__label { display: none; }", "@media (min-width: 48rem)",
                  "@media (min-width: 64rem)", "body:has(.ft-tabbar) .ft-page",
                  "max-width: 72rem"):
            self.assertIn(s, src)
        self.assertRegex(src, r"\.ft-banner\.hidden\s*\{\s*display:\s*none;?\s*\}")


DESK_ROUTES = [
    (Role.IFO_ADMIN, p) for p in (
        "/ifo/rooms", "/ifo/import", "/ifo/bookings", "/ifo/conflicts", "/ifo/assignments",
        "/ifo/terms", "/ifo/terms/create", "/ifo/suspensions", "/ifo/breaks", "/ifo/corrections",
        "/ifo/dashboard", "/ifo/utilization", "/ifo/reports", "/ifo/rooms/new", "/ifo/schedules/new",
        "/ifo/buildings", "/ifo/buildings/create", "/notifications", "/notifications/settings", "/profile")
] + [
    (Role.DEAN, p) for p in ("/dean/dashboard", "/dean/requests", "/dean/faculty", "/dean/reports",
                             "/notifications", "/profile")
] + [
    (Role.HR_ADMIN, p) for p in ("/hr/attendance", "/notifications", "/profile")
] + [
    (Role.SYSTEM_ADMIN, p) for p in ("/", "/sys/jobs", "/notifications", "/profile")
]


class DeskDataTests(TestCase):
    def _login(self, role, name):
        from accounts.models import Department
        dept = Department.objects.first()
        u = get_user_model().objects.create(username=name, role=role, department=dept)
        self.client.force_login(u)
        return u

    def test_stacked_rows_carry_labels(self):
        from scheduling.test_support import make_reporting_fixture
        make_reporting_fixture()
        self._login(Role.HR_ADMIN, "dd_hr")
        body = self.client.get("/hr/attendance").content.decode()
        self.assertIn('class="tbl tbl--stack"', body)
        for label in ("Faculty", "Course", "Date", "Scheduled", "Actual", "Status"):
            self.assertIn(f'data-label="{label}"', body)

    def test_filters_use_the_shared_filterbar(self):
        from scheduling.test_support import make_reporting_fixture
        make_reporting_fixture()
        for i, (role, path) in enumerate(((Role.HR_ADMIN, "/hr/attendance"),
                                          (Role.IFO_ADMIN, "/ifo/dashboard"),
                                          (Role.DEAN, "/dean/reports"))):
            with self.subTest(path=path):
                self._login(role, f"dd_f{i}")
                body = self.client.get(path).content.decode()
                self.assertIn('class="ui-filterbar"', body)
                self.client.logout()

    def test_every_desk_page_uses_shadcn_page_anatomy(self):
        from scheduling.test_support import make_reporting_fixture
        make_reporting_fixture()
        for i, (role, path) in enumerate(DESK_ROUTES):
            with self.subTest(role=role, path=path):
                self._login(role, f"dd_a{i}")
                resp = self.client.get(path, follow=True)
                self.assertEqual(resp.status_code, 200, path)
                body = resp.content.decode()
                self.assertIn('class="ui-pagehead', body, path)
                self.assertNotIn('<h1 class="ui-pagehead__title"></h1>', body, path)
                self.assertNotRegex(body, r'class="[^"]*\bft-', path)   # no floor vocabulary on desk
                self.client.logout()

    def test_ifo_kpis_use_equal_height_stats(self):
        from scheduling.test_support import make_reporting_fixture
        make_reporting_fixture()
        self._login(Role.IFO_ADMIN, "dd_kpi")
        body = self.client.get("/ifo/dashboard").content.decode()
        self.assertIn('class="ui-stats"', body)
        self.assertGreaterEqual(len(re.findall(r'class="ui-stat(?: [^"]*)?"', body)), 4)


class OfflinePageTests(SimpleTestCase):
    root = ROOT

    def test_offline_page_keeps_every_hook(self):
        html = _read("templates/checker/offline.html")
        for hook in ('id="capture"', 'id="payload"', 'id="action"', 'id="note"',
                     'id="status"', 'id="account-label"', 'id="offline-banner"',
                     'id="offline-banner-text"', "checker/offline_queue.js",
                     'value="verified"', 'value="verified_empty"', 'value="flag_not_present"',
                     "data-offline-shell"):
            self.assertIn(hook, html)

    def test_offline_page_uses_brand_tokens_and_touch_sizes(self):
        html = _read("templates/checker/offline.html")
        self.assertIn("#001c43", html)            # MMCM navy, inlined: no stylesheet offline
        self.assertIn("min-height: 44px", html)
        # The crest, via /icon-192.png: the service worker precaches that URL
        # (it serves static/brand/mmcm-crest.png), so it renders offline.
        self.assertIn('src="/icon-192.png"', html)


CODE = re.compile(r"\b(HR|SYS|IFO|DEAN|MOD|GRD|CHK|FAC|NOTIF|CR|RPT)-\d{2}\b|\(D-\d{2}\)|\(A\d{1,2}\)")


class PlainCopyTests(TestCase):
    PAGES = [(Role.HR_ADMIN, "/hr/attendance"), (Role.SYSTEM_ADMIN, "/sys/jobs"),
             (Role.IFO_ADMIN, "/ifo/dashboard"), (Role.IFO_ADMIN, "/ifo/rooms"),
             (Role.IFO_ADMIN, "/ifo/utilization"), (Role.IFO_ADMIN, "/ifo/reports"),
             (Role.IFO_ADMIN, "/ifo/assignments"),
             (Role.DEAN, "/dean/dashboard"), (Role.DEAN, "/dean/requests"),
             (Role.DEAN, "/dean/reports"), (Role.FACULTY, "/faculty/home"),
             (Role.CHECKER, "/checker/floor"), (Role.GUARD, "/guard/monitor")]

    def test_no_requirement_codes_in_rendered_pages(self):
        from accounts.models import Department
        from scheduling.test_support import make_reporting_fixture
        make_reporting_fixture()
        dept = Department.objects.first()
        for i, (role, path) in enumerate(self.PAGES):
            with self.subTest(path=path):
                u = get_user_model().objects.create(username=f"pc_{i}", role=role, department=dept)
                self.client.force_login(u)
                body = self.client.get(path, follow=True).content.decode()
                visible = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
                m = CODE.search(visible)
                self.assertIsNone(m, f"{path}: {m and visible[max(0, m.start() - 60):m.end() + 20]!r}")
                self.client.logout()


class TermStepsTests(TestCase):
    def _term(self, name, status):
        from datetime import date
        from scheduling.models import AcademicTerm
        return AcademicTerm.objects.create(name=name, status=status,
                                           start_date=date(2026, 6, 1), end_date=date(2026, 10, 1))

    def test_draft_without_schedules_points_to_import(self):
        from web.ifo_terms import term_steps
        steps = term_steps(self._term("Draft T", "draft"))
        self.assertEqual([s["key"] for s in steps], ["create", "import", "check", "activate", "close"])
        self.assertEqual([s["state"] for s in steps], ["done", "current", "todo", "todo", "todo"])
        self.assertEqual(steps[1]["href"], "/ifo/import")

    def test_active_term_points_to_close(self):
        from web.ifo_terms import term_steps
        t = self._term("Active T", "active")
        steps = term_steps(t)
        self.assertEqual([s["state"] for s in steps], ["done", "done", "done", "done", "current"])
        self.assertEqual(steps[4]["href"], f"/ifo/terms/{t.pk}/close")

    def test_archived_term_is_all_done(self):
        from web.ifo_terms import term_steps
        self.assertEqual({s["state"] for s in term_steps(self._term("Old T", "archived"))}, {"done"})

    def test_term_detail_renders_the_tracker(self):
        t = self._term("Draft D", "draft")
        u = get_user_model().objects.create(username="ts_ifo", role=Role.IFO_ADMIN)
        self.client.force_login(u)
        body = self.client.get(f"/ifo/terms/{t.pk}").content.decode()
        self.assertIn('class="ui-steps"', body)
        self.assertIn('aria-current="step"', body)
        body = self.client.get("/ifo/terms").content.decode()
        self.assertIn('class="ui-steps"', body)


class AdminBrandTests(TestCase):
    def test_admin_carries_mmcm_branding(self):
        su = get_user_model().objects.create_superuser("adm_brand", "a@b.c", "x")
        self.client.force_login(su)
        body = self.client.get("/admin/").content.decode()
        self.assertIn("mmcm-crest.png", body)
        self.assertIn("--header-bg: #001c43", body)
        self.assertIn("FluxTrack administration", body)


class PaginationTests(TestCase):
    """2026-11-08 (user request "add paginations"): every list that can grow past
    a screen uses the shared 50-row pager (D10). Live boards keep the page in the
    poll URL so a refresh does not jump back to page 1."""

    def test_notifications_page_through_older_rows(self):
        from ops.models import Notification
        u = get_user_model().objects.create(username="pg_ifo", role=Role.IFO_ADMIN)
        for i in range(55):
            Notification.objects.create(user=u, type="system", title=f"Notice {i:02d}", body="b", link="/")
        self.client.force_login(u)
        body = self.client.get("/notifications").content.decode()
        self.assertIn('aria-label="Pagination"', body)
        self.assertIn("Showing <b>1</b>", body)
        body2 = self.client.get("/notifications?page=2").content.decode()
        self.assertIn("Notice 00", body2)       # the oldest rows are reachable now
        self.assertNotIn("Notice 54", body2)

    def test_long_lists_are_wired_to_the_shared_pager(self):
        wiring = {
            "web/guard.py": "paginate(", "web/checker.py": "paginate(", "web/ifo.py": "room_classes_pg",
            "web/dean.py": "paginate(", "web/notifications.py": "paginate(",
        }
        for rel, needle in wiring.items():
            self.assertIn(needle, _read(rel), rel)
        for tpl in ("templates/guard/_monitor_rows.html", "templates/checker/_floor_rows.html",
                    "templates/ifo/room_detail.html", "templates/dean/faculty_list.html",
                    "templates/notifications/_list_body.html"):
            self.assertIn('"_pager.html"', _read(tpl), tpl)

    def test_live_boards_poll_the_page_they_show(self):
        for tpl in ("templates/guard/monitor.html", "templates/checker/floor.html"):
            self.assertIn("request.GET.urlencode", _read(tpl), tpl)


class FinalReviewFixTests(SimpleTestCase):
    """Fixes from the whole-branch review (2026-11-08)."""

    def test_admin_colours_leave_django_dark_mode_alone(self):
        src = _read("templates/admin/base_site.html")
        self.assertNotIn(":root, html[data-theme=\"light\"]", src)
        self.assertIn("prefers-color-scheme: light", src)
        self.assertIn('html:not([data-theme="dark"])', src)

    def test_report_a_problem_requires_a_deliberate_reason(self):
        src = _read("templates/checker/_outcome.html")
        radios = re.findall(r'<input type="radio" name="action"[^>]*>', src)
        self.assertEqual(len(radios), 2)
        for r in radios:
            self.assertNotIn("checked", r)
        self.assertIn("required", radios[0])

    def test_filter_bars_reopen_when_the_screen_widens(self):
        src = _read("templates/base.html")
        block = src[src.index("details.ui-filterbar") - 600:src.index("details.ui-filterbar") + 600]
        self.assertIn("addEventListener", block)

    def test_scorecard_back_link_and_export_do_not_print(self):
        src = _read("templates/reports/scorecard.html")
        self.assertRegex(src, r'class="[^"]*no-print[^"]*"[^>]*>&larr; Back to the report')
        self.assertRegex(src, r'class="uk-btn uk-btn-primary uk-btn-sm no-print" download')
