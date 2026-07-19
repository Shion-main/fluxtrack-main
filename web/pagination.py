"""Shared list pagination for the dense admin tables (HR, Dean, SysAdmin).

Before this, long lists were handled by slicing to a cap (`qs[:200]`) and printing
"Showing up to 200 rows." That silently truncates: the reader has no idea whether
they are looking at everything or at an arbitrary window, which is exactly the
wrong property for a system of record. Pagination replaces the cap with an honest,
navigable window.

Two rules the surfaces here depend on:

  - Page state lives in the querystring, so a page is linkable, the back button
    works, and an existing filter bar keeps working unchanged.
  - `querystring` carries every OTHER GET param forward, so paging never silently
    drops the filters the user applied.

Exports are deliberately NOT paginated -- HR's CSV still streams the full filtered
set (HR-03). The page bounds the screen, not the data. ASCII-only.
"""
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

DEFAULT_PER_PAGE = 50


def paginate(request, object_list, per_page=DEFAULT_PER_PAGE, param="page"):
    """Return a context dict for `_pager.html` plus the current page's objects.

    Accepts a queryset OR a plain list (the reporting surfaces build lists of
    dicts, not querysets). Out-of-range and non-integer page values degrade to a
    valid page rather than raising -- a hand-edited or stale `?page=` must never
    500 a read-only surface.
    """
    paginator = Paginator(object_list, per_page)
    raw = request.GET.get(param)
    try:
        page = paginator.page(raw)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        # Past the end (stale link, or the filter narrowed the set): clamp to the
        # last real page instead of showing an error.
        page = paginator.page(paginator.num_pages)

    # Every other GET param, so a page link preserves the active filters.
    params = request.GET.copy()
    params.pop(param, None)
    querystring = params.urlencode()

    return {
        "page": page,
        "paginator": paginator,
        "page_param": param,
        "querystring": f"{querystring}&" if querystring else "",
        # first / last / +-2 with ellipses, so the control stays a fixed width
        # whether there are 3 pages or 300.
        "page_range": paginator.get_elided_page_range(
            page.number, on_each_side=2, on_ends=1),
    }
