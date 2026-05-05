"""
HMAC-signed approval URLs for driver/supplier confirmation links.

The signed URL embeds the offer_id and an expiry timestamp, signed with a shared
secret so any tampering is rejected. No DB lookup needed to verify authenticity.

URL format: {base}/approve?offer={offer_id}&exp={unix_ts}&sig={hex}
"""
import hmac
import hashlib
import time
from app.config import settings


def sign_approval_url(offer_id: int, ttl_seconds: int | None = None) -> str:
    """Generate a full signed approval URL valid for ttl_seconds (default from settings)."""
    exp, sig = sign_approval_params(offer_id, ttl_seconds)
    base = settings.approval_base_url.rstrip("/")
    return f"{base}/approve?offer={offer_id}&exp={exp}&sig={sig}"


def sign_approval_params(offer_id: int, ttl_seconds: int | None = None) -> tuple[int, str]:
    """Return (exp, sig) for an offer. Useful when generating inline forms server-side."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.approval_link_ttl_seconds
    exp = int(time.time()) + ttl
    sig = _compute_sig(offer_id, exp)
    return exp, sig


def verify_approval_params(offer_id: int, exp: int, sig: str) -> tuple[bool, str]:
    """
    Verify a signed approval link's parameters.
    Returns (valid, reason). reason is empty if valid, else a short error key.
    """
    if not settings.approval_link_secret:
        return False, "secret_not_configured"
    if exp < int(time.time()):
        return False, "expired"
    expected = _compute_sig(offer_id, exp)
    if not hmac.compare_digest(expected, sig):
        return False, "invalid_signature"
    return True, ""


def _compute_sig(offer_id: int, exp: int) -> str:
    payload = f"offer={offer_id}&exp={exp}".encode()
    secret = settings.approval_link_secret.encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()
