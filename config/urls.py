"""FluxTrack URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.health import health

handler403 = "web.views.error_403"
handler404 = "web.views.error_404"
handler500 = "web.views.error_500"

urlpatterns = [
    path("healthz/", health, name="health"),
    path("admin/", admin.site.urls),
    # python-social-auth: /auth/login/<backend>/ + /auth/complete/<backend>/
    # (namespace 'social'; TRAILING_SLASH=True matches the registered Entra
    # callback /auth/complete/azuread-tenant-oauth2/ — Pitfall 3)
    path("auth/", include("social_django.urls", namespace="social")),
    path("", include("web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
