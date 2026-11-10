# backend/passwords.py
#
# Password and username rules, and password hashing. Pure functions: no database,
# no Flask. (db.py and main.py call these.)
#
# Hashing: scrypt from Python's standard library (memory-hard, no extra package).
#   * Parameters are stored inside every hash, so they can be raised later and old
#     hashes keep working; `needs_rehash` tells the login code to upgrade a hash
#     the next time its owner signs in.
#   * Hashes made by the old code (PBKDF2, "salt:hash") still verify, and are
#     upgraded to scrypt transparently at the next successful login.
#
# Policy follows current NIST guidance (SP 800-63B): a sensible minimum LENGTH,
# a high maximum, no composition rules ("must contain a symbol"), no silent
# trimming or truncation, and a block-list of well-known weak passwords.
import hashlib
import hmac
import os
import re
import secrets
import unicodedata

# OWASP's minimum scrypt configuration for ~32 MiB of memory: N=2^15, r=8, p=3.
# Tests lower the cost with PASSWORD_HASH_FAST=1 (see conftest.py); production never does.
_PROD_PARAMS = (2 ** 15, 8, 3)
_FAST_PARAMS = (2 ** 10, 8, 1)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128        # for NEW passwords (sign-up / change)
MAX_LOGIN_PASSWORD_LENGTH = 1024  # sign-in accepts old, longer passwords but still bounds the work per request
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")


def _params() -> tuple[int, int, int]:
    # The cheap setting exists only so the test suite is fast. It is IGNORED on Vercel and whenever
    # a production database is configured, so a stray environment variable can never weaken real passwords.
    fast = os.getenv("PASSWORD_HASH_FAST") == "1" and not (os.getenv("VERCEL") or os.getenv("DATABASE_URL"))
    return _FAST_PARAMS if fast else _PROD_PARAMS


# ── hashing ───────────────────────────────────────────────────

def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    normalized = unicodedata.normalize("NFKC", password).encode("utf-8")
    return hashlib.scrypt(normalized, salt=salt, n=n, r=r, p=p, dklen=32,
                          maxmem=2 * 128 * n * r + 2 ** 20)


def hash_password(password: str) -> str:
    n, r, p = _params()
    salt = secrets.token_bytes(16)
    return f"scrypt${n}${r}${p}${salt.hex()}${_scrypt(password, salt, n, r, p).hex()}"


def _verify_legacy_pbkdf2(password: str, stored: str) -> bool:
    """Hashes written by the first version of the app: '<salt>:<pbkdf2 hex>'."""
    try:
        salt, hash_hex = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, hash_hex = stored.split("$")
            n, r, p = int(n), int(r), int(p)
            if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 16 and 1 <= p <= 16):
                return False                     # refuse absurd parameters in a corrupted row
            digest = _scrypt(password, bytes.fromhex(salt_hex), n, r, p)
            return hmac.compare_digest(digest.hex(), hash_hex)
        except Exception:
            return False
    return _verify_legacy_pbkdf2(password, stored)


def needs_rehash(stored: str) -> bool:
    """True for old PBKDF2 hashes and for scrypt hashes made with weaker/other parameters."""
    if not stored or not stored.startswith("scrypt$"):
        return True
    try:
        _, n, r, p, *_ = stored.split("$")
        return (int(n), int(r), int(p)) != _params()
    except Exception:
        return True


_dummy_hash = None


def burn_time_like_a_real_check(password: str) -> None:
    """Run a full hash verification against a dummy hash.

    Used when the username does not exist, so "unknown user" and "wrong password"
    take the same time and an attacker cannot tell which usernames are real."""
    global _dummy_hash
    if _dummy_hash is None or needs_rehash(_dummy_hash):
        _dummy_hash = hash_password("not-a-real-password-just-for-timing")
    verify_password(password, _dummy_hash)


# ── rules ─────────────────────────────────────────────────────

_COMMON = frozenset("""
password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword pass1234 passcode
12345678 123456789 1234567890 11111111 00000000 87654321 12341234 123123123 111111111 123456789a
qwertyui qwerty123 qwertyuiop qwerty1234 asdfghjk asdfghjkl zxcvbnm1 1q2w3e4r 1qaz2wsx zaq12wsx
abcd1234 abc12345 abcdefgh abcdefg1 iloveyou iloveyou1 letmein1 letmein123 welcome1 welcome123
admin123 administrator changeme changeme1 test1234 testtest user1234 default1 secret123 mypassword
football baseball basketball superman batman sunshine princess trustno1 whatever monkey123 dragon12
master123 shadow123 michael1 jessica1 charlie1 india123 india@123 internet computer2 letmein!
""".split())


def validate_username(username: str) -> str | None:
    """Return an error message, or None if the username is acceptable (new accounts only)."""
    if not USERNAME_RE.match(username or ""):
        return ("Username must be 3-32 characters: letters, numbers, dot, dash or underscore, "
                "and start with a letter or number.")
    return None


def validate_password(password: str, username: str = "") -> str | None:
    """Return an error message, or None if the password is acceptable (new/changed passwords only).
    Signing in never applies these rules, so existing accounts are not locked out."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) == 1:
        return "That password is too common. Pick something harder to guess."
    if len(username) >= 3 and username.lower() in lowered:
        return "Password must not contain your username."
    return None
