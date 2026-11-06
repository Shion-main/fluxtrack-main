"""Strict browser push destination and encryption-key boundary."""
import base64
import binascii
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec


def valid_endpoint(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 500:
        return False
    try:
        url = urlsplit(endpoint)
        if (url.scheme != "https" or url.port not in (None, 443)
                or url.username or url.password or url.fragment
                or not url.path or any(ord(c) <= 32 for c in endpoint)):
            return False
        host = url.hostname or ""
        return (host in {"fcm.googleapis.com", "updates.push.services.mozilla.com",
                         "web.push.apple.com"}
                or (host.endswith(".notify.windows.com")
                    and all(part and part.replace("-", "").isalnum()
                            for part in host.split("."))))
    except ValueError:
        return False


def _decode(value):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("invalid key")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def valid_subscription(endpoint, keys):
    if not valid_endpoint(endpoint) or not isinstance(keys, dict):
        return False
    try:
        public, auth = _decode(keys.get("p256dh")), _decode(keys.get("auth"))
        if len(public) != 65 or public[0] != 4 or len(auth) != 16:
            return False
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
        return True
    except (ValueError, TypeError, binascii.Error):
        return False
