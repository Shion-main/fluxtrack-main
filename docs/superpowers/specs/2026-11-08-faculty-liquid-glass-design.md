# Faculty screens in Apple's Liquid Glass style: design

Date: 2026-11-08. Status: awaiting the user's approval.
Mockup chosen: direction **A, Frosted light**, in
`.superpowers/brainstorm/2879-1794151893/content/liquid-glass-home.html`.

## Intent

The Faculty screens should feel like a premium native iPhone app, not a static
web page. The user's words: "look premium and like have liquid glasses effect
like the ui toolkit uses for apps right now, using apples ui/ux as basis",
"optimized for ios27, in mobile", "responsive, like a floating nav below",
"faculty first". Faculty use FluxTrack on their phones while walking between
classes, so it has to look polished and still be quick to read and tap.

Basis: Apple's Liquid Glass design language (introduced with iOS 26) and the
Human Interface Guidelines. iOS 27 specifics are not confirmed and are not guessed at.

## Goals

1. **Look (direction A).**
   - Soft navy and red light far behind the content, on a pale background.
   - Frosted white glass for cards, lists and bars.
   - The check-in card is navy glass you can faintly see through.
   - MMCM navy stays the main colour; red is used sparingly.
2. **Floating glass tab bar** at the bottom on phones. It keeps the five
   current faculty tabs: Home, Schedule, Online classes, My attendance, Requests.
3. **A separate round glass Scan button** beside the tab bar (the user asked
   for it). It opens the existing `/faculty/scan` page.
4. **Native-feeling motion:**
   - The large greeting title shrinks into a small glass bar at the top on scroll.
   - The tab bar shrinks while scrolling down and returns when scrolling up.
   - The glass highlight slides between tabs.
   - Pages slide between screens instead of flashing.
   - Buttons press in slightly when tapped.
   - All motion is off under the phone's reduce-motion setting.
5. **Responsive:**
   - Phones: the bottom floating bar.
   - Tablet and computer: the same glass bar floats at the top centre, like
     Apple's iPad apps, with the Scan button attached. Home uses two columns,
     with the check-in card beside today's classes.
6. **Every Faculty screen**, not just Home:
   - home, schedule, scan and its result card, online classes and online start;
   - attendance history;
   - requests (list, new request form, room picker);
   - profile and photo, and the faculty view of notifications.

## Non-goals

- Checker and Guard (they come later, after Faculty is approved).
- Office roles: they keep the shadcn console.
- Dark mode, haptics (iPhone browsers cannot vibrate), and a native iOS app.
- Changing what any screen does or saves. No product rule changes.

## Anti-goals (a failure even if it works)

- Text that is hard to read on glass, outdoors or in a hurry. Body text must
  meet AA contrast on the glass it sits on.
- A slow or janky phone. Blur must not make scrolling stutter.
- Glass everywhere, like a theme demo. Glass is for floating things (bars,
  buttons, the check-in card); dense content stays on near-opaque surfaces.
- Breaking htmx, offline or check-in hooks (ids, `data-*`, form fields).
- Changing the Checker or Guard screens by accident.

## Constraints

- **Stack:** Django templates, Franken UI, htmx, plain CSS; no build step.
  Changing the colour roles in `static/css/tokens.css` changes them everywhere.
  The new glass values go there as new tokens, because the no-raw-colours test
  enforces that.
- **Decision D14 changes for Faculty:** last session's rule was "every role
  follows shadcn". The user approved moving the Faculty screens to Apple's style.
  D14 needs an update in the vault: office roles stay shadcn, Faculty follows
  Apple's style, and Checker and Guard are to be decided.
- **Fonts:** Apple's SF Pro cannot be bundled. The Faculty font stack puts the
  phone's own system font first, which is SF on an iPhone, then falls back to Geist.
- **Fallbacks:**
  - Where the browser cannot blur, or the user asks for reduced transparency,
    glass becomes a solid surface.
  - Where page transitions are unsupported, pages simply load as today.
- **Tests and workflow:** every existing test must pass. The pinned strings in
  `faculty.css` stay, because Checker and Guard still use it. Work is
  test-first, ends with the full suite run at several clock times, and keeps
  the SRS restore. Browser checks run on the throwaway `fluxtrack_demo` copy.
- **Committing:** nothing is committed without the user's say-so. The previous
  redesign (about 105 files) is still staged and uncommitted.

## How (decided)

| Item | Decision | Whose |
|---|---|---|
| Look | Direction A, Frosted light | user |
| Scan button | Separate round glass button beside the tab bar | user |
| Bottom floating bar on phones | Yes | user |
| Where the new look lives | A new Faculty-only stylesheet (`static/faculty/glass.css`), loaded only on Faculty pages, on top of `faculty.css` | my call |
| Tablet and computer | The glass bar floats at the top centre; Home in two columns from 1024px | my call (shown, not objected to) |
| Page transitions | The browser's built-in cross-page transitions, which need no script | my call |
| Title collapse and tab-bar shrink | A small script that watches scroll direction | my call |
| Request form | Stays its own page, but slides up like an iPhone sheet | my call |

## Left to the builder

Exact blur strengths, corner radii, spring timings, highlight positions, icon
sizes, and how each secondary screen (history filters, request form fields,
photo upload) is laid out in the glass style. These should follow Apple's
Human Interface Guidelines and the mockup.

## How we will know it worked

- On a 390px phone view, every Faculty screen matches direction A:
  - the floating bar and Scan button never cover content;
  - nothing scrolls sideways;
  - text passes AA contrast.
- On tablet and computer widths, the bar sits at the top centre and Home is two columns.
- With reduce-motion on, nothing animates.
- Checker and Guard screens look exactly as before.
- The full test suite passes.
- Not provable here: how it feels on a real iPhone. That stays an open item.
