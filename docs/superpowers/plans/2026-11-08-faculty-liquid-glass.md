# Faculty Liquid Glass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle every Faculty screen in Apple's Liquid Glass style (direction A, Frosted light), with a floating glass tab bar, a separate glass Scan button, native-feeling motion, and a top-centre bar on tablets and computers. Checker, Guard and office screens must not change.

**Architecture:**
- `base.html` marks Faculty pages with `html.ft-glass` and loads two new files only for them: `static/faculty/glass.css` and `static/faculty/glass.js`.
- `glass.css` restyles the existing floor classes (`.ft-top`, `.ft-page`, `.ft-greet`, `.ft-hero`, `.ft-tabbar` and so on). Every rule in it is scoped under `html.ft-glass`, so `faculty.css` stays as it is for Checker and Guard.
- Motion comes from the browser's cross-page View Transitions plus one small script for scroll behaviour.

**Tech Stack:** Django 6 templates, Franken UI 2.1.2 (vendored, no build step), htmx 2.0.6, plain CSS and JS, Whitenoise (`collectstatic` after CSS/JS edits).

**Spec:** `docs/superpowers/specs/2026-11-08-faculty-liquid-glass-design.md`. Mockup: `.superpowers/brainstorm/2879-1794151893/content/liquid-glass-home.html` (direction A).

## Global Constraints

- **Scope:** Faculty only. Checker, Guard and office screens must render pixel-identical to before.
- **No behaviour changes:** keep every id, `name`, `hx-*`, `data-*` and form field on Faculty pages. Markup changes are limited to what each task names.
- **Colours:** no raw colours (`#hex`, `rgb()`, `rgba()`) outside `static/css/tokens.css`. Glass values are new tokens there, read as `hsl(var(--token) / alpha)`.
- **Breakpoints:** every `@media` width is on the existing ladder (640/768/1024/1280, 40/48/64/80rem, "below" written as `X - 0.02px`).
- **Contrast:** body text at least 4.5:1 against the glass it sits on, composited over the worst-case backdrop.
- **Motion:** none under `prefers-reduced-motion: reduce`. Under `prefers-reduced-transparency: reduce`, or where `backdrop-filter` is unsupported, glass becomes a solid surface.
- **Touch targets:** at least `var(--touch)` (44px). On 360px wide screens, nothing scrolls sideways.
- **Keep the old test strings:** the pinned strings in `faculty.css` stay (`FloorShadcnTests.test_pinned_strings_survive`). Never weaken a test. If an old test fails, decide whether it encoded old design or the change is wrong, and report which.
- **Process:**
  - Failing test first; watch it fail for the right reason.
  - Finish each task with its tests, and finish the plan with the full suite run at the real clock and at a frozen 00:10, 07:00 and 23:50.
  - Back up `FluxTrack_SRS.docx` before full runs and restore it after.
- **Browser checks:** only through the gstack `/browse` skill, only against the throwaway `fluxtrack_demo` copy (dates already shifted 16 weeks). For live states, use the demo clock at Tue 2026-11-10 13:05 Manila. The demo clock script in the scratchpad points at that copy only.
- **Commits:** none unless the user says so. Stage only. The previous redesign is still staged and uncommitted; leave `.planning/STATE.md` alone.
- **Copy:** plain words, no requirement codes on screen. Visible tab labels on phones are the short forms "Home", "Schedule", "Online", "Attendance", "Requests". The `aria-label`s keep their full names.

## Review Focus

1. **360px phone:** five labelled tabs plus the Scan button must fit without clipping or sideways scroll (Task 4 probe at 360).
2. **No blur available** (older Android, Firefox without the flag) **or reduced transparency set:** every glass surface falls back to solid and stays readable (Task 1 static test, Task 4 browser check with `backdrop-filter` disabled).
3. **htmx partial swaps on Faculty pages must not break:** the modality form's 400 swap, online start/checkout and photo status. They must neither trigger a whole-page transition nor land under the glass bar (Task 5 real submit of an invalid request form).
4. **A merged-section hero with a long section list** (`itBriones`, Tue 10:45, A161 + A182) wraps inside the glass card with no overflow (Task 5 check at 360).
5. **The account menu and the notification popover** open above the glass top bar and the tab bar, with a visible keyboard focus ring on glass (Task 5 real click and Tab check).

---

### Task 1: Glass shell wiring, tokens and contract

**Files:**
- Modify: `templates/base.html` (the html class, the head links, the Faculty `nav.ft-tabbar` block at lines 167-191, and the body script)
- Modify: `static/css/tokens.css` (new glass tokens in the `:root, html.uk-theme-neutral` block)
- Create: `static/faculty/glass.css`, `static/faculty/glass.js`
- Test: `web/tests_faculty_glass.py` (new). Also add `static/faculty/glass.css` to `TokenContractTests.CSS` and `ComponentSheetTests.RAW_COLOUR_FILES` in `web/tests_design_system.py`.

**Interfaces:**
- Produces:
  - **html class:** `<html class="... ft-glass">` when `user.is_authenticated and user.role == "faculty"`; nothing for other roles.
  - **Loaded only on Faculty pages:** `<link rel="stylesheet" href="{% static 'faculty/glass.css' %}">` after `faculty.css`, and `<script src="{% static 'faculty/glass.js' %}" defer>`.
  - **Scan button:** inside the Faculty `nav.ft-tabbar`, after `.ft-tabbar__row`: `<a href="/faculty/scan" class="ft-scanbtn" aria-label="Scan room QR"><uk-icon icon="qr-code"></uk-icon></a>`.
  - **Short labels:** each Faculty `.ft-tab` gets `<span class="ft-tab__short">` holding the short label. The existing `ft-tab__label` and `aria-label` stay.
  - **Tokens:** `--glass-fill`, `--glass-edge` (HSL triplets); `--glass-alpha: 0.62`, `--glass-strong-alpha: 0.86`, `--glass-hero-alpha: 0.9` (numbers); `--glass-blur: 22px`; `--glow-navy`, `--glow-red`, `--glow-blue` (HSL triplets); `--font-ios: -apple-system, BlinkMacSystemFont, "SF Pro Text", var(--font-sans)`.

- [ ] **Step 1: Write the failing tests** in `web/tests_faculty_glass.py`:
  - `GlassShellTests(TestCase)`:
    - `test_faculty_pages_load_the_glass_layer`: log in a `Role.FACULTY` user, GET `/faculty/home`. Assert `ft-glass` in the `<html` tag, `faculty/glass.css` and `faculty/glass.js` present.
    - `test_other_floor_roles_do_not`: a `Role.CHECKER` user on `/checker/floor` and a `Role.GUARD` user on `/guard/monitor`. Assert none of `ft-glass`, `glass.css`, `glass.js` appear.
    - `test_scan_button_sits_beside_the_tab_bar`: for each of `/faculty/home`, `/faculty/schedule`, `/faculty/online`, `/faculty/history`, `/faculty/modality/mine`, assert `class="ft-scanbtn"`, `href="/faculty/scan"` and `aria-label="Scan room QR"` are inside the Faculty nav.
    - `test_short_labels_keep_full_names_for_screen_readers`: assert the five `ft-tab__short` texts and the unchanged `aria-label="My attendance"` and `aria-label="Online classes"`.
  - `GlassContractTests(SimpleTestCase)`:
    - `test_every_rule_is_scoped_to_faculty`: strip comments. Take every selector before `{` that is not an at-rule or a keyframe step (`from`, `to`, `N%`), split on commas, and assert each starts with `html.ft-glass`.
    - `test_motion_and_transparency_fallbacks`: assert these are present:
      - `@view-transition`;
      - a `@media (prefers-reduced-motion: reduce)` block containing `navigation: none` and `animation: none`;
      - `@media (prefers-reduced-transparency: reduce)`;
      - `@supports not ((backdrop-filter:`, written so it accepts the `-webkit-` form too.
    - `test_glass_text_clears_aa`: composite each surface, then check the text on it with the existing `contrast` maths (add an `_rgb` / `_composite(fg_hsl, alpha, bg_rgb)` helper in the test module).
      - `--primary` at `--glass-hero-alpha` over white: `--primary-foreground` at full strength, and at 0.78, must clear 4.5.
      - `--glass-fill` at `--glass-strong-alpha` over `--glow-navy` at 35% on `--background`: `--foreground` and `--muted-foreground` must clear 4.5.
- [ ] **Step 2: Run** `C:/Users/joshu_mnu8z3u/AppData/Local/Programs/Python/Python312/python.exe manage.py test web.tests_faculty_glass web.tests_design_system`. Expected: the new tests FAIL because the markers, files and tokens are missing (not import errors). Old tests pass.
- [ ] **Step 3: Implement the wiring.**
  - Add the tokens.
  - Create `glass.css` with only the scoped skeleton:
    - `@view-transition { navigation: auto; }`;
    - the reduced-motion block (`@view-transition { navigation: none; }` and `html.ft-glass *, html.ft-glass *::before, html.ft-glass *::after { animation: none !important; transition: none !important; }`);
    - the solid fallbacks, which swap glass for `hsl(var(--card))` with no blur.
  - Create an empty-but-valid `glass.js` (an IIFE that returns when `!document.documentElement.classList.contains('ft-glass')`).
  - Add the base.html markup listed under Produces.
- [ ] **Step 4: Run** the same command. Expected: PASS, and the old design-system tests still pass.
- [ ] **Step 5: Baseline shots before any visual change.** On the demo copy, use `/browse` to screenshot `/checker/floor`, `/checker/online`, `/guard/monitor` and `/guard/locate` at 390 and 1440. Save them to the scratchpad as `before-<role>-<page>-<w>.png`. Task 6 compares against these.
- [ ] **Step 6: Stage** the changed files (no commit).

### Task 2: The look on phones (direction A)

**Files:**
- Modify: `static/faculty/glass.css`
- Test: `web/tests_faculty_glass.py` (`GlassLookTests`)

**Interfaces:**
- Consumes: the Task 1 tokens and `html.ft-glass`.
- Produces these state classes, which Task 3's script toggles:
  - `.ft-top.is-scrolled`: compact glass top bar;
  - `.ft-tabbar.is-compact`: shrunk tab bar;
  - `.ft-tab.is-active` (already exists).

- [ ] **Step 1: Write the failing tests** in `GlassLookTests(SimpleTestCase)`:
  - `test_backdrop_uses_the_glow_tokens`: `html.ft-glass body` (or `.ft-app`) background reads `--glow-navy`, `--glow-red` and `--glow-blue` in radial gradients.
  - `test_floating_tab_bar_and_scan_button`:
    - `html.ft-glass .ft-tabbar` is `position: fixed`, has a `border-radius` of `999px`, and uses `backdrop-filter`;
    - `.ft-scanbtn` is a circle at least `var(--touch)` wide;
    - `.ft-tab__label` is hidden and `.ft-tab__short` is shown under `html.ft-glass`.
  - `test_hero_is_navy_glass`: `html.ft-glass .ft-hero` background reads `--primary` and `--glass-hero-alpha`.
  - `test_pages_clear_the_floating_bar`: `html.ft-glass body:has(.ft-tabbar) .ft-page` has a `padding-bottom` with `calc(` and `env(safe-area-inset-bottom`.
  - `test_font_is_the_system_stack`: `html.ft-glass body` sets `font-family: var(--font-ios)`.
- [ ] **Step 2: Run** `... manage.py test web.tests_faculty_glass`. Expected: the GlassLookTests FAIL on the missing rules.
- [ ] **Step 3: Implement direction A** in `glass.css`, matching the mockup: backdrop glows, frosted cards and lists (`--glass-strong-alpha` for dense lists), the navy glass hero with a rim highlight, the large-title greeting, the floating capsule tab bar with the active-tab glass lens, the round Scan button beside it, chips and pills, press-in `:active { transform: scale(.97) }`, and the `is-scrolled` and `is-compact` states. Radii read `--radius*` tokens or `999px`/`50%` only (`test_floor_radius_reads_the_shared_ladder` must stay green for `faculty.css`).
- [ ] **Step 4: Run** the faculty glass tests plus `web.tests_design_system`. Expected: PASS.
- [ ] **Step 5: Look at it.** Run `collectstatic`, start the demo server with the demo clock (Tue 13:05), sign in as `rafernandez` with `/browse` at 390px, and screenshot Home. Compare by eye with mockup A. Write down the differences, and fix any that a person would notice.
- [ ] **Step 6: Stage.**

### Task 3: Motion

**Files:**
- Modify: `static/faculty/glass.js`, `static/faculty/glass.css`, `templates/faculty/modality_new.html` (add the class `ft-sheet-page` to its outer `.ft-app` only)
- Test: `web/tests_faculty_glass.py` (`GlassMotionTests`)

**Interfaces:**
- Consumes: the Task 2 state classes.
- Produces: `glass.js` behaviour.
  - Adds `.is-scrolled` to `.ft-top` when `scrollY > 8` and removes it at the top.
  - Adds `.is-compact` to `.ft-tabbar` when scrolling down past 64px, and removes it on any upward scroll or within 48px of the page bottom.
  - Uses one passive scroll listener, throttled with `requestAnimationFrame`.

- [ ] **Step 1: Write the failing tests** in `GlassMotionTests(SimpleTestCase)`:
  - `test_active_tab_morphs_between_pages`: `html.ft-glass .ft-tab.is-active` sets `view-transition-name: ft-active-tab`, and `::view-transition-group(ft-active-tab)` has a spring-like `animation-timing-function` (any `cubic-bezier`).
  - `test_scroll_states_are_driven_by_one_listener`: `glass.js` contains `passive: true`, `requestAnimationFrame`, `is-scrolled` and `is-compact`, and no `setInterval`.
  - `test_request_form_rises_like_a_sheet`: `html.ft-glass .ft-sheet-page` has an `animation` whose `@keyframes` starts with `translateY(`. `modality_new.html` carries `ft-sheet-page`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Write `glass.js` to the Produces behaviour.
  - Add the view-transition names and keyframes: page content slides 12px with a fade; the tab lens morphs; the sheet rises.
  - Give the top bar a `view-transition-name: ft-top` so it stays still while the page under it changes.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Do the real gestures** in `/browse` at 390px on the demo copy, comparing screenshots before and after each gesture:
  - scroll the Home page with the mouse wheel down 400px, then up 100px;
  - tap Schedule, then Home;
  - open "Request a modality change".
  - Then emulate `prefers-reduced-motion: reduce` and confirm nothing animates (the classes still toggle).
- [ ] **Step 6: Stage.**

### Task 4: Responsive (tablet, computer, small phone)

**Files:**
- Modify: `static/faculty/glass.css`
- Test: `web/tests_faculty_glass.py` (`GlassResponsiveTests`)

- [ ] **Step 1: Write the failing tests** in `GlassResponsiveTests(SimpleTestCase)`:
  - `test_bar_floats_top_centre_from_48rem`: inside `@media (min-width: 48rem)`, `html.ft-glass .ft-tabbar` sets `top:` and `bottom: auto`, and `.ft-page` gets a top padding that reads `--tabbar-h`.
  - `test_side_rail_is_overridden_for_faculty`: `faculty.css` turns the tab bar into a side rail at 64rem. That block sets these properties (checked in code on 2026-11-08):
    - `.ft-tabbar`: `left`, `right`, `top`, `bottom`, `width`, `padding`, `background` and `backdrop-filter`;
    - `.ft-tabbar__row`: `flex-direction: column`;
    - `body:has(.ft-tabbar) .ft-page`: `padding-left: 15rem`.

    Assert that, inside `@media (min-width: 64rem)`, `glass.css` has `html.ft-glass` rules overriding `.ft-tabbar` `width`, `left` and `background`, `.ft-tabbar__row` `flex-direction` and the `.ft-page` `padding-left`.
  - `test_home_two_columns_from_64rem`: `html.ft-glass .ft-home-grid` has `grid-template-columns` inside `@media (min-width: 64rem)`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement the layouts.**
  - From 48rem: the glass bar floats at the top centre with the Scan button attached; the top bar keeps the brand on the left and the actions on the right.
  - From 64rem: Home is two columns (check-in card beside today's classes).
  - Below 390px: tabs tighten (smaller gap, 11px labels) so all five plus Scan fit at 360.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Probe.** Reuse the earlier audit probe (`probe.py` in the previous session's scratchpad, or rewrite it: `scrollWidth - clientWidth`, and elements past the right edge). Run it on the demo copy for every Faculty route at 360, 390, 768, 1024 and 1440. Expected: 0 overflow everywhere. Repeat 390 with `backdrop-filter` disabled through `/browse` JS (`document.documentElement.style.setProperty` will not do it; inject a `<style>` that sets `backdrop-filter: none !important`). Then check by eye that the text is readable on the solid fallback.
- [ ] **Step 6: Stage.**

### Task 5: Every Faculty screen

**Files:**
- Modify: `static/faculty/glass.css`. Templates only where a screen has no hook to style. Each such change adds a class and nothing else; record it in the ledger.
- Test: `web/tests_faculty_glass.py` (`GlassScreensTests`)

- [ ] **Step 1: Write the failing test** `GlassScreensTests(TestCase).test_every_faculty_screen_is_in_the_glass_shell`.
  - Routes: `/faculty/home`, `/faculty/schedule`, `/faculty/online`, `/faculty/history`, `/faculty/modality/mine`, `/faculty/modality/new`, `/faculty/scan`, `/faculty/profile`, `/notifications`.
  - For each, as a faculty user: status 200, `ft-glass` on `<html`, exactly one `<header`, and `glass.css` loaded.
  - Add a second test, `test_screens_have_glass_rules`. It asserts that `glass.css` has a scoped rule for each screen's distinctive class: read each template, list its `ft-*` classes, and assert each appears in `glass.css` or in an allow-list of purely structural classes kept in the test.
- [ ] **Step 2: Run** it. Expected: the second test FAILS, listing the unstyled classes. If the first fails, find out why before going on: a page that is not in the floor shell for faculty is a finding.
- [ ] **Step 3: Style each screen** to direction A: schedule, scan and its outcome card, online list and online start/checkout, history with its filters and pager, the requests list, the new request form and room picker, profile and photo upload, and the faculty notifications list. Dense content uses `--glass-strong-alpha`.
- [ ] **Step 4: Run** it. Expected: PASS.
- [ ] **Step 5: Do the real gestures on the demo copy** at 390px:
  - each screen once;
  - submit the new request form empty, and confirm the 400 error swaps in visibly and is not hidden under a bar;
  - check in to the online class (Verify & start), then check out;
  - open the account menu and the notification bell, and Tab through them, checking the focus ring is visible;
  - sign in as `itBriones` with the clock at Tue 10:40 to see the merged hero at 360px.
- [ ] **Step 6: Stage.**

### Task 6: Proof, docs and record

**Files:**
- Modify: `docs/DESIGN.md` (new section "Faculty: Liquid Glass"), vault `Decisions/D14 - One shadcn system tailored to MMCM.md` (update), vault `Open items.md`, memory `ui-ux-reboot.md`

- [ ] **Step 1: Check Checker and Guard are unchanged.** Retake the Task 1 Step 5 shots and diff them against the baselines (a pixel diff with Pillow in the scratchpad). Expected: identical, or only live-data differences such as clock text. Explain any other difference.
- [ ] **Step 2: Run the full suite** at the real clock and at a frozen 00:10, 07:00 and 23:50, using the scratchpad's frozen-clock runner pointed at its own test DB. Back up the SRS before and restore it after. Expected: everything passes, with the same skips as before.
- [ ] **Step 3: Prove two tests can fail.**
  - Remove `html.ft-glass` from one `glass.css` rule: `test_every_rule_is_scoped_to_faculty` must fail.
  - Raise `--glass-strong-alpha` to 0.3: `test_glass_text_clears_aa` must fail.
  - Restore both.
- [ ] **Step 4: Write it down.**
  - **DESIGN.md:** the Faculty section (tokens, scoping rule, fallbacks, motion, breakpoints).
  - **D14:** "Office roles follow shadcn; Faculty follows Apple's Liquid Glass (user, 2026-11-08); Checker and Guard to be decided".
  - **Memory:** the status.
- [ ] **Step 5: Stage everything.** Leave the throwaway `fluxtrack_demo` in place for the user's demo; it is theirs to drop.
