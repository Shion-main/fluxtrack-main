# FluxTrack design system

FluxTrack follows **shadcn/ui** (the classic new-york v4 sizes), **tailored to
MMCM**. Franken UI 2.1.2, which is a shadcn port, supplies most components; the
rest are written to the same anatomy in `static/css/ui.css`. Written from what
shipped on 2026-11-08 (plan: `docs/superpowers/plans/2026-11-08-unified-responsive-ui.md`).

## Where things live

| File | What it owns |
|---|---|
| `static/css/tokens.css` | The only place colours are **set**: shadcn colour roles in MMCM values, radius, shadows, font, touch size, the breakpoint ladder (as a comment). |
| `static/css/app.css` | Utilities: skeleton, skip link, htmx failure alert, `.tbl` table (+ `.tbl--stack`), status pill, pager, missing Tailwind utilities. |
| `static/css/ui.css` | Part A: Franken's shadcn components tuned to spec. Part B: components Franken lacks (`.ui-*`). |
| `static/css/console.css` | The desk console shell (IFO, Dean, HR, SysAdmin) and Dean workspace. |
| `static/faculty/faculty.css` | The floor family (Faculty, Checker, Guard) on shadcn anatomy. |
| `static/css/board.css`, `timetable.css` | IFO rooms board; weekly timetable and print sheets. |

Load order (`templates/base.html`): Franken core, utilities, tokens, app, ui, faculty.

## Colour

Colour roles are HSL triplets read as `hsl(var(--role))`. MMCM values:

| Role | Value | Use |
|---|---|---|
| `--primary` | 215 100% 13% (`#001c43`, MMCM navy) | Main buttons, the floor check-in card, active icons |
| `--destructive` | 357 84% 52% (`#ec1f28`, MMCM red) | Delete, flag, errors |
| `--background` / `--foreground` | white / 222 47% 11% | Page and ink |
| `--muted`, `--secondary`, `--accent` | navy-tinted greys | Quiet surfaces, hover, selection |
| `--border`, `--input`, `--ring` | 220 20% 90%, 220 20% 90%, 215 90% 25% | Hairlines and the 3px focus ring at 50% |
| `--sidebar*` | stock shadcn light sidebar | Desk console sidebar (the user ruled out a navy sidebar) |
| `--success`, `--warning`, `--info` (+ `-muted`) | green, amber, blue | Attendance states only, never decoration |
| `--destructive-text`, `--destructive-muted` | readable red on white, red tint | Error text, absent badges |
| `--virtual` (+ `-muted`) | purple | "Not a physical space" (V-rooms) |

**Rule:** no raw colours (`#hex`, `rgb()`) in any stylesheet except `tokens.css`
(the print rules in `timetable.css` and the self-contained offline page are the
exceptions). `web/tests_design_system.py` enforces it.

## Type, radius, shadow, size

- Font: **Geist** (vendored at `static/vendor/geist/`, OFL), with a system fallback.
- Radius: `--radius` 0.625rem; `--radius-sm/md/lg/xl` = -4px / -2px / 0 / +4px. Buttons and inputs `md`, cards `xl`, alerts `lg`.
- Shadows: `--shadow-xs` (controls), `--shadow-sm` (cards), `--shadow-lg` (popovers, sheets, the floor bottom bar).
- Sizes: buttons 36px (sm 32, lg 40), inputs 36px. **MMCM tailoring:** on floor screens and below 640px, buttons and inputs are at least `--touch` (44px).

## Breakpoints

sm 640, md 768, lg 1024, xl 1280. "Below X" is `max-width: (X - 0.02)px`.
`faculty.css` also uses 48rem and 64rem (pinned by tests). Every `@media` width
must be on this ladder; a test fails otherwise.

## Shells

- **Desk console** (`templates/_console.html`): light shadcn sidebar (crest +
  wordmark, grouped 32px items, current page on `--sidebar-accent` with navy
  text, account menu in the footer), a 56px top bar with a quiet location label
  and the bell, and a page header in the body. Below 1024px the sidebar is a
  modal drawer: focus trapped, Escape and the backdrop close it, focus returns
  to the menu button, the page behind is inert and does not scroll.
  Which console a desk user gets is decided in one place: `web.context.role_console`.
- **Floor shell** (Faculty, Checker, Guard): `_floor_top.html` header, the navy
  check-in card (Card on `bg-primary`, MMCM tailoring), cards, badges and alerts
  on shadcn anatomy, and a shadcn bottom navigation that becomes a side rail at
  64rem. Pages with the bar reserve `--tabbar-h` (57px, measured) plus the safe area.
- One brand mark (`_brand.html`) and one account menu (`_account_menu.html`) in every shell.

## Faculty: Liquid Glass (2026-11-08)

The Faculty screens follow Apple's Liquid Glass style (direction A, "Frosted
light"); the office roles keep shadcn, and Checker and Guard keep the floor
shell above until the user decides. Spec:
`docs/superpowers/specs/2026-11-08-faculty-liquid-glass-design.md`.

- **Where it lives:** `static/faculty/glass.css` and `static/faculty/glass.js`,
  loaded by `base.html` only when `user.role == "faculty"`, which also adds
  `html.ft-glass`. Every rule is scoped under `html.ft-glass`; a test fails on
  any unscoped selector, so the layer cannot reach Checker or Guard (they share
  `faculty.css`).
- **Tokens** (`tokens.css`): `--glass-fill`, `--glass-edge`, `--glass-base`,
  `--glass-alpha` (0.62, bars and light chrome), `--glass-strong-alpha` (0.86,
  dense content, the tab bar and anything text sits on), `--glass-hero-alpha`
  (0.9, the navy check-in card), `--glass-blur`, `--glass-shadow(-sm)`,
  `--glow-navy/red/blue` with their peak strengths `--glow-*-alpha` (backdrop
  light; kept low enough that muted text on a peak stays AA), `--font-ios`
  (system font first, so an iPhone shows SF; Geist elsewhere). Tests composite
  each glass and glow over its worst-case backdrop and require AA for the text.
- **Blur budget:** `backdrop-filter` only on floating chrome (the scrolled top
  bar, the bell, chips, the check-in card, the tab bar, Scan, sub-flow app
  bars). Dense cards and lists use the 0.86 fill with no blur (tested), so long
  lists scroll smoothly on cheap phones.
- **Chrome:** a floating capsule tab bar with short labels (the full names stay
  in `aria-label`), muted inactive tabs and the current tab as a solid navy
  capsule, plus a separate round Scan button (`.ft-scanbtn`, not `.ft-scan`,
  which is the scanner page). A bar under 280px (360-375px phones) tightens so
  all five labels still fit. From 48rem the bar floats at the top centre inside
  the top row; from 64rem tabs show icon and label side by side and Home is two
  columns.
- **States:** glass base rules outrank `faculty.css` state rules, so every
  focus, hover, invalid and `.is-*` state glass would erase is restated in
  `glass.css` (a test maps them). The check-in card's segment styles are scoped
  to `.ft-hero` so the request form's light control keeps its ink.
- **Motion:** cross-page View Transitions (the bars stay put, the active-tab
  capsule glides, the page fades and lifts; the request form rises like a
  sheet), all on one smooth ease-out curve. `glass.js` frosts the top bar on
  scroll, mirrors the large title into it once the title scrolls away (phones),
  and on phones only scales the tab bar down while scrolling down (transform,
  never height). Reduced motion turns all of it off.
- **Fallbacks:** no `backdrop-filter` support, or `prefers-reduced-transparency`,
  makes every glass surface solid. Fallback rules sit last in the file.
- **Patterns:** cards nested in a card render as an inset grouped list with
  dividers; buttons are capsules; fields are rounded and near-opaque.

## Page anatomy (desk)

Every desk page opens with `.ui-pagehead`: fill `page_title`, `page_desc` (one
line, plain words, no requirement codes) and `page_actions` (they wrap under the
title on a phone). Then, as needed:

- `.ui-filterbar` for GET filters: open on desktop, folded behind "Filters" on a phone.
- `.ui-stats` / `.ui-stat` for figures: equal-height cards, label, one value, one short note. Explanations go in a `.ui-explain` disclosure under the row.
- `.tbl.tbl--stack` for tables: every `<td>` carries `data-label`; below 640px each row becomes a labelled card.
- `_pager.html` (50 rows, D10) under every list that can grow past a screen. Live boards carry the page in their poll URL.
- `.ui-empty` for empty states, `.ui-steps` for multi-step processes (term set-up), `uk-alert` / `uk-badge` variants for status.

## Do and don't

- Do read colours as roles; do add a missing utility to `app.css` (there is no Tailwind build: a missing class does nothing, silently).
- Do keep htmx and offline hooks (`id`s, `data-offline-*`) when restyling; change CSS before markup.
- Don't put a colour, radius or breakpoint literal in a component rule.
- Don't put `*/` inside a CSS comment; keep CSS and template comments ASCII.
- Don't add a second header to a page: the console and floor shells own their chrome.
- After any CSS change run `collectstatic` before checking in a browser.
