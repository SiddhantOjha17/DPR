"""Password hashing and signed-session helpers. Stdlib only - no new dependency.

Sessions are invalidated whenever the app process restarts by design: the HMAC
secret is generated fresh in memory each time create_app() runs and is never
persisted, so a cookie signed by a previous process simply stops verifying once
that process (and its secret) is gone. No session table, no cleanup job.
"""
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex)."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    if not password_hash or not salt:
        return False
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def sign_session(user_id: int, secret: bytes) -> str:
    payload = str(user_id)
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session(token: str | None, secret: bytes) -> int | None:
    if not token or "." not in token:
        return None
    payload, _, signature = token.partition(".")
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        return int(payload)
    except ValueError:
        return None
