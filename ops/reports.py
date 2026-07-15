"""Weekly consolidated report generation, storage, and notification (RPT-02).

The single orchestration layer that turns the pure aggregate + render layers into
a stored, idempotent, notified artifact. It sits ABOVE the two side-effect-free
modules it reuses:

  - ``scheduling.reporting.faculty_attendance`` -> ``FacultyRow`` list (RPT-01)
  - ``scheduling.report_render.build_csv`` / ``build_pdf`` -> ``bytes`` (RPT-03)

and writes exactly two side effects, each through the one sanctioned path:

  - report bytes -> ``default_storage`` under a SERVER-BUILT name (never a
    request-derived path, T-06-05 path-traversal control); the ``STORAGES``
    default is FileSystemStorage -> ``MEDIA_ROOT`` today and swaps to S3 in
    Phase 8 with no change here.
  - a ``WEEKLY_REPORT_READY`` notification -> ``ops.notify.notify`` ONLY
    (NOTIF-00 single write path); IFO gets every report, each Dean gets ONLY
    their own department's (T-06-06 information-disclosure control).

Idempotency (RPT-02, T-06-12) rides ``WeeklyReport.unique_together(week_start,
department)`` via ``get_or_create``: JOB-03 re-running the same Monday (misfire
coalesce, manual re-run) or an on-demand regeneration overwrites the existing
row's ``csv_path``/``pdf_path`` and never creates a second row.

Week boundaries are computed on LOCAL dates (Asia/Manila ``Session.date``), never
UTC ``scheduled_start`` (Pitfall 1) -- ``report_week_bounds`` is pure (date in,
dates out).
"""
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from accounts.models import Role
from ops.models import WeeklyReport
from ops.notifications import WEEKLY_REPORT_READY
from ops.notify import notify
from ops.policy import get_policy
from scheduling.report_render import build_csv, build_pdf
from scheduling.reporting import faculty_attendance

# reporting_week_start policy value -> Python weekday() index (Mon=0 .. Sun=6).
# Only "monday" ships this milestone; the map keeps report_week_bounds honest to
# the policy instead of hardcoding Monday (Conventions 3).
_WEEK_START_WEEKDAY = {"monday": 0, "sunday": 6}


def report_week_bounds(reference_date):
    """Return the (start, end) local dates of the week CONTAINING reference_date.

    Pure: a ``datetime.date`` in, a ``(Monday, Sunday)`` tuple out, aligned to the
    ``reporting_week_start`` policy (``get_policy``, default "monday"). The caller
    chooses WHICH week -- JOB-03 passes ``localdate() - 7 days`` to report on the
    prior completed week. Both bounds are inclusive; ``faculty_attendance`` filters
    ``Session.date__range=(start, end)`` so the Sunday is included and the next
    Monday is excluded (Pitfall 1: local dates only, no UTC drift).
    """
    start_weekday = _WEEK_START_WEEKDAY.get(str(get_policy("reporting_week_start")).lower(), 0)
    offset = (reference_date.weekday() - start_weekday) % 7
    start = reference_date - timedelta(days=offset)
    end = start + timedelta(days=6)
    return start, end


def _save_overwrite(name, data):
    """Save ``data`` bytes under the DETERMINISTIC ``name``, overwriting any prior
    file so regeneration reuses the same server-built path (idempotency, RPT-02).

    ``default_storage.save`` would otherwise mint a suffixed name if the target
    exists, orphaning the previous bytes and drifting ``csv_path``/``pdf_path``;
    deleting first keeps the name stable and the row's stored path canonical.
    """
    if default_storage.exists(name):
        default_storage.delete(name)
    return default_storage.save(name, ContentFile(data))


def generate_weekly_report(week_start, week_end, department):
    """Generate + store ONE department's weekly report idempotently (RPT-02).

    Reuses the pure aggregate (``faculty_attendance``) and render (``build_csv`` /
    ``build_pdf``) layers, upserts the ``WeeklyReport`` row on its
    ``(week_start, department)`` uniqueness key, and writes both files via
    ``default_storage`` under a name built ONLY from ``department.code`` (or "ALL"
    when ``department`` is ``None`` for the IFO roll-up) + ``week_start`` -- never
    from request input (T-06-05). Returns the ``WeeklyReport``.
    """
    rows = faculty_attendance(start=week_start, end=week_end, department=department)
    report, _ = WeeklyReport.objects.get_or_create(
        week_start=week_start, department=department)

    code = department.code if department is not None else "ALL"
    csv_name = f"reports/{week_start}/{code}.csv"
    pdf_name = f"reports/{week_start}/{code}.pdf"

    report.csv_path = _save_overwrite(csv_name, build_csv(rows))
    report.pdf_path = _save_overwrite(pdf_name, build_pdf(rows, week_start, department))
    report.save(update_fields=["csv_path", "pdf_path"])
    return report


def notify_report_ready(department, week_start, link=""):
    """Fan a WEEKLY_REPORT_READY notice to IFO + the relevant Dean(s) (NOTIF-00).

    ALWAYS notifies IFO (``role=Role.IFO_ADMIN`` -> every active IFO admin). For a
    department-scoped report it ALSO notifies that department's active Deans via
    ``users=`` (there is no per-department role fan-out) so a Dean receives ONLY
    their own department's report (T-06-06). The ``None`` (ALL) roll-up notifies
    IFO alone. Every row goes through ``notify()`` -- NEVER a direct
    Notification model create (NOTIF-00).
    """
    dept_label = department.code if department is not None else "All"
    title = "Weekly attendance report ready"
    body = f"{dept_label} - week of {week_start}"

    notify(role=Role.IFO_ADMIN, type=WEEKLY_REPORT_READY,
           title=title, body=body, link=link)

    if department is not None:
        from django.contrib.auth import get_user_model
        deans = get_user_model().objects.filter(
            role=Role.DEAN, is_active=True, department=department)
        notify(users=deans, type=WEEKLY_REPORT_READY,
               title=title, body=body, link=link)
