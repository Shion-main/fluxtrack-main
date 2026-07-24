"""HTTP response policies shared by every FluxTrack surface."""
from django.utils.cache import patch_cache_control


class NoStoreHTMLMiddleware:
    """Keep browser/proxy caches from replaying stale or sensitive HTML."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("text/html"):
            patch_cache_control(
                response,
                private=True,
                no_cache=True,
                no_store=True,
                must_revalidate=True,
                max_age=0,
            )
        return response
