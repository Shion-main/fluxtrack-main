# FluxTrack: Scenarios by Role

> **Superseded historical scenario snapshot.** The `(live today)` and `(planned)`
> annotations below reflect the early build, not the completed repository. Use
> [`../FluxTrack_SRS.md`](../FluxTrack_SRS.md) v1.3 for current requirements and
> [`PROGRESS.md`](./PROGRESS.md) for current implementation status. The narratives
> are retained as product-design history.

Plain-language walkthroughs of how each person actually experiences
FluxTrack — no requirement IDs, no field names. Written for reading, not
building; the technical build reference with status tracking and
requirement IDs is `docs/USE_CASES.md`.

Each scenario ends with a status note in italics: *(live today)* means you
can actually do this in the app right now; *(planned)* means it's designed
but not built yet.

---

## Faculty

Professor Reyes teaches three sections a week. She just wants class to
start without thinking about the app.

**Starting class on time.** It's 7:55 AM. Professor Reyes walks into R307
for her 8:00 Software Engineering class. She opens FluxTrack on her phone,
taps "Check in," and points her camera at the QR code taped by the door.
The app confirms: "Checked in — Present." That's it — no forms, no typing.
*(live today)*

**Running late.** Her previous meeting ran over. She scans in at 8:20,
twenty minutes after class was supposed to start. Instead of checking her
in, the app tells her the session has already been marked Absent — the
grace window closed at 8:15. She'll need a Checker who sees she's actually
there to correct the record; the app itself won't let her talk her way back
in. *(live today — though the "Checker corrects it" half isn't built yet,
see the Checker section)*

**Ending class early.** Her 9:15 class wraps up at 9:40 instead of 10:00
because she finished the lecture early. She scans the same room's QR code
again to check out. Because it's more than fifteen minutes before the
scheduled end, the app asks her why: she types "Finished topic early,
review session next class" and confirms. Done. *(live today)*

**Wrong room by habit.** She's used to teaching in R311, but this term
she's been moved to R307. Out of habit she scans R311's code. The app
notices her actual class is elsewhere and asks: "Your session is scheduled
in R307, but you scanned R311 — hold your class here instead?" She confirms
because the room's actually free and it's more convenient — the system
updates her session's room and quietly lets the facilities office know the
room changed. *(live today)*

**Walking into an occupied room.** She scans into R307 but another
professor's class is still showing as in-progress there — maybe that
professor forgot to check out. FluxTrack tells her the room is occupied and
offers to force a handover: confirm, and the system closes out the other
class automatically and starts hers. No awkward conversation with the other
professor needed. *(live today)*

**Too early, or in the wrong context.** If she scans a room fifteen minutes
before anything is due to start there, or scans a room QR for a class
that's supposed to be fully online, the app tells her plainly why it won't
check her in yet rather than silently failing. *(live today)*

**Teaching online.** For a fully-online session, she doesn't scan anything
— she opens the app, confirms her Teams meeting link is correct, and taps
"Verify & Start." *(planned)*

**Checking her own record.** At the end of the month she wants to see her
attendance history — every class, whether it was verified by a facilities
Checker, any flags raised against her. She can look but can't dispute
anything from the app; if something's wrong, that's a conversation outside
the system. *(planned)*

---

## Checker

Marco is facilities staff, assigned to the 3rd floor for the morning shift.
His job is to physically confirm that what the app says is happening in a
room is actually happening.

**Starting a shift.** Marco clocks in for his shift and opens FluxTrack.
Before he's assigned to a floor for the day, the app won't let him verify
anything — this stops someone wandering into a floor they're not covering
and marking things. Once IFO has assigned him to Floor 3, his floor view
lights up. *(planned — the assignment step and the floor view are both not
built yet)*

**Walking the floor.** His floor view shows every room on Floor 3 as a
color-coded card: green for verified, yellow for awaiting a check, red for
something's off. A priority queue at the top shows him the class that's
been waiting longest for a physical check — that's where he heads first,
not just whichever room is closest. *(planned)*

**Verifying a class.** He scans R307's QR code. The app shows him the
class that's supposed to be happening there right now, plus the professor's
photo. He looks in the room, sees the same professor teaching, and taps
"Verify." That session is now confirmed by an actual human, not just a
phone scan. *(planned)*

**Catching a mismatch.** He scans R311 and the photo doesn't match the
person standing at the front of the room. He taps "Flag identity
mismatch" — this goes straight to facilities and HR, no back-and-forth
inside the app. *(planned)*

**Correcting a mistaken Absent.** The system marked Professor Reyes' 8:00
class Absent because she scanned in twenty minutes late — but Marco can see
with his own eyes she's right there teaching. He overrides it to Present.
If the room had already been released as free in the meantime, the record
still gets corrected, but the room itself stays released — and facilities
gets a note that there's a conflict to sort out (someone thought this room
was empty and it isn't). *(planned)*

**Going offline.** Marco loses signal in the stairwell between floors. He
keeps scanning — the app queues everything locally on his phone. The moment
he's back online, every queued scan gets sent and re-checked against
whatever's true *now* (not blindly trusted from when he scanned), and
anything that can't be cleanly applied gets flagged for facilities to look
at instead of silently failing. *(planned)*

---

## IFO Admin (Integrated Facilities Office)

Ana runs the facilities office. She's the one who sets everything up at the
start of term and watches it run day to day.

**Loading a new term.** At the start of the semester, the registrar hands
her a spreadsheet of every class, room, and time slot. Today, getting that
into FluxTrack is a command someone runs for her rather than something she
does herself — she hands the file off and gets back a confirmation of how
many classes were imported. *(planned as a self-serve upload; the
underlying import logic itself is built and already validated against a
real registrar file)*

**Printing room posters.** For every room, she opens its page in FluxTrack
and prints a poster: the room name, a QR code, and a six-digit backup code
for anyone whose camera won't cooperate. She tapes these up by each
classroom door. *(live today)*

**A room's codes leak or get worn out.** If a poster gets torn down and
photographed by someone who shouldn't have it, or just gets too faded to
scan, she can regenerate that room's QR and six-digit code — the old
poster stops working the moment she does, and there's a record of exactly
when and who rotated it. *(planned)*

**Watching the floor live, mid-morning.** She keeps a live view open showing
every session happening right now, updating every few seconds — who's
checked in, who hasn't shown, what's flagged. *(live today, as a polling
list — not yet a visual floor map)*

**Someone's stuck in limbo.** A room shows as occupied but nobody's
actually there — maybe a class was cancelled and nobody told the system.
She can manually release the room and clear whatever conflict flag got
raised. *(planned)*

**Booking a room for a one-off event.** A department wants R307 for a
guest lecture next Tuesday that isn't part of the regular schedule. She
creates a one-time booking, and the system makes sure it doesn't collide
with an actual class or another booking. *(planned)*

**Assigning today's Checkers.** She assigns Marco to Floor 3 for the
morning shift and someone else to the afternoon — this is what actually
turns on their ability to verify anything. *(planned)*

**Friday afternoon report.** Every Friday she pulls up the week's
consolidated attendance report, broken down by department, and either lets
it auto-generate or pulls it on demand. She exports it as a PDF to send to
the deans. *(planned)*

---

## HR Admin

Renz handles payroll-adjacent reporting. He doesn't run payroll inside
FluxTrack — the system explicitly doesn't do that — but he pulls the
attendance data payroll depends on.

**Pulling verified attendance.** Before a payroll cutoff, he opens
FluxTrack and filters attendance records to a date range and a department,
seeing exactly who was present, who was absent, and whether a Checker
actually confirmed it or it's just a self-reported scan. *(planned)*

**Exporting for payroll.** He exports the filtered results as a CSV and
hands it to whatever external payroll system MMCM actually uses — FluxTrack
stops at the export, it never processes pay itself. *(planned)*

---

## Guard

Diego is campus security, posted to a building entrance. His access is
read-only — he watches, he doesn't change anything.

**Keeping an eye on the floor.** From his post, he glances at a live view
of room status on his assigned floor(s) — helpful for noticing something
odd, like a room showing a class in progress with the lights off.
*(planned)*

**A visitor asks for a professor.** Someone at the front desk asks where
Professor Reyes is right now. Diego searches her name and gets back: which
room she's in, which building and floor, what class, and when it ends — or
"Online — not on campus" if she's teaching remotely, or her next class if
she's not teaching at this moment. *(planned)*

**Getting pinged.** If something unusual happens on his floor — repeated
scan failures, a room that's been flagged — he gets a push notification
rather than needing to keep the live view open constantly. *(planned)*

---

## Dean

Dr. Villanueva oversees the Computer Science department. Her access is
read-only, and scoped only to her own department — she can't see other
departments' data.

**Weekly check-in.** Every week she glances at her department's
consolidated attendance report — who's been present, who's had repeated
absences worth a conversation. *(planned)*

**Following up on a specific professor.** After a student complains about
a professor missing class, she pulls up that professor's individual
scorecard: scheduled classes vs. actually held, attendance percentage,
absences, early-ends, and how much of their teaching has been online vs.
in-person. *(planned)*

---

## System Admin

The System Admin keeps the underlying machinery healthy — users, policy
values, and making sure scheduled jobs are actually running.

**Onboarding a new hire.** A new faculty member joins mid-term. The admin
creates their account, assigns them the Faculty role and their department.
*(partial today — done through Django's built-in admin panel rather than a
FluxTrack-specific screen; works, just not polished)*

**Adjusting a policy value.** The grace period is currently fifteen
minutes, an assumption nobody's confirmed against MMCM's actual attendance
policy yet. When that policy comes through, the admin updates the value in
one place and it takes effect everywhere immediately — nothing hardcoded
requires a code change. *(partial today — same admin-panel caveat as
above)*

**Investigating a discrepancy.** A dean asks why a particular session shows
as force-handed-over. The admin checks the audit log, which recorded every
write action anyone took, and finds exactly who did what and when.
*(partial today — viewable via the admin panel, already linked from the
System Admin home screen)*

**The Friday report didn't show up.** The weekly report was supposed to
generate automatically Friday night and it didn't. The admin checks a job
monitor showing when each scheduled job last ran and whether it succeeded
— today, nothing like this exists yet, because the scheduled jobs
themselves (nightly session creation, the sweep that marks no-shows
Absent, weekly report generation) aren't wired up to run automatically at
all. *(planned)*

---

## What ties these together

A few threads run through all seven roles' stories:

- **Faculty and Checker are the only two roles anything is actually built
  for today.** Everyone else — IFO Admin included, despite having the most
  scenes built — is missing the parts of their story that involve anything
  beyond looking at a live list or printing a poster.
- **The Checker's story is entirely unbuilt**, and it's the one every other
  role's trust in the data depends on — "verified by a Checker" is what
  makes an attendance record more than a self-report.
- **Nobody sees a notification yet**, even though the system is already
  quietly creating some of them (Professor Reyes' wrong-room correction
  really does notify IFO in the database — there's just no screen showing
  it to Ana yet).
