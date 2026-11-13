# Unified, Responsive FluxTrack UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every role on the shadcn/ui design system, followed fully and tailored to MMCM (navy, red, crest). It must work at phone, tablet and desktop widths and make the hardest multi-step screens easier to follow.

**Architecture:** Keep Franken UI (D11), which is a shadcn port. Set shadcn's full set of colour roles and its radius in `static/css/tokens.css` with MMCM values, tune Franken's shadcn components to the exact shadcn sizes, add the shadcn components Franken lacks in `static/css/ui.css`, and rebuild the floor family's bespoke parts on shadcn anatomy, and keep the two device shells (navy phone shell for floor roles, sidebar console for desk roles), but move every desk page into the console so that the old plain top bar disappears. Then fix layouts page by page, driven by a measured baseline audit.

**Tech Stack:** Django 6 templates, Franken UI 2.1.2 (vendored, no Tailwind build), htmx 2.0.6, plain CSS, Django test runner on MSSQL LocalDB, gstack `/browse` for browser checks.

**Spec:** No separate spec. The user skipped the design questions on 2026-11-08 and asked for a plan first. The direction below is the spec. Lines marked **(my call)** were decided by Claude and are open to veto.

---

## Design direction (the spec)

**What the user asked for (verbatim intent):** map the codebase; make the entire app responsive; polish the UI/UX; retain all the colours and some of the layouts; one design system across all roles; keep the overall Mapúa institutional vibe; make it as visually pleasing as shadcn; redesign the places that are still hard to use, because the app has many processes.

**What the map found (2026-11-08):**
- About 90 page templates across seven roles, in five visual families. Navy phone shell: Faculty, Checker, Guard (`static/faculty/faculty.css`, 1,028 lines). Sidebar console: IFO and Dean (`templates/_console.html`, `static/css/console.css`). Plain Franken top-bar pages: HR attendance, SysAdmin job monitor, the role hub, admin profile, admin notifications, the scorecard. Two-panel login. Standalone pages: room poster, offline capture.
- The families share colours (`tokens.css`) but not radius, type scale, spacing, headers or card style. Radii run 26/18/14px on phone and about 8px on desk.
- There are seven different breakpoints: 23rem, 620px, 640px, 900px, 1023px, 1024px, 48rem and 64rem.
- No font is set, so every OS shows its own system font.
- Visible defects in the 2026-11-08 screenshots:
  - `checker/offline.html` is raw, unstyled HTML.
  - The Checker "session found" card shows two flag forms with two note boxes at once.
  - The IFO dashboard KPI cards have uneven heights, and the occupancy card is crowded with paragraphs.
  - An IFO dashboard faculty row has a blank name (`scheduling/reporting.py:_name` has no username fallback).
  - Requirement codes such as "(HR-01/02/03)", "(SYS-04)" and "(IFO-09)" appear in visible page copy.
  - Floor-role lists run under the bottom tab bar (Guard monitor).
  - SysAdmin's Django admin is stock teal.

**Goals**
1. One system: a page from any role is recognisably the same product. It uses the same brand mark, account menu, type scale, card, table, badge, button, form control, empty state and alert.
2. Responsive everywhere: no horizontal page scroll at 360, 390, 768, 1024 or 1440px wide. Desk tables become stacked rows on phones. Floor screens use the extra width on desktops instead of a stretched phone column.
3. Mapúa feel: navy `#001c43` stays the dominant brand colour, and red `#ec1f28` stays a sparing accent (destructive actions, the crest, one active indicator). The crest appears in every shell.
4. Friendlier processes: one decision at a time on the Checker flag flow, a step tracker on the IFO term lifecycle, a calmer IFO dashboard, and plain-language copy.

**Non-goals**
- No library swap (D11 stands). No React, no Tailwind build step.
- No change to what any screen does. Each form posts the same fields to the same URL, and each rule stays as it is. Layout and labels only ("Ask before product rules").
- The login keeps its two-panel layout. It only picks up the shared font and tokens.
- No dark mode.

**Anti-goals (a failure even if it works):**
- The floor roles lose the navy hero look.
- The app looks like generic SaaS: gradient heroes, identical big-number tile grids, emoji. PRODUCT.md lists these as anti-references.
- The offline capture page breaks, or a scan or flag stops working.
- A tested class name disappears and the old test is edited to match without telling the user.

**User requirement added 2026-11-08: "fully follow shadcn design system but tailored to MMCM".** The section below is binding on every task.

## shadcn fidelity, tailored to MMCM

shadcn/ui (new-york style, current v4 defaults) is the design system. MMCM tailoring happens **only** through token values and the few rules listed under "MMCM tailoring". Component anatomy, sizes, spacing, type and states follow shadcn. Franken UI 2.1.2 is a shadcn port and already defines shadcn's colour roles (`--background`, `--foreground`, `--card(-foreground)`, `--popover(-foreground)`, `--primary(-foreground)`, `--secondary(-foreground)`, `--muted(-foreground)`, `--accent(-foreground)`, `--destructive(-foreground)`, `--border`, `--input`, `--ring`, `--chart-1..5`) as HSL triplets. It does **not** define `--radius` or the `--sidebar-*` roles, so we add those.

**Colour roles (HSL triplets on `html.uk-theme-neutral`; Franken wraps them in `hsl()`):**

| Role | Value | Notes |
|---|---|---|
| `--background` / `--foreground` | `0 0% 100%` / `222 47% 11%` | White page, navy-black ink (`#0f172a` family) instead of shadcn's neutral black |
| `--card`, `--popover` | as background / foreground | |
| `--primary` / `--primary-foreground` | `215 100% 13%` (`#001c43`) / `0 0% 98%` | MMCM navy |
| `--secondary` / `--secondary-foreground` | `220 33% 96%` / `215 100% 13%` | Navy-tinted light grey |
| `--muted` / `--muted-foreground` | `220 33% 96%` / `220 14% 40%` | Muted text ≥ 4.5:1 on white and on muted |
| `--accent` / `--accent-foreground` | `220 40% 94%` / `215 100% 13%` | Hover and selected surfaces |
| `--destructive` / `--destructive-foreground` | `357 84% 52%` (`#ec1f28`) / `0 0% 100%` | MMCM red |
| `--border`, `--input` | `220 20% 90%` | |
| `--ring` | `215 90% 25%` | Navy focus ring, drawn at 50% opacity per shadcn |
| `--chart-1..5` | navy `215 100% 13%`, `215 70% 35%`, `215 55% 55%`, `215 45% 75%`, red `357 84% 52%` | Sequential navy ramp plus red for the exception series |
| `--sidebar` / `--sidebar-foreground` | `220 33% 98%` / `222 47% 11%` | **Light sidebar**, stock shadcn (off-white, a touch of navy tint). The user ruled out a navy sidebar (2026-11-08) |
| `--sidebar-primary` / `--sidebar-primary-foreground` | `215 100% 13%` / `0 0% 98%` | Navy: crest tile and the active item's icon |
| `--sidebar-accent` / `--sidebar-accent-foreground` | `220 40% 94%` / `215 100% 13%` | Active and hover item: light navy tint, navy text |
| `--sidebar-border` / `--sidebar-ring` | `220 20% 90%` / `215 90% 25%` | Same as `--border` / `--ring` |
| Status (MMCM extension; shadcn has none) | `--success 156 78% 27%` `--warning 25 90% 33%` `--info 222 66% 32%`, each with `-foreground` and a `-muted` tint | Attendance states, from the existing green/amber/info hexes |

**Radius:** `--radius: 0.625rem` (10px, the shadcn v4 default). `--radius-sm` = `calc(var(--radius) - 4px)`, `--radius-md` = `- 2px`, `--radius-lg` = `var(--radius)`, `--radius-xl` = `+ 4px`. Franken's `--uk-global-radius` and `--uk-global-radius-s` are set from these, so `uk-*` components match. The floor family's 26/18/14px radii go: hero becomes `--radius-xl` (14px), cards `--radius-xl`, buttons and inputs `--radius-md`.

**Type:** Geist Sans, vendored (OFL licence; shadcn's current default font). Base `text-sm` (0.875rem / 1.25rem) on desk surfaces and `text-base` on floor surfaces. Page title `text-2xl font-semibold tracking-tight`. Card title `leading-none font-semibold`. Card description `text-sm text-muted-foreground`. Tabular numbers for every figure.

**Component anatomy (copy shadcn, not our older bespoke shapes):**
- **Button:** variants default, secondary, outline, ghost, destructive, link. Heights sm 32px, default 36px, lg 40px, icon 36px. `rounded-md`, `text-sm font-medium`, gap 8px, icon 16px. Focus is `ring-[3px] ring-ring/50` plus `border-ring`. Disabled is 50% opacity with no pointer.
- **Input and Select:** 36px tall, `rounded-md`, 1px `--input` border, `shadow-xs`, padding 0 12px. Focus as Button. `aria-invalid` gives a destructive border and ring.
- **Card:** `rounded-xl`, border, `shadow-sm`, `py-6` and `gap-6`. Header, title, description, action, content and footer use `px-6`.
- **Badge:** `rounded-md`, 1px border, padding 2px 8px, `text-xs font-medium`. Variants default, secondary, destructive, outline, plus the MMCM status variants success, warning and info (muted tint background, status-coloured text).
- **Table:** `text-sm`. The header row is `h-10 px-2 font-medium`. Rows have `border-b` and `hover:bg-muted/50`, and there are no zebra stripes.
- **Tabs (and the floor segmented control):** `bg-muted rounded-lg p-[3px] h-9`. The active trigger is `bg-background shadow-sm`.
- **Alert:** `rounded-lg`, border, padding 12px 16px, `text-sm`, an icon column. Variants default and destructive, plus the status variants.
- **Sidebar:** 16rem wide. Groups have a `text-xs` label, and menu buttons are 32px tall, `rounded-md`, `text-sm`. The active item is `bg-sidebar-accent font-medium`. Below 1024px the sidebar becomes a **Sheet**: it slides from the left over a `bg-black/50` overlay and has a close button.
- **Also used:** Sheet, Dropdown menu (the account menu), Separator, Skeleton (`bg-accent`, pulse), Empty (icon, title, description, action), Field (label, control, description, error), Breadcrumb (deep IFO pages).
- **Shadows:** only `shadow-xs` (controls), `shadow-sm` (cards) and `shadow-lg` (popovers and sheets).
- **Motion:** 150ms ease on colour and opacity, and 200ms on the sheet slide. None under `prefers-reduced-motion`.

**MMCM tailoring (the only places we depart from stock shadcn):**
1. The colour values above: navy primary, red destructive, navy-tinted neutrals (the sidebar stays light, as stock shadcn).
2. The MMCM crest beside the "FluxTrack" wordmark in every shell header and sidebar.
3. The **navy hero card** on floor-role home screens. It is a shadcn Card with `bg-primary text-primary-foreground` (a variant, not a new component).
4. **Touch sizes:** on floor roles, and on any screen narrower than 640px, the primary actions use Button `lg`, raised from 40px to 44px, and inputs are 44px tall (PRODUCT.md: touch targets ≥ 44px). Desk roles at 640px and wider keep the stock 36px.
5. Status colours (success, warning, info) are added to Badge and Alert because attendance needs them. They are never used for decoration.

**My calls (veto any):**
- **(my call) Font:** Geist Sans (shadcn's default), vendored as woff2 under `static/vendor/geist/`, with no CDN, so offline and the PWA keep working. Fallback: system-ui.
- **(user's call, 2026-11-08) Light sidebar, not navy.** Desk consoles use stock shadcn's light sidebar. MMCM shows there through the crest, navy text and icon on the active item, and the navy primary buttons. Navy surfaces are kept for the floor hero card only.
- **(my call) One breakpoint ladder,** the same as Franken and Tailwind: 640, 768, 1024, 1280px (40, 48, 64, 80rem). The console collapses to a drawer below 1024px instead of 900px.
- **(my call) Desk pages that have no console today move into one:** HR gets an HR console (Attendance, Notifications), SysAdmin gets a SysAdmin console (Job monitor, Users and settings, Audit log). Admin profile and admin notifications render inside the user's own console.
- **(my call) Checker flag flow:** two primary buttons, "Verify present" and "Report a problem". The second opens one reason choice (wrong person / not present), one note and one "Send flag" button. Under the hood it is still the same two `action` values posted to `/checker/action`.

---

## Global Constraints

- Interpreter: `C:/Users/joshu_mnu8z3u/AppData/Local/Programs/Python/Python312/python.exe manage.py test <label>`. Bare `python` has no Django.
- After **any** CSS or static edit, before a browser check: `... python.exe manage.py collectstatic --noinput`. Whitenoise serves hashed copies, so a skipped run means you are checking stale CSS.
- There is no Tailwind build. Before using any utility class, confirm that it exists in `static/vendor/franken-ui/2.1.2/utilities.min.css`. For anything positional or load-bearing, write real CSS in `ui.css`.
- Never put `*/` inside a CSS comment. shadcn's colour roles are **set** only in `tokens.css` on `html.uk-theme-neutral` (that is the one place we override Franken's own names). Everywhere else, **read** them as `hsl(var(--role))`. Our own additions are `--radius*`, `--sidebar*`, `--success*`, `--warning*` and `--info*` (shadcn naming). The legacy `--ft-*` and `--nv-*` tokens become aliases of these roles, then are deleted once no rule reads them.
- **shadcn first:** if Franken has the shadcn component (`uk-btn`, `uk-input`, `uk-select`, `uk-textarea`, `uk-card`, `uk-badge`, `uk-label`, `uk-alert`, `uk-table`, `uk-tab`, `uk-drop`/dropdown, `uk-toggle`), use it. `ui.css` only adds components Franken lacks: Sidebar, Sheet, Stat, Field, Empty, Steps, stacked Table, and the MMCM brand mark. Each is written to the anatomy in "shadcn fidelity".
- **No raw colours** (`#hex`, `rgb()`, named colours) in any stylesheet except `tokens.css`. `static/css/timetable.css` print rules may use `#000` and `#fff` only.
- Django `{# #}` comments are single-line only. Use `{% comment %}` for anything that wraps.
- Keep every class name and string that an existing test asserts (listed below). Where a test pins the **old** design on purpose, update it in the same task and list the change in that task's commit message and in the final report. Never weaken a test silently.
- Keep every element ID and `data-offline-*` hook in `templates/checker/scan.html`, `templates/checker/offline.html` and `static/checker/offline_queue.js`.
- Browser checks run on a **throwaway** database restored from `fluxtrack`, with the clock frozen at Monday 2026-07-20 10:52 (see memory `figma-user-journey`). Never on the dev DB. Use gstack `/browse`, never the `mcp__claude-in-chrome__*` tools.
- Full test runs rewrite `FluxTrack_SRS.docx`. Back it up first and restore it after.
- Run the full suite with frozen clocks at 00:10, 07:00 and 23:50 as well as the real clock ("Sweep the clock").
- ASCII-only in CSS and template comments (the existing house rule).
- Commit only when the user says so. Each task's "Commit" step means: stage the listed files, show the staged list, and commit **only if the user has authorised commits for this run**. Otherwise leave the changes staged and continue.
- Touch targets ≥ 44px. Body text contrast ≥ 4.5:1. A visible focus ring on every control. Honour `prefers-reduced-motion`.

**Tested strings that must survive** (from `grep` of the suites on 2026-11-08):
- `ft-row__title`, `ft-history-cards`, `ft-history-card__course`, `ft-top`, `ft-app`, `ft-tabbar__role`, `ft-tab__label`, `ft-error`
- `id="offline-banner" class="hidden ft-banner"`, the CSS rule `.ft-banner.hidden { display: none; }`
- `.ft-tab__label { display: none; }`, `@media (min-width: 48rem)`, `@media (min-width: 64rem)`, `body:has(.ft-tabbar) .ft-page` and `max-width: 72rem` in `faculty.css`
- `cns__link is-active`, `cns__bar`, `dn-faculty-card`, `dn-session__controls`, `dn-change-flow`, `uk-btn-destructive`
- No `ft-` class on IFO pages (`web/tests_ifo_utilization.py:327`)

**Tests that pin the OLD desk header and must change in Task 5** (tell the user):
- `web/tests_ux_finish.py::FloorNotificationShellTests::test_admin_notification_page_keeps_the_desktop_shell` asserts `uk-label uk-label-secondary`.
- `web/tests.py` around line 1083: the admin `/notifications` page has exactly one `<header`, contains `sticky top-0`, and does not contain `cns__bar`.
- `web/tests_faculty_profile.py:263` and `web/tests_ux_finish.py:91` assert the floor pages do **not** contain the Franken label. These stay true and need no change.

## Review Focus

1. **Long names and codes at 360px.** Names like "Ma. Eloisa P. Española", room codes like "SS085-C216" and department names must wrap or truncate with an ellipsis, never push the page sideways. Owner: Task 9, test `test_stacked_rows_carry_labels` plus the overflow probe in Task 15.
2. **Polling swaps (htmx) inside the new layouts.** The IFO room board, Checker floor and Guard monitor re-render every few seconds. New wrappers must not sit inside the swapped region, or they will duplicate or vanish. Owner: Tasks 6, 7 and 8. The browser check waits for two polls and counts headers.
3. **Mobile drawer and keyboard.** Below 1024px the console sidebar is a drawer. It must trap focus while open, close on Escape and on the scrim, return focus to the menu button, and stop the page behind it from scrolling. Owner: Task 6, browser check.
4. **Checker "Report a problem" with no JavaScript, or offline.** The flag must still be sendable. Without JS, the reason radios and the note are visible and posted as one form. The offline queue hooks must still fire. Owner: Task 10, test `test_flag_form_posts_one_action_with_one_note` plus a JS-off browser check.
5. **Print.** The scorecard, room timetable and room poster must still print cleanly after moving inside the console (sidebar and bar hidden in `@media print`). Owner: Task 5, browser print-preview check.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `static/css/tokens.css` | modify | The full design contract: brand, semantic, type scale, spacing, radius, breakpoints as comments, font-face |
| `static/vendor/geist/Geist-Variable.woff2`, `static/vendor/geist/LICENSE.txt` | create | Vendored font (shadcn default) |
| `static/css/ui.css` | create | Part A: Franken's shadcn components tuned to spec via their variables. Part B: shadcn components Franken lacks (Sidebar, Sheet, Stat, Field, Empty, Steps, stacked Table, brand mark, account dropdown) |
| `static/css/app.css` | modify | Keep utilities (skeleton, skip link, `.tbl`). Move component rules that duplicate `ui.css` into it |
| `static/faculty/faculty.css` | modify | Floor-only parts (hero, scan, keypad, tab bar, outcome). Re-point radius and type to tokens. Fix tab-bar clearance and desktop layouts |
| `static/css/console.css` | modify | Console shell. Breakpoint 1024px. Drawer behaviour. Print rules |
| `templates/base.html` | modify | Load `ui.css`. Body font. The legacy header becomes an unauthenticated-only fallback |
| `templates/_brand.html`, `templates/_account_menu.html` | create | One brand mark and one account menu, included by every shell |
| `templates/_console.html` | modify | Use the shared partials. Drawer a11y. Mobile bar shows the brand |
| `templates/hr/_console.html`, `templates/sys/_console.html` | create | Thin role consoles (pattern: `templates/dean/_console.html`) |
| `web/context.py` | modify | Add `role_console(request)`: the one rule for which console a desk user gets |
| `config/settings.py` | modify | Register the context processor |
| `templates/notifications/list_console.html`, `templates/notifications/settings_console.html`, `templates/web/profile_console.html` | create | Desk-role versions of shared pages, extending `{{ console_template }}` |
| `templates/hr/*.html`, `templates/sys/jobs.html`, `templates/web/home.html`, `templates/reports/scorecard.html` | modify | Move into consoles; use `ui.css` components |
| `templates/ifo/_cards.html`, `templates/ifo/dashboard.html` | modify | Calmer KPI row, stacked table |
| `scheduling/reporting.py:420` | modify | `_name(first, last, username="")` fallback |
| `templates/checker/_outcome.html` | modify | One-decision flag flow |
| `templates/checker/offline.html` | modify | Styled, self-contained offline page |
| `templates/ifo/terms.html`, `templates/ifo/term_detail.html` | modify | Term lifecycle step tracker |
| `templates/admin/base_site.html` | create | Django admin branding (navy and crest) |
| `web/tests_design_system.py` | create | All new tests for this plan, one class per task |
| `docs/DESIGN.md` | create | Human-readable design system, written from what shipped |
| `docs/ui-audit/2026-11-08-baseline.md` | create | Measured defects per page per width, before and after |

---

### Task 1: Baseline audit harness

**Files:**
- Create: `scratchpad/ui_audit/routes.py` (scratchpad, not repo): a list of `(role, username, path)` covering every non-partial template, built from `web/urls.py`, `config/urls.py` and the 2026-11-08 shot manifest (`<old scratchpad>/manifest.jsonl`, `flows_*.py`)
- Create: `scratchpad/ui_audit/probe.py`: drives gstack browse at widths 360, 390, 768, 1024 and 1440. For each page it records `document.documentElement.scrollWidth > innerWidth`, elements whose `getBoundingClientRect().right > innerWidth`, console errors, header count, and a screenshot
- Create: `docs/ui-audit/2026-11-08-baseline.md`

**Interfaces:**
- Produces: `probe.py --out <dir> --label <before|after>` writes `<dir>/<label>/<role>__<slug>__<width>.png` and `<dir>/<label>/report.json` (`[{role, path, width, overflow_px, offenders:[selector], console_errors:int, headers:int}]`). Task 15 reruns it with `--label after`.

- [ ] **Step 1:** Restore a throwaway DB `fluxtrack_ui` from `fluxtrack` (`BACKUP ... WITH COPY_ONLY`, then `RESTORE ... WITH MOVE`), run `migrate` against it, and start `runserver` with `DB_NAME=fluxtrack_ui` and the frozen-clock shim (`frozen.py` pattern from the 2026-11-08 scratchpad) at 2026-07-20T10:52+08:00.
- [ ] **Step 2:** Run `probe.py --label before`. Expected: one report row per (page, width). Zero 500s. If a page returns 500, record it and do not fix it here.
- [ ] **Step 3:** Write `docs/ui-audit/2026-11-08-baseline.md`: a table of every page with any width where `overflow_px > 0`, the offending selectors, console errors, and a "seen" column of visual defects from reading the screenshots. Include the defects listed in the spec, confirmed or refuted by this run.
- [ ] **Step 4:** Commit `docs/ui-audit/2026-11-08-baseline.md` (see Global Constraints on commits).

### Task 2: shadcn tokens tailored to MMCM, font and breakpoint ladder

**Files:**
- Modify: `static/css/tokens.css`
- Create: `static/vendor/geist/Geist-Variable.woff2`, `static/vendor/geist/LICENSE.txt` (download from the official vercel/geist-font release; check the licence file is OFL-1.1)
- Modify: `static/css/console.css`, `static/css/app.css`, `static/css/board.css`, `static/faculty/faculty.css`: media queries only in this task
- Test: `web/tests_design_system.py::TokenContractTests`

**Interfaces:**
- Produces, on `html.uk-theme-neutral`: every colour role in the "shadcn fidelity" table, with exactly those values. Also `--radius` and `--radius-sm/md/lg/xl`, plus `--uk-global-radius: var(--radius-md)` and `--uk-global-radius-s: var(--radius-sm)`, so Franken components follow the same ladder.
- Produces, on `:root`:
  - `--font-sans "Geist", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`
  - `--tabbar-h` (measure the floor tab bar height plus its bottom gap in the browser and pin the real value)
  - `--content-max 72rem`
  - `--touch 44px`
- Keeps the legacy `--nv-*`, `--ink`, `--body`, `--ft-muted`, `--line`, `--green*`, `--amber*`, `--red*`, `--purple*`, `--info-*`, `--*-wash` and `--r-hero/card/btn/pill` names as **aliases** that point at the new roles (e.g. `--nv-hero: hsl(var(--primary))`, `--r-card: var(--radius-xl)`). Then `faculty.css` keeps working until Task 8 rewrites it. The alias block carries a comment saying it is deleted at the end of Task 8.
- Breakpoints are documented in a comment only, since CSS custom properties cannot be used in `@media`: sm 640, md 768, lg 1024, xl 1280.

- [ ] **Step 1: Write the failing tests**

```python
class TokenContractTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent
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
        src = (self.root / "static/css/tokens.css").read_text("utf-8")
        block = re.search(r"html\.uk-theme-neutral\s*\{(.*?)\}", src, re.S).group(1)
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
        src = (self.root / "static/css/tokens.css").read_text("utf-8")
        for name in ("--font-sans", "--tabbar-h", "--content-max", "--touch"):
            self.assertIn(name + ":", src)
        self.assertIn("@font-face", src)
        self.assertIn("Geist-Variable.woff2", src)
        self.assertTrue((self.root / "static/vendor/geist/Geist-Variable.woff2").exists())

    def test_muted_foreground_clears_aa_on_white_and_muted(self):
        # compute WCAG contrast from the HSL triplets in tokens.css
        # (write a tiny hsl->rgb->relative-luminance helper in this test module)
        self.assertGreaterEqual(contrast("--muted-foreground", "--background"), 4.5)
        self.assertGreaterEqual(contrast("--muted-foreground", "--muted"), 4.5)
        self.assertGreaterEqual(contrast("--primary-foreground", "--primary"), 4.5)
        self.assertGreaterEqual(contrast("--sidebar-foreground", "--sidebar"), 4.5)
        self.assertGreaterEqual(contrast("--sidebar-accent-foreground", "--sidebar-accent"), 4.5)

    def test_body_uses_the_shared_font(self):
        src = (self.root / "static/css/tokens.css").read_text("utf-8")
        self.assertRegex(src, r"body\s*\{[^}]*font-family:\s*var\(--font-sans\)")
```

- [ ] **Step 2:** Run `... manage.py test web.tests_design_system.TokenContractTests`. Expected: FAIL. The ladder test names `620px` (console.css), `900px`, `1023px` and `23rem`. The role test fails on `--background` (we do not set it yet) and on `--sidebar`.
- [ ] **Step 3:** Add the roles, radius ladder, aliases, `@font-face` (`font-display: swap`) and `body { font-family: var(--font-sans) }`. If the contrast test fails on a value from the table, adjust **lightness only** until it passes, and record the final value in the plan table and in `docs/DESIGN.md`. Map the off-ladder queries: `23rem` → `40rem` (only if the history filter still fits at 360px, otherwise drop the query); `620px` → `max-width: 639.98px`; `900px` → `max-width: 1023.98px`; `1023px` → `1023.98px`; `board.css` `641px` → `640px`; any bare `max-width: 640px` → `639.98px` so the two sides of 640 do not overlap. Keep `48rem` and `64rem` in `faculty.css`, because tests pin them.
- [ ] **Step 4:** Run the same test. Expected: PASS. Run `web.tests_ux_finish`. Expected: PASS (the pinned faculty.css strings are intact).
- [ ] **Step 5:** Commit `static/css/*.css static/faculty/faculty.css static/vendor/geist web/tests_design_system.py` with the message `feat(ui): shadcn roles in MMCM colours, Geist font, breakpoint ladder`.

### Task 3: shadcn components, tuned to the spec

**Files:**
- Create: `static/css/ui.css`
- Modify: `templates/base.html` (load order: Franken core → utilities → tokens → app → **ui** → faculty), `static/css/app.css` (`.tbl` stays here; restyle it to the shadcn Table spec; add `.tbl--stack`)
- Test: `web/tests_design_system.py::ComponentSheetTests`

**Part A: tune Franken's shadcn components to the exact spec.** Set them through Franken's own component variables in `ui.css` (`--uk-btn-height`, `--uk-btn-padding`, `--uk-input-*` and so on; read `core.min.css` for the real names first), so that markup keeps using `uk-*` classes:
- `uk-btn` heights 36/32/40px and the six variants (`uk-btn-default`, `uk-btn-primary`, `uk-btn-secondary`, `uk-btn-ghost`, `uk-btn-destructive`, `uk-btn-link`; check that each exists in the bundle). Focus ring per spec.
- `uk-input`, `uk-select` and `uk-textarea` are 36px tall with `shadow-xs`, and `[aria-invalid="true"]` gets the destructive ring.
- `uk-card` uses `rounded-xl`, `shadow-sm` and 24px padding.
- `uk-badge` and `uk-label` use the Badge spec, plus `.uk-badge-success`, `-warning`, `-info` (MMCM status extension).
- `uk-alert` uses the Alert spec, plus status variants.
- `uk-tab` uses the Tabs spec (muted track, raised active trigger).
- Below 640px, every `uk-btn` and form control is `min-height: var(--touch)` (MMCM tailoring 4).

**Part B: components Franken lacks (the class contract every later task uses):**
- `.ui-pagehead` with `__title` (h1, `text-2xl font-semibold tracking-tight`), `__desc` (muted, `text-sm`, max 65ch) and `__actions` (wraps below 640px)
- `.ui-stats`: an auto-fit grid, `minmax(11rem,1fr)`, equal-height Cards. `.ui-stat` contains `__label` (`text-sm` muted), `__value` (`text-2xl font-semibold`, tabular-nums) and `__note` (`text-xs` muted, one line)
- `.ui-filterbar`: a `<details open>` wrapper. Below 640px it starts closed, and the summary is an outline Button reading "Filters" plus a count Badge. At 640px and up the summary is hidden and the fields sit in a wrapping row, with the buttons at the end
- `.ui-field` with `__label` (`text-sm font-medium`), `__desc` (`text-sm` muted) and `__error` (`text-sm` destructive)
- `.ui-empty` with `__icon` (40px muted tile), `__title`, `__desc` and `__action`
- `.ui-steps` (an ordered list; `li.ui-step` has `is-done`, `is-current` or neither; horizontal at 768px and up, vertical below; a numbered 24px circle, done = primary with a check, current = primary ring)
- `.ui-sidebar` (shadcn Sidebar spec, reading `--sidebar*`) with `__header`, `__group`, `__group-label`, `__menu`, `__item` and `__footer`. Below 1024px it becomes `.ui-sheet` (left sheet, `shadow-lg`, `bg-black/50` overlay, 200ms slide)
- `.ui-brand` (24px crest plus the "FluxTrack" wordmark, `font-semibold`) and `.ui-acct` (shadcn Dropdown menu: 32px avatar trigger, a `shadow-lg` popover with a label, separator and items). The markup lives in Task 4's partials
- `.tbl--stack`: below 640px, `thead` is visually hidden (`.sr-only` pattern), each `tr` is a Card, and each `td::before { content: attr(data-label) }` labels the cell in `text-xs` muted

- [ ] **Step 1: Write the failing tests**

```python
class ComponentSheetTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def test_ui_sheet_defines_the_component_contract(self):
        src = (self.root / "static/css/ui.css").read_text("utf-8")
        for sel in (".ui-pagehead", ".ui-stats", ".ui-stat__value", ".ui-filterbar",
                    ".ui-field__error", ".ui-empty", ".ui-steps", ".ui-sidebar",
                    ".ui-sheet", ".ui-brand", ".ui-acct", ".uk-badge-success",
                    ".uk-badge-warning", ".uk-badge-info", "--uk-btn-height"):
            self.assertIn(sel, src)

    def test_no_raw_colours_outside_tokens(self):
        # Task 8 appends "static/faculty/faculty.css" and "static/css/board.css".
        for rel in ("static/css/ui.css", "static/css/app.css", "static/css/console.css"):
            src = re.sub(r"/\*.*?\*/", "", (self.root / rel).read_text("utf-8"), flags=re.S)
            self.assertNotRegex(src, r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", rel)

    def test_stack_tables_label_cells_from_data_label(self):
        src = (self.root / "static/css/app.css").read_text("utf-8")
        self.assertIn("content: attr(data-label)", src)
        self.assertIn(".tbl--stack", src)

    def test_base_loads_ui_between_app_and_faculty(self):
        src = (self.root / "templates/base.html").read_text("utf-8")
        self.assertLess(src.index("css/app.css"), src.index("css/ui.css"))
        self.assertLess(src.index("css/ui.css"), src.index("faculty/faculty.css"))

    def test_ui_sheet_has_no_side_stripes_or_franken_token_names(self):
        src = (self.root / "static/css/ui.css").read_text("utf-8")
        self.assertNotRegex(src, r"border-left:\s*[3-9]px")
        self.assertNotRegex(src, r"--(muted|border|primary|background)\s*:")
```

- [ ] **Step 2:** Run `web.tests_design_system.ComponentSheetTests`. Expected: FAIL (`ui.css` missing).
- [ ] **Step 3:** Write `ui.css` (Part A, then Part B), reading only `hsl(var(--role))` and the radius, font and touch tokens. Restyle `.tbl` to the Table spec, add `.tbl--stack` to `app.css`, and replace its two raw hexes with roles. Load `ui.css` in `base.html`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then `collectstatic`, and build a scratch gallery page (render-harness pattern from memory `faculty-navy-redesign`) showing every Button variant and size, Input (default, focus, invalid, disabled), Card, Badge (all variants), Alert, Tabs, Stat row, Field, Empty, Steps, Sidebar, Sheet open and the account dropdown, at 390px and 1280px. Put it **side by side with the shadcn docs examples** (ui.shadcn.com/docs/components, via `/browse`) and fix every visible mismatch in size, spacing, radius, weight or ring that is not one of the five MMCM tailorings.
- [ ] **Step 5:** Commit with the message `feat(ui): shadcn components to spec, MMCM tailored`.

### Task 4: One brand mark and one account menu in every shell

**Files:**
- Create: `templates/_brand.html` (`<a class="ui-brand" href="{{ home }}"><img src="{% static 'brand/mmcm-crest.png' %}" alt=""><b>FluxTrack</b></a>`, where `home` is passed via `{% include ... with home=... %}`), `templates/_account_menu.html` (avatar initials or photo; name; role and department; links Profile `{% url 'profile' %}`, Notification settings `/notifications/settings`, Sign out `/logout`)
- Modify: `templates/_console.html` (brand plus sidebar foot), the floor `ft-top` header (find every copy with `grep -rl "ft-top__brand" templates`; today it is inlined in about 12 templates, so extract it to `templates/_floor_top.html` and include it), `templates/notifications/_floor_header.html`
- Test: `web/tests_design_system.py::SharedChromeTests`

**Interfaces:**
- Consumes: `.ui-brand` and `.ui-acct` from Task 3
- Produces: `templates/_floor_top.html` (include with `home=`); `_brand.html`; `_account_menu.html`. Keep the `ft-top` class on the floor header element and `cns__bar` on the console bar (both are tested).

- [ ] **Step 1: Write the failing test**

```python
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
                self.assertEqual(body.count('class="ui-acct'), 1)
                self.assertIn("brand/mmcm-crest.png", body)
                self.client.logout()
```

If a role page needs fixtures (an active term, a posting), use the existing helpers in `web/tests_ux_finish.py` and `web/tests.py`. Read them before writing your own.

- [ ] **Step 2:** Run it. Expected: FAIL (count 0).
- [ ] **Step 3:** Create the partials and swap them into both shells. Floor-role menus keep every link they have today (e.g. Faculty's Profile and History), so `FacultyProfileReachabilityTests` stays green.
- [ ] **Step 4:** Run `web.tests_design_system.SharedChromeTests web.tests_ux_finish web.tests_faculty_profile web.tests`. Expected: PASS, apart from the three known dev-login failures in memory `django-test-interpreter`.
- [ ] **Step 5:** Commit with the message `feat(ui): one brand mark and account menu across shells`.

### Task 5: Every desk page inside a console

**Files:**
- Modify: `web/context.py` (add `role_console`), `config/settings.py` (register `web.context.role_console`)
- Create: `templates/hr/_console.html` (nav: Attendance `hr_attendance`, Notifications), `templates/sys/_console.html` (nav: Job monitor `sys_jobs`, Users and settings `/admin/`, Audit log: use the link `sys/jobs.html` already has)
- Create: `templates/notifications/list_console.html`, `templates/notifications/settings_console.html`, `templates/web/profile_console.html`. Each `{% extends console_template %}` and includes the existing body partials. If there are none, extract the shared middle of `notifications/list.html`, `settings.html` and `faculty/profile.html` into `_*_body.html` partials first
- Modify: the views that render those pages (`web/faculty.py:profile`, the notifications list and settings views) to pick `*_console.html` when `console_template` is set, `templates/hr/attendance.html`, `templates/sys/jobs.html`, `templates/web/home.html` (superuser hub → sys console), `templates/reports/scorecard.html` (extends `console_template`; print CSS hides the console chrome), `templates/base.html` (the legacy header renders only for authenticated users with no console and no floor shell; today that is no one, so keep it as a safe fallback)
- Modify (old-design tests, see Global Constraints): `web/tests_ux_finish.py::test_admin_notification_page_keeps_the_desktop_shell` and the `web/tests.py` test around line 1083
- Test: `web/tests_design_system.py::ConsoleEverywhereTests`

**Interfaces:**
- `role_console(request) -> {"console_template": str | None}` returns `"ifo/_console.html"` for IFO_ADMIN, `"dean/_console.html"` for DEAN, `"hr/_console.html"` for HR_ADMIN, and `"sys/_console.html"` for SYSTEM_ADMIN or a superuser with no role. It returns `None` for FACULTY, CHECKER, GUARD and anonymous users. This is the only place this mapping exists ("Share one rule").

- [ ] **Step 1: Write the failing tests**

```python
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
            req = rf.get("/"); req.user = get_user_model()(username=f"m_{role}", role=role)
            self.assertEqual(role_console(req)["console_template"], expected)

    def test_active_nav_item_marks_the_current_desk_page(self):
        u = get_user_model().objects.create(username="cns_hr_nav", role=Role.HR_ADMIN)
        self.client.force_login(u)
        body = self.client.get("/hr/attendance").content.decode()
        self.assertIn('class="cns__link is-active"', body)
```

- [ ] **Step 2:** Run it. Expected: FAIL. HR, sys, profile and notifications have no `class="cns"`.
- [ ] **Step 3:** Implement. Update the two old-design tests so they assert the console: one `<header`, `cns__bar` present, and the role's nav present. Keep each test's original intent: the page has exactly one header and real navigation. Note both test changes in the commit message.
- [ ] **Step 4:** Run `web.tests_design_system web.tests_ux_finish web.tests web.tests_faculty_profile ops`. Expected: PASS, apart from the three known failures.
- [ ] **Step 5:** Browser check on the throwaway DB: HR, SysAdmin and IFO profile at 390px and 1440px. Print preview of the scorecard shows no sidebar.
- [ ] **Step 6:** Commit with the message `feat(ui): every desk page lives in its role console` and a body that lists the two updated tests and why.

### Task 6: Console shell responsive and accessible

**Files:**
- Modify: `static/css/console.css`, `templates/_console.html` (inline script)
- Test: `web/tests_design_system.py::ConsoleShellTests`

- [ ] **Step 1: Write the failing tests**

```python
class ConsoleShellTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def test_console_collapses_at_lg_and_hides_chrome_in_print(self):
        css = (self.root / "static/css/console.css").read_text("utf-8")
        self.assertIn("@media (max-width: 1023.98px)", css)
        self.assertRegex(css, r"@media print\s*\{[^@]*\.cns__side[^}]*display:\s*none")

    def test_drawer_script_traps_focus_and_locks_scroll(self):
        html = (self.root / "templates/_console.html").read_text("utf-8")
        self.assertIn("inert", html)          # main region inert while drawer open
        self.assertIn("overflow", html)       # body scroll lock toggled
        self.assertIn('aria-modal="true"', html)
```

- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3a:** Rebuild the console sidebar on the shadcn Sidebar spec using `.ui-sidebar*` from Task 3: a light `--sidebar` surface (stock shadcn; not navy, per the user) with a `--sidebar-border` right edge; the crest and wordmark in `__header`; IFO's existing sections (Academic lifecycle, Campus calendar, Reporting) as `__group` and `__group-label`; 32px `__item` menu buttons, with the active item on `--sidebar-accent` with navy `--sidebar-accent-foreground` text and icon; and identity plus sign-out in `__footer` via `_account_menu.html`. Keep the `cns__link` and `is-active` classes on each item (tests pin `class="cns__link is-active"`). Add `ui-sidebar__item` as a second class only if the pinned string stays byte-identical; otherwise style `.cns__link` directly from the spec. The top bar (`cns__bar`) becomes the shadcn inset header: 56px, a bottom border, the page title on the left, actions and the bell on the right, and a breadcrumb on IFO detail pages (room, building, term).
- [ ] **Step 3:** Implement. Below 1024px the sidebar becomes a shadcn **Sheet** (`.ui-sheet`): an off-canvas `role="dialog" aria-modal="true"` drawer. While it is open, `.cns__main` gets `inert` and `document.body.style.overflow = "hidden"`; on close both revert and focus returns to `[data-cns-open]`. The mobile `cns__bar` shows `_brand.html`. `cns__body` padding is `--sp-4` below 640px and `--sp-6` above. `cns__actions` wraps. Add print rules.
- [ ] **Step 4:** Run the tests. Expected: PASS. Browser: IFO rooms board at 390px, 768px and 1024px. Open the drawer, Tab through it (focus stays inside), press Escape (focus returns to the menu button). Wait for two board polls and confirm there is still one `cns__bar`.
- [ ] **Step 5:** Commit with the message `feat(ui): console drawer below 1024px with focus trap`.

### Task 7: Floor shell responsive

**Files:**
- Modify: `static/faculty/faculty.css`, `templates/faculty/home.html`, `templates/checker/floor.html`, `templates/guard/monitor.html`
- Test: `web/tests_design_system.py::FloorShellTests`

- [ ] **Step 1: Write the failing tests**

```python
class FloorShellTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def test_pages_with_a_tab_bar_clear_it(self):
        css = (self.root / "static/faculty/faculty.css").read_text("utf-8")
        self.assertRegex(css, r"body:has\(\.ft-tabbar\) \.ft-page\s*\{[^}]*padding-bottom:\s*calc\([^)]*var\(--tabbar-h\)")

    def test_floor_radius_reads_the_shared_ladder(self):
        css = (self.root / "static/faculty/faculty.css").read_text("utf-8")
        self.assertNotRegex(css, r"border-radius:\s*(26|18|14)px")

    def test_home_has_a_two_column_desktop_layout(self):
        css = (self.root / "static/faculty/faculty.css").read_text("utf-8")
        self.assertIn(".ft-home-grid", css)
        html = (self.root / "templates/faculty/home.html").read_text("utf-8")
        self.assertIn('class="ft-home-grid"', html)
```

- [ ] **Step 1b:** Read `body:has(.ft-tabbar) .ft-page` in `faculty.css` first, because a test already pins that selector. Extend it; do not rename it.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - Clearance: `padding-bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom) + var(--sp-4))`.
  - Radius: re-point every literal radius to `--radius-*` (the full shadcn re-skin is Task 8; this task only does layout).
  - `.ft-home-grid`: one column below 1024px; from 1024px up, `grid-template-columns: minmax(0,26rem) minmax(0,1fr)` with the hero on the left and Today's list on the right.
  - Checker floor and Guard monitor lists: `.ft-list` becomes a 2-column grid from 768px and 3 columns from 1280px.
  - The polled regions (`#floor-rows`, the guard rows container) stay the swap targets, and the grid class goes on the swapped container's parent so that a swap keeps the layout.
- [ ] **Step 4:** Run `web.tests_design_system.FloorShellTests web.tests_ux_finish`. Expected: PASS. Browser at 390px: the last list item on Guard monitor and Faculty schedule is fully above the tab bar. At 1440px: Faculty home is two columns, and the Checker floor is a 3-column grid after two polls.
- [ ] **Step 5:** Commit with the message `feat(ui): floor shell uses desktop width and clears the tab bar`.

### Task 8: Floor family on shadcn anatomy

The Faculty, Checker and Guard screens keep their layouts and the navy hero, but every part is rebuilt to the shadcn spec, reading only shadcn roles.

**Files:**
- Modify: `static/faculty/faculty.css` (rewrite rules; keep every class name a test pins), `static/css/board.css` (colours to roles), `static/css/tokens.css` (delete the legacy alias block from Task 2 once nothing reads it)
- Modify templates only where a shadcn part needs different markup (for example, the account menu already comes from Task 4). Prefer changing CSS over markup, because markup carries the htmx and offline hooks.
- Test: `web/tests_design_system.py::FloorShadcnTests`, and extend `ComponentSheetTests.test_no_raw_colours_outside_tokens` with `static/faculty/faculty.css` and `static/css/board.css`

**Mapping (old floor part → shadcn part, MMCM tailoring noted):**

| Floor class | Becomes |
|---|---|
| `.ft-hero` | Card, `bg-primary text-primary-foreground`, `--radius-xl`, 24px padding (tailoring 3) |
| `.ft-seg` / `.ft-seg__opt` | Tabs on primary: track `hsl(var(--primary-foreground) / .08)`, active trigger `bg-background text-foreground shadow-sm` |
| `.ft-cta`, `.ft-btn-navy`, `.ft-btn-danger`, `.ft-btn-soft`, `.ft-btn-ghost-sm` | Button default, destructive, secondary, ghost sm; floor primary actions at `--touch` height (tailoring 4) |
| `.ft-control`, `.ft-input-nv`, `.ft-otp__box` | Input (44px on floor); OTP boxes follow shadcn InputOTP (slots joined, `rounded-md` ends, active slot ring) |
| `.ft-pill--*` | Badge: `active` and `approved` are success; `late` and `pending` are warning; `absent` is destructive; `upcoming` and `online` are info; `done` and `merged` are secondary; `blended` is outline with `--chart-2` text |
| `.ft-row`, `.ft-card--*`, `.ft-history-card` | Card (`rounded-xl`, `shadow-sm`, 16px padding on floor). State is shown by a Badge plus an icon, and no longer by a card wash |
| `.ft-outcome--*` | Alert: ok is success, warn is warning, bad is destructive, info is info, neutral is default. Title and description per spec |
| `.ft-alert-error`, `.ft-banner` | Alert destructive / warning (keep `.ft-banner.hidden { display: none; }` byte-identical) |
| `.ft-tabbar` / `.ft-tab` | A bottom navigation bar in shadcn style: `bg-background/95` with a `border-t` and `shadow-lg`, 44px items, active = `bg-accent text-accent-foreground rounded-md` with a primary icon. Desktop labels as today (keep the pinned strings) |
| `.ft-top` | Inset header: 56px, the crest and wordmark (`_brand.html`), and the bell plus account dropdown on the right |
| `.ft-keypad` / `.ft-key` | Button outline lg grid, 56px keys |
| `.ft-chip` | Badge outline, as a link |

- [ ] **Step 1: Write the failing tests**

```python
class FloorShadcnTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def css(self):
        return (self.root / "static/faculty/faculty.css").read_text("utf-8")

    def test_floor_reads_only_shadcn_roles(self):
        src = re.sub(r"/\*.*?\*/", "", self.css(), flags=re.S)
        self.assertNotRegex(src, r"var\(--(nv|ft)-")   # legacy floor tokens gone
        self.assertNotRegex(src, r"var\(--(ink|body|line|green|amber|red|purple)\b")
        self.assertIn("hsl(var(--primary))", src)

    def test_legacy_alias_block_is_deleted(self):
        tokens = (self.root / "static/css/tokens.css").read_text("utf-8")
        self.assertNotIn("--nv-hero", tokens)

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
```

- [ ] **Step 2:** Run it, plus the extended raw-colour test. Expected: FAIL (faculty.css reads `--nv-*` and has 48 raw hexes; board.css has 8).
- [ ] **Step 3:** Rewrite `faculty.css` section by section to the mapping. After each section, `collectstatic` and look at the matching screens at 390px with the render harness (`scratchpad/render_outcomes.py` pattern) and on the live throwaway DB. Convert `board.css` colours to roles; the room-state colours map to `--success`, `--warning`, `--destructive`, `--info` and `--muted`. Then delete the alias block from `tokens.css`.
- [ ] **Step 4:** Run `web.tests_design_system web.tests_ux_finish web.tests_faculty_history web.tests_faculty_profile verification web.tests`. Expected: PASS, apart from the three known failures. Browser at 390px and 1440px: Faculty home (all four hero states), scan, manual code, every outcome, requests and the wizard; Checker floor, scan, outcomes and online; Guard monitor, locate and room. Compare each with the Task 3 gallery for spacing, radius and ring.
- [ ] **Step 5:** Commit with the message `feat(ui): floor family rebuilt on shadcn anatomy`.

### Task 9: Desk tables, filter bars and the IFO dashboard

**Files:**
- Modify: `templates/hr/attendance.html`, `templates/hr/_rows.html`, `templates/ifo/_cards.html`, `templates/ifo/dashboard.html`, `templates/dean/reports.html`, `templates/dean/dashboard.html`, `templates/sys/jobs.html`, `templates/ifo/weekly_reports.html`, `templates/ifo/room_detail.html`, `templates/reports/scorecard.html`
- Modify: `scheduling/reporting.py:420` and its two callers (lines ~539 and ~712)
- Test: `web/tests_design_system.py::DeskDataTests`, `scheduling/tests_reporting.py::FacultyNameFallbackTests`

**Interfaces:**
- `_name(first: str, last: str, username: str = "") -> str` returns `"first last".strip()`, or `username` when that is empty. Callers pass `r["faculty__username"]` (add it to the `.values()` list) and `faculty.username`.

- [ ] **Step 1: Write the failing tests**

```python
# scheduling/tests_reporting.py
class FacultyNameFallbackTests(SimpleTestCase):
    def test_blank_names_fall_back_to_username(self):
        from scheduling.reporting import _name
        self.assertEqual(_name("", "", "jdelacruz"), "jdelacruz")
        self.assertEqual(_name("Ana", "Reyes", "areyes"), "Ana Reyes")

# web/tests_design_system.py
class DeskDataTests(TestCase):
    def test_stacked_rows_carry_labels(self):
        # HR attendance with one seeded session row (reuse the HR fixtures in web/tests.py)
        body = ...  # GET /hr/attendance as HR admin
        self.assertIn('class="tbl tbl--stack"', body)
        for label in ("Faculty", "Course", "Date", "Scheduled", "Actual", "Status"):
            self.assertIn(f'data-label="{label}"', body)

    def test_filters_use_the_shared_filterbar(self):
        for role, path in ((Role.HR_ADMIN, "/hr/attendance"), (Role.IFO_ADMIN, "/ifo/dashboard"),
                           (Role.DEAN, "/dean/reports")):
            ...  # GET as role
            self.assertIn('class="ui-filterbar"', body)

    def test_every_desk_page_uses_shadcn_page_anatomy(self):
        # one row per desk url_name in the Task 1 route list (all IFO, Dean, HR, Sys pages)
        for role, path in DESK_ROUTES:
            ...  # GET as role, follow=True
            self.assertIn('class="ui-pagehead', body, path)
            self.assertNotRegex(body, r'class="[^"]*\bft-', path)   # no floor vocabulary on desk

    def test_ifo_kpis_use_equal_height_stats(self):
        ...  # GET /ifo/dashboard as IFO admin
        self.assertIn('class="ui-stats"', body)
        self.assertGreaterEqual(body.count('class="ui-stat"'), 4)
```

Fill in each `...` with the existing fixture helpers. Before writing new ones, read how `web/tests.py` seeds HR and IFO reporting pages.

- [ ] **Step 2:** Run them. Expected: FAIL (`_name` takes 2 args; no `tbl--stack`).
- [ ] **Step 3:** Implement:
  - `_name` fallback.
  - **Desk sweep** (every IFO, Dean, HR and Sys template):
    - Each page opens with `.ui-pagehead`, so the console bar title and the page title no longer compete. The bar keeps the short title, and `ui-pagehead__desc` carries the one-line description that today sits loose under the bar.
    - Status text uses `uk-badge` variants.
    - "Nothing here" blocks use `.ui-empty`.
    - Forms use `.ui-field`.
    - Hand-rolled utility rows (for example `web/home.html`) become shadcn Item or Card rows.
  - Every listed table: `class="tbl tbl--stack"` plus `data-label` on each `td`.
  - Every GET filter form: `.ui-filterbar`. Keep the field names and the Apply/Reset/Export links; add an "n active" count from the existing `filters` context.
  - IFO KPI row: `.ui-stats`, with one `.ui-stat` per figure. The occupancy explanation moves out of the card into a single `.ui-stat__note` line plus a "How this is counted" `<details>` under the row. Keep every number and sentence (tests assert "reclaimable as bookable slots" and "Reclaimable h"; grep `web/tests_ifo_utilization.py` and `web/tests_ifo*` for others before moving any copy).
- [ ] **Step 4:** Run `web.tests_design_system.DeskDataTests scheduling.tests_reporting web.tests_ifo_utilization web.tests`. Expected: PASS. Browser at 360px: HR attendance rows are labelled cards and there is no page overflow (`scrollWidth == innerWidth`).
- [ ] **Step 5:** Commit with the message `feat(ui): stacked tables, shared filter bar, calmer IFO KPIs; fix blank faculty name`.

### Task 10: Checker flag flow, one decision at a time

**Files:**
- Modify: `templates/checker/_outcome.html` (the "session found" branch: lines ~120-156 on 2026-11-08), `static/faculty/faculty.css` (`.ft-decide`)
- Test: `verification/tests.py` or `web/tests_design_system.py::CheckerDecisionTests`. Put it where the checker outcome tests already live: run `grep -rn "flag_identity_mismatch" */tests*.py` first.

**Interfaces:**
- One `<form class="ft-outcome__form ft-decide" hx-post="/checker/action" hx-target="#outcome" hx-swap="innerHTML">` holding `room_id` and `session_id` (hidden), radio `name="action"` with values `flag_identity_mismatch` and `flag_not_present` (the first checked by default), one `<textarea name="note" required maxlength="255">`, and one `ft-btn-danger` "Send flag". It sits inside `<details class="ft-decide__problem"><summary>Report a problem</summary>`.
- The "Verify present" form is unchanged (`action=verified`).
- With JS off, `<details>` still opens natively, so nothing needs JS.

- [ ] **Step 1:** Read `/checker/action` (`grep -n "def action" web/checker.py`) and confirm that it reads `action` and `note` from POST and does not need two distinct forms. If it routes on anything else (a different URL, a field name), stop and report: that would be a product change.
- [ ] **Step 2: Write the failing tests**

```python
def test_flag_form_posts_one_action_with_one_note(self):
    body = ...  # render the checker outcome for an active session (reuse the existing checker scan fixture)
    self.assertEqual(body.count("<textarea"), 1)
    self.assertIn('value="flag_identity_mismatch"', body)
    self.assertIn('value="flag_not_present"', body)
    self.assertIn('<summary', body)
    self.assertIn("Report a problem", body)

def test_flag_not_present_still_posts_through_the_merged_form(self):
    resp = self.client.post("/checker/action", {"action": "flag_not_present",
        "room_id": room.id, "session_id": session.id, "note": "Room empty at 10:40"},
        HTTP_HX_REQUEST="true")
    self.assertEqual(resp.status_code, 200)
    self.assertContains(resp, "Flag sent")
```

- [ ] **Step 3:** Run them. Expected: the first FAILS (two textareas). The second should already PASS; it proves the contract did not move. If it fails, stop.
- [ ] **Step 4:** Implement the merged form and `.ft-decide` styling (radio choices as two 44px tappable rows with the `.ft-choice` look).
- [ ] **Step 5:** Run the checker test modules plus `web.tests_ux_finish`. Expected: PASS. Browser at 390px: verify a session, then report a problem with each reason. With JS disabled, the form still submits (it falls back to a full POST if `hx-post` does not fire; confirm what the view returns for a non-htmx POST and note it). Offline mode: the queued-flag path in `offline_queue.js` still finds its hooks. Run `grep -n "data-offline" templates/checker/*.html static/checker/offline_queue.js` before and after; the counts must match.
- [ ] **Step 6:** Commit with the message `feat(checker): one-decision flag flow (same actions, one note)`.

### Task 11: Styled offline capture page

**Files:**
- Modify: `templates/checker/offline.html` (standalone; keep it self-contained because the service worker caches it, and open item L2 is about its script caching)
- Test: `web/tests_design_system.py::OfflinePageTests`

- [ ] **Step 1: Write the failing tests**

```python
class OfflinePageTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def test_offline_page_keeps_every_hook(self):
        html = (self.root / "templates/checker/offline.html").read_text("utf-8")
        for hook in ('id="capture"', 'id="payload"', 'id="action"', 'id="note"',
                     'id="status"', 'id="account-label"', 'id="offline-banner"',
                     'id="offline-banner-text"', "checker/offline_queue.js",
                     'value="verified"', 'value="verified_empty"', 'value="flag_not_present"'):
            self.assertIn(hook, html)

    def test_offline_page_uses_brand_tokens_and_touch_sizes(self):
        html = (self.root / "templates/checker/offline.html").read_text("utf-8")
        self.assertIn("#001c43", html)
        self.assertIn("min-height: 44px", html)
        self.assertIn("mmcm-crest.png", html)
```

- [ ] **Step 2:** Run them. Expected: the first PASSES (it pins today's hooks) and the second FAILS.
- [ ] **Step 3:** Restyle with an inline `<style>` that copies the needed token values (navy app bar with crest, white sheet, `.ft-control`-like inputs, the three observation choices as radio rows **with the `select#action` kept**, visually replaced by the radio rows that set it; or keep the select styled, whichever keeps `offline_queue.js` untouched). Check whether the crest is in the service worker's precache list (`grep -n "precache\|CACHE" static/**/sw*.js templates/**/sw*`). If it is not, inline the crest as a data URI rather than editing the SW (that change belongs to L2).
- [ ] **Step 4:** Run the tests. Expected: PASS. Browser: open `/checker/offline` with the network set to offline after a warm load. It renders styled, and saving an observation shows "Saved on this device".
- [ ] **Step 5:** Commit with the message `feat(checker): styled offline capture page`.

### Task 12: Plain-language copy (no requirement codes on screen)

**Files:**
- Modify: every template whose **rendered** text contains a requirement code. From the grep, these are the visible lines in `hr/attendance.html:15`, `ifo/dashboard.html:11`, `sys/jobs.html`, `dean/dashboard.html`, `dean/queue.html` and `dean/reports.html`. Confirm with the test, because most matches are inside `{% comment %}` and never render.
- Test: `web/tests_design_system.py::PlainCopyTests`

- [ ] **Step 1: Write the failing test**

```python
CODE = re.compile(r"\b(HR|SYS|IFO|DEAN|MOD|GRD|CHK|FAC|NOTIF|CR)-\d{2}\b|\(D-\d{2}\)")

class PlainCopyTests(TestCase):
    PAGES = [(Role.HR_ADMIN, "/hr/attendance"), (Role.SYSTEM_ADMIN, "/sys/jobs"),
             (Role.IFO_ADMIN, "/ifo/dashboard"), (Role.IFO_ADMIN, "/ifo/rooms"),
             (Role.DEAN, "/dean/dashboard"), (Role.DEAN, "/dean/requests"),
             (Role.DEAN, "/dean/reports"), (Role.FACULTY, "/faculty/home"),
             (Role.CHECKER, "/checker/floor"), (Role.GUARD, "/guard/monitor")]

    def test_no_requirement_codes_in_rendered_pages(self):
        for role, path in self.PAGES:
            ...  # login as role, GET path follow=True
            visible = re.sub(r"<!--.*?-->|<script.*?</script>", "", body, flags=re.S)
            self.assertIsNone(CODE.search(visible), f"{path}: {CODE.search(visible)}")
```

- [ ] **Step 2:** Run it. Expected: FAIL, naming HR-01.
- [ ] **Step 3:** Rewrite each visible line in plain words. For example, "Verified session records across all departments. Filter and export for payroll. Read-only." Run `grep -rn "<the old sentence>" */tests*.py` before changing a sentence; if a test asserts it, keep the test's key phrase.
- [ ] **Step 4:** Run `web.tests_design_system.PlainCopyTests` plus the touched apps' suites. Expected: PASS.
- [ ] **Step 5:** Commit with the message `fix(copy): plain language instead of requirement codes`.

### Task 13: IFO term lifecycle step tracker

**Files:**
- Modify: `templates/ifo/terms.html`, `templates/ifo/term_detail.html`, the view that renders them (`grep -n "def term" web/ifo*.py`)
- Test: `web/tests_design_system.py::TermStepsTests`

**Interfaces:**
- `term_steps(term) -> list[dict(key, label, state, href)]` lives next to the term views. The keys are `create`, `import`, `check`, `activate`, `close`, and `state` is one of `done`, `current` or `todo`. It is derived only from data that already exists: `Term.status` (DRAFT/ACTIVE/ARCHIVED) and whether the term has any `Schedule` rows (`term.schedules.exists()`, or the real related name; read `scheduling/models.py` first). Rules:
  - DRAFT with no schedules: create done, import current.
  - DRAFT with schedules: import done, check current. The href is the existing preflight/activate page (`ifo/term_action.html`).
  - ACTIVE: create, import, check and activate done; close current.
  - ARCHIVED: all done.
- These states are display-only. They must not gate any action that is reachable today.

- [ ] **Step 1: Write the failing tests**

```python
class TermStepsTests(TestCase):
    def test_draft_without_schedules_points_to_import(self):
        steps = term_steps(draft_term)
        self.assertEqual([s["state"] for s in steps], ["done", "current", "todo", "todo", "todo"])

    def test_active_term_points_to_close(self):
        self.assertEqual([s["state"] for s in term_steps(active_term)],
                         ["done", "done", "done", "done", "current"])

    def test_term_detail_renders_the_tracker(self):
        ...  # GET term detail as IFO admin
        self.assertIn('class="ui-steps"', body)
        self.assertIn('aria-current="step"', body)
```

- [ ] **Step 2:** Run them. Expected: FAIL (ImportError on `term_steps`; that alone does not count as the real failure, so write the stub that returns `[]` and re-run to see the assertion failure).
- [ ] **Step 3:** Implement `term_steps` and render `.ui-steps` at the top of both pages. The current step's label links to its page.
- [ ] **Step 4:** Run `web.tests_design_system.TermStepsTests scheduling.tests_term_lifecycle web.tests_ifo_ops`. Expected: PASS.
- [ ] **Step 5:** Commit with the message `feat(ifo): term lifecycle step tracker`.

### Task 14: Django admin in MMCM colours

**Files:**
- Create: `templates/admin/base_site.html` (`{% extends "admin/base.html" %}`; override `branding` with the crest and "FluxTrack administration"; override `extrastyle` to set Django admin's CSS variables: `--primary: #001c43; --secondary: #0a1f44; --header-bg: #001c43; --link-fg: #1c3a86; --button-bg: #001c43; --default-button-bg: #0a1f44; --delete-button-bg: #ba1a1a`)
- Test: `web/tests_design_system.py::AdminBrandTests`

- [ ] **Step 1: Write the failing test.** GET `/admin/` as a superuser; assert `"mmcm-crest.png"` and `"--header-bg: #001c43"` are in the body.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. Confirm that `TEMPLATES["DIRS"]` includes `templates/` and that the project template wins over `django.contrib.admin`'s.
- [ ] **Step 4:** Run it. Expected: PASS. Browser: `/admin/` and a user change page at 1440px.
- [ ] **Step 5:** Commit with the message `feat(admin): MMCM branding on Django admin`.

### Task 15: Pagination on every long list (user request, 2026-11-08)

The user asked: "Make sure to add paginations". Many lists already use the shared 50-row pager (D10: `web/pagination.py::paginate` plus `templates/_pager.html`). This task finds every list that can grow past one screen and has no pager, and adds that same pager. It does not build a second pager.

**Files:**
- Modify: the views and templates found by the inventory in Step 1
- Modify: `templates/_pager.html` and `app.css` `.pgr` (shadcn Pagination anatomy: ghost 36px page buttons, the active page as an outline button, Previous/Next with labels from 640px up, 44px targets below 640px)
- Test: `web/tests_design_system.py::PaginationTests`

**Interfaces:**
- Consumes: `paginate(request, object_list, per_page=50, param="page") -> dict` (page, paginator, page_range, querystring, page_param). Read `web/pagination.py` first; do not change its signature.
- Rule: one pager per list, 50 rows per page (D10). Lists that are live boards and poll with htmx (Checker floor, Guard monitor, IFO room board) keep their page number in the poll URL so a refresh does not jump back to page 1.

- [ ] **Step 1:** Inventory. For every desk and floor list template, record the row source, whether it is bounded (for example, today's six classes is bounded), and whether it already includes `_pager.html`. Write the table into the ledger.
- [ ] **Step 2: Write the failing tests:** seed 51 rows for each unbounded list without a pager, GET the page, and assert that `aria-label="Pagination"` and "Showing 1" are present and that row 51 is not on page 1; then GET `?page=2` and assert that row 51 is present.
- [ ] **Step 3:** Run them. Expected: FAIL for each list that has no pager.
- [ ] **Step 4:** Add `paginate()` in each view and include `_pager.html` under each list. For polled lists, pass the page through the `hx-get` URL. Restyle the pager to shadcn Pagination.
- [ ] **Step 5:** Run `web.tests_design_system.PaginationTests` plus every touched app's tests. Expected: PASS. Browser at 390px and 1440px on two paged lists, including one live board after two polls.

### Task 16: Final verification and the design document

**Files:**
- Create: `docs/DESIGN.md`. Write it from what shipped: tokens, ladder, components, shells, do/don't, and the gotchas from Global Constraints.
- Modify: `docs/ui-audit/2026-11-08-baseline.md` (add an "After" column)

- [ ] **Step 1:** `collectstatic`. Rerun `probe.py --label after` on the throwaway DB at all five widths. Expected: `overflow_px == 0` and `console_errors == 0` on every row, and `headers == 1` on every page except the login. Read every changed screenshot by eye, and fix and re-run anything off.
- [ ] **Step 2:** Back up `FluxTrack_SRS.docx`. Run the full suite at the real clock and with the clock frozen at 00:10, 07:00 and 23:50 (each frozen time **before** the real time). Expected: all pass, apart from the three known dev-login failures. Restore the SRS.
- [ ] **Step 3:** Prove two new tests can fail. Temporarily revert the `_name` fallback and the Checker merged form, confirm `FacultyNameFallbackTests` and `test_flag_form_posts_one_action_with_one_note` go red, then restore both.
- [ ] **Step 4:** Do the human-eye checks from open items while the browser is up: the heat grid in greyscale and in print preview, and print preview of the scorecard and room timetable.
- [ ] **Step 5:** Drop the throwaway DB and stop the server. Compare the dev DB key counts with the baseline taken in Task 1.
- [ ] **Step 6:** Write `docs/DESIGN.md` and fill in the audit's After column. Commit with the message `docs: DESIGN.md and before/after UI audit`.
- [ ] **Step 7:** Report to the user in plain language: what changed per role, the before/after audit numbers, which old-design tests changed and why, what was not tested (real phone, QR camera, real offline), and anything left over. Offer to retake the Figma journey screens.

---

## Self-review notes

- **Spec coverage:**
  - Responsive: Tasks 2, 6, 7, 9 and 15.
- shadcn fidelity: Tasks 2, 3 (components to spec, side-by-side with the shadcn docs), 6 (Sidebar and Sheet), 8 (floor family on shadcn anatomy), and the no-raw-colours test.
  - One system: Tasks 2, 3, 4 and 5.
  - Mapúa feel: Tasks 2, 4 (crest in every shell), 8 (navy floor hero) and 14.
  - Friendlier processes: Tasks 9, 10, 11, 12 and 13.
  - Keep colours: tokens are unchanged in value, only extended.
  - Keep some layouts: both shells stay, and the login stays.
  - "Map the codebase": done in the spec section, and measured in Task 1.
- **Not covered, on purpose:** Faculty request wizard and room board internals (already redesigned in July; they inherit tokens and components only). Login (non-goal). Dark mode.
- **Risk to watch:** Task 5 touches the most shared code (context processor plus shared pages). Run it after Task 4 and before the page tasks, and run the full `web` suite at its end, not just the listed modules.
