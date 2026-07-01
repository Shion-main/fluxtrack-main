"""Policy value access: SystemSetting row overrides the settings default (SRS §8)."""
from django.conf import settings

from .models import SystemSetting


def get_policy(key):
    row = SystemSetting.objects.filter(key=key).first()
    if row is not None:
        raw = row.value
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    return settings.FLUXTRACK_POLICY[key]
