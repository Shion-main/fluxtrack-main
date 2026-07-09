# Phase 5 — Discussion Log

**Date:** 2026-07-09
*Human reference only — not consumed by downstream agents.*

## Areas discussed

### Notification surface
- Options: bell + dropdown panel / dedicated full-page list / both.
- **Chosen: Both** — bell + unread badge + short dropdown, plus a "See all" full-page list.

### Mute granularity (NOTIF-03)
- Options: per event type / global push on-off / by category group.
- **Chosen: By category group** — Room events, Reports, System; suppresses both list and push.

### Web push opt-in
- Options: opt-in toggle on notifications page / prompt on login-first-visit.
- User first picked "prompt on login/first visit."
- **Challenge raised:** a raw unsolicited browser prompt risks a permanent origin-block on a stray "Block" — kills the VAPID demo. Offered a soft pre-prompt middle ground.
- **Final: A — soft pre-prompt on first visit** (in-app "Enable / Not now" banner; real browser prompt only on Enable).

### Read / retention
- Options: auto-read on view + keep all / manual mark-read / auto-read + auto-expire.
- **Chosen: Auto-read on view + keep all.**

## Deferred
- Per-event-type granular mute.
- Notification auto-expiry/pruning.
- Real-time (SSE/WebSocket) delivery.

## Todos reviewed
- `entra-auth-backend-decision`, `phase1-localdb-env-deviations` — matched only on the generic "phase" keyword; not relevant, not folded.
