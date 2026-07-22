"""Infrastructure-only endpoints kept independent from application state."""
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health(request):
    """Process liveness for Nginx and an AWS target-group health check."""
    return JsonResponse({"status": "ok"})
