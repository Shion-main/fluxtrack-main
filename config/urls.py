"""FluxTrack URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # python-social-auth: /auth/login/<backend>/ + /auth/complete/<backend>/
    # (namespace 'social'; TRAILING_SLASH=True matches the registered Entra
    # callback /auth/complete/azuread-tenant-oauth2/ — Pitfall 3)
    path("auth/", include("social_django.urls", namespace="social")),
    path("", include("web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
