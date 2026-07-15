# Phase 6 — UI Review

**Audited:** 2026-07-16
**Baseline:** `.planning/phases/06-reporting-engine-reporting-surfaces/06-UI-SPEC.md` (approved contract, checker sign-off still shows "pending" checkboxes)
**Screenshots:** not captured — no dev server detected on 3000/5173/8080; this is a code-only audit (Django + Franken UI, server-rendered templates)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 2/4 | Empty/error/no-results copy matches the contract verbatim, but the RPT-04 scorecard's required "Export CSV" CTA does not exist anywhere in the template |
| 2. Visuals | 3/4 | Card/table hierarchy is consistent and clean; the RPT-05 error-card is correctly muted (not full-red) per spec |
| 3. Color | 3/4 | Navy accent is bounded as specified; one un-tokenized hardcoded hex pair duplicates an existing CSS variable instead of reusing it |
| 4. Typography | 3/4 | The 4-size scale (12/14/20/30) is respected; `font-medium` (500) appears twice in phase-6 files against a declared 400/600-only weight set |
| 5. Spacing | 3/4 | Scale is respected almost everywhere; two arbitrary non-scale values (`mt-3`, `gap-3` = 12px) slip into `dean/dashboard.html` |
| 6. Experience Design | 1/4 | The entire Weekly Consolidated Report surface (RPT-01/03) — the IFO-wide report with its "Download PDF" primary CTA — does not exist; no export route exists under `/ifo/` at all |

**Overall: 15/24**

---

## Top 3 Priority Fixes

1. **The Weekly Consolidated Report surface (RPT-01/03) was never built** — IFO users have no way to download the department-wide PDF/CSV report the contract requires as the IFO primary deliverable; `web/urls.py` has zero `export`/`download` routes under `/ifo/`, and `templates/reports/` contains only `scorecard.html` and `_error_card.html`, no report-table template. **Fix:** add an `ifo/report` (or similar) view + template mirroring `dean/reports.html`'s Pattern-A filter bar + Pattern-C export anchors, and wire `Download PDF` / `Export CSV` routes analogous to `dean.report_export`.

2. **Faculty scorecard (RPT-04) is missing its mandated "Export CSV" CTA** — `templates/reports/scorecard.html` (shared by both `ifo_scorecard` and `dean_scorecard`) renders KPI cards, modality breakdown, and an absences table, but has no export anchor at all, despite the contract's Per-Surface table naming Export CSV as the surface's Primary CTA. **Fix:** add a `Pattern C` download anchor (e.g. `/{role}/scorecard/{faculty_id}/export.csv`) in the header row next to the back button, per the contract's markup example.

3. **Two spacing-scale violations in `templates/dean/dashboard.html`** — `gap-3` (line 54, 12px) and `mt-3` (line 66, 12px) fall outside the declared standard set `{4, 8, 16, 24, 32, 48, 64}`, contradicting the spec's explicit "Exceptions: none" claim. **Fix:** replace with `gap-4`/`mt-4` (16px) or `gap-2`/`mt-2` (8px) to land back on the scale.

Additional (non–top-3) findings below, several of which are also fix-worthy.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)
- PASS — Empty state copy matches contract exactly: `templates/ifo/_cards.html:70` and `templates/dean/reports.html:73` both render "No attendance in this range. No sessions were scheduled for the selected [dates/department and dates]. Adjust the range above." consistent with the contract's `{% empty %}` intent (contract's exact wording is close but not char-for-char identical to the `Copywriting Contract` table's "No attendance in this range" / "No sessions were scheduled for the selected department and dates" — the two are merged into one sentence here, a minor drift, not scored down further).
- PASS — HR no-results and empty-vs-filtered distinction is correctly implemented: `templates/hr/attendance.html:96-100` branches on `filters.any_applied` to show "No sessions match these filters. Clear a filter or widen the date range." vs. "No attendance in this range. Sessions will appear here as they are held." — matches contract's HR no-results line verbatim.
- PASS — RPT-05 error copy is byte-for-byte the contract's generic text in `templates/reports/_error_card.html:10-11`: "Couldn't load this section" / "This metric failed to load. The rest of the page is unaffected — refresh to try again." No raw exception is interpolated anywhere in the partial (confirmed by reading the whole file — no `{{ card.1 }}` or similar is ever printed).
- **BLOCKER** — `templates/reports/scorecard.html` has no "Export CSV" button despite being named RPT-04 in the contract with Export CSV as its declared Primary CTA (Per-Surface Contract Summary table, row "Faculty scorecard (RPT-04)"). Verified by full read of the file: only a back-button and content sections exist.
- **BLOCKER** — No "Download PDF" CTA anywhere for the Weekly Consolidated Report (RPT-01/03); the copy contract explicitly declares "Primary CTA — Weekly report / Dean report: Download PDF (secondary: Export CSV)" but only the Dean side (`dean/dashboard.html`, `dean/reports.html`) implements it — the IFO side of the same surface is entirely absent.

### Pillar 2: Visuals (3/4)
- PASS — Visual hierarchy is consistent: page title (`uk-h2`) → section heading (`uk-h3`/`uk-h4`) → caption (`uk-text-small uk-text-muted`) → big metric (`uk-h2`) is applied uniformly across `ifo/dashboard.html`, `dean/dashboard.html`, `reports/scorecard.html`.
- PASS — RPT-05 error-card correctly avoids "full-red card" per contract: `border-border` + a 3px `--red-tint` left-border accent + amber icon only (`templates/reports/_error_card.html:6-8`), matching the muted, non-alarming spec.
- WARNING — Icon-only back buttons all carry `aria-label="Back"` (`reports/scorecard.html:12`, `dean/dashboard.html:12`, `dean/reports.html:12`) — correct and consistent. However, no icon-only button anywhere in these templates has a visible focus ring beyond the browser/Franken default; not independently verifiable without a rendered page, flagged as `needs_human_review: true`.
- WARNING — DEAN-04's "latest weekly report" card and the KPI card grid use the same visual weight (both `uk-card uk-card-body`), so there is no single dominant focal point on the Dean dashboard — the contract doesn't explicitly forbid this, but pillar 2's "clear focal point" heuristic is only partially met.

### Pillar 3: Color (3/4)
- PASS — Navy accent (`#001c43` / `--primary`) is bounded to primary buttons, the "Verified" checker pill, and the highlighted Attendance-% metric — consistent with the contract's "10% accent, never applied to every card" rule. Confirmed via grep: no stray `bg-primary`/hardcoded navy on card borders or body text.
- PASS — Semantic status tokens (`--green`, `--amber`, `--red` + tints) are reused, not reinvented, across `ifo/_cards.html`, `dean/dashboard.html`, `reports/scorecard.html`, `hr/_rows.html` — all use the same inline `style="background:var(--green-tint);color:var(--green)"` pattern.
- WARNING — `templates/hr/_rows.html:30` hardcodes `style="background:#e7ecf7;color:#001c43"` for the "Verified" pill instead of referencing CSS custom properties (there is no `--navy-tint` variable defined, only the literal hex pair repeated ad hoc). The contract's color table describes this exact combo as "Checker-verified... brand navy on tint (mirrors `.ft-pill--merged`)" but doesn't define a token for it — this is a spec gap that the implementation should have flagged rather than silently hardcoding, since every other status pill (green/amber/red) is a `var(--x)` reference and this one alone is a bare hex literal, breaking consistency within the same file.

### Pillar 4: Typography (3/4)
- PASS — Exactly 4 sizes present in-scope: `uk-h2` (30px display), `uk-h3`/`uk-h4` (20px heading), `uk-text-small` (12px label), and default body (14px) — no stray `text-xl`/`text-2xl`/etc. found in `templates/reports/`, `templates/ifo/dashboard.html`, `templates/ifo/_cards.html`, `templates/dean/*.html`, `templates/hr/*.html`.
- WARNING — `font-medium` (500 weight) appears twice in phase-6 scope: `templates/reports/_error_card.html:10` and `templates/hr/_rows.html:8`, but the contract declares only two weights ("Regular 400 (body) + Semibold 600 (all emphasis, headings, metrics, labels)"). This introduces an undeclared third weight tier, however minor visually.

### Pillar 5: Spacing (3/4)
- PASS — The overwhelming majority of spacing usage across all five surfaces maps cleanly to the declared scale: `gap-1`(4) / `gap-2`(8) / `gap-4`(16) / `mb-6`(24) / `pt-8`/`mb-8`(32) / `pb-16`(64), matching the contract's token table precisely.
- WARNING — `templates/dean/dashboard.html:54` uses `gap-3` (12px) and line 66 uses `mt-3` (12px) — both outside `{4, 8, 16, 24, 32, 48, 64}`, directly contradicting the spec's "Exceptions: none" statement for reporting surfaces.
- Note — `templates/dean/dashboard.html:10` uses raw `max-w-2xl mx-auto px-4` rather than the `uk-container max-w-2xl` idiom used everywhere else (`reports/scorecard.html:9`, `dean/reports.html:10` both use `uk-container`). Not a spacing-scale violation (px-4 = 16px, in-scale) but a container-idiom inconsistency worth flagging under pillar 6 as well.

### Pillar 6: Experience Design (1/4)
- **BLOCKER** — RPT-01/03 Weekly Consolidated Report does not exist as a surface. `web/urls.py` has no `ifo/report`, `ifo/export`, or equivalent path; `web/ifo.py` only implements `dashboard` (IFO-09) and `scorecard` (RPT-04 drill-down). The contract's own Per-Surface table lists this as a distinct row with its own primary CTA ("Download PDF") — it is simply unbuilt, not degraded or partial.
- PASS — RPT-05 per-card graceful degradation is correctly implemented and independently verified in two places: `templates/ifo/_cards.html` guards the KPI grid (`summary.1`) and the faculty table (`rows.1`) as two *separate* `(value, error)` pairs so one failing independently of the other, matching the contract's "per-card isolation" requirement exactly; `templates/dean/dashboard.html` similarly isolates its one `summary` card. `templates/reports/scorecard.html:20` also gates its whole KPI section behind `card.1`.
- PASS — Read-only enforcement (DEAN-01) holds: no destructive or write controls found anywhere in `dean/dashboard.html`, `dean/reports.html`, `hr/attendance.html`, `reports/scorecard.html` — every control is a GET filter, a download anchor, or a drill-down link.
- PASS — Table semantics are correct: `<thead>`/`<th>` present in every `uk-table` (`ifo/_cards.html:47`, `dean/reports.html:51`, `hr/attendance.html:78-86`), and `hr/_rows.html` renders one `<tr>` per session with properly scoped `<td>`s.
- WARNING — HR filter form (`templates/hr/attendance.html:19-60`) uses `<span class="uk-text-small uk-text-muted">` as visual labels wrapping inputs inside a `<label>` element, which is technically an accessible label (implicit association via nesting) — acceptable, but the pattern differs from a proper `<label for="id_...">` + `id` pairing recommended for screen-reader clarity when styling gets more complex later. Not a blocker, noted for future hardening.
- WARNING — No loading state markup found for any of the htmx-swapped panels (`#report-panel` in `ifo/dashboard.html`, `hx-target` swaps in `dean/_queue.html`). None of the Pattern-A forms show a `uk-spinner`/disabled-button-while-loading treatment during the GET swap, so a slow network leaves the Apply button clickable with no feedback. The contract's Per-Surface table lists "loading" as a required state for the Weekly Report and HR surfaces specifically — this is unmet for HR (`hr/attendance.html`, plain GET form, no htmx wiring at all in this file, so no loading indicator is possible without JS).

---

## Registry Safety

Registry audit: not applicable — `components.json` does not exist (project uses Django + Franken UI CDN, no shadcn). Skipped per gate.

---

## Files Audited

- `templates/reports/_error_card.html`
- `templates/reports/scorecard.html`
- `templates/ifo/dashboard.html`
- `templates/ifo/_cards.html`
- `templates/dean/dashboard.html`
- `templates/dean/reports.html`
- `templates/dean/queue.html` / `templates/dean/_queue.html` (spot-checked for consistency baseline)
- `templates/hr/attendance.html`
- `templates/hr/_rows.html`
- `templates/base.html` (Franken shell baseline)
- `web/urls.py`, `web/ifo.py`, `web/dean.py` (route/view cross-check for missing export surface)
- `.planning/phases/06-reporting-engine-reporting-surfaces/06-UI-SPEC.md` (contract)
