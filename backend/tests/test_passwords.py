# backend/tests/test_passwords.py
import hashlib
import unicodedata

import pytest

from backend import passwords as pw


def legacy_hash(password: str, salt: str = "ab" * 16) -> str:
    """Exactly what the first version of the app stored: '<salt>:<pbkdf2-sha256 hex>'."""
    return f"{salt}:{hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()}"


# ── hashing ───────────────────────────────────────────────────────────────

def test_production_cost_parameters_are_what_we_claim(monkeypatch):
    """Tests run with cheap hashing; this one test proves production uses OWASP-grade scrypt."""
    monkeypatch.delenv("PASSWORD_HASH_FAST", raising=False)
    stored = pw.hash_password("a perfectly fine passphrase")
    assert stored.startswith("scrypt$32768$8$3$")
    assert pw.verify_password("a perfectly fine passphrase", stored)
    assert not pw.verify_password("another passphrase", stored)
    assert pw.needs_rehash(stored) is False


@pytest.mark.parametrize("env", [{"VERCEL": "1"}, {"DATABASE_URL": "postgresql://example"}])
def test_the_cheap_test_setting_is_ignored_in_production(monkeypatch, env):
    monkeypatch.setenv("PASSWORD_HASH_FAST", "1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert pw.hash_password("a perfectly fine passphrase").startswith("scrypt$32768$8$3$")


def test_every_hash_has_its_own_salt():
    a, b = pw.hash_password("same password!"), pw.hash_password("same password!")
    assert a != b and pw.verify_password("same password!", a) and pw.verify_password("same password!", b)


def test_the_password_is_never_in_the_hash():
    assert "hunter22-secret" not in pw.hash_password("hunter22-secret")


def test_unicode_forms_of_the_same_password_are_equivalent():
    """'é' typed as one character or as e + accent must be the same password on every device."""
    composed, decomposed = unicodedata.normalize("NFC", "caf\u00e9-pass1"), unicodedata.normalize("NFD", "caf\u00e9-pass1")
    assert composed != decomposed
    assert pw.verify_password(decomposed, pw.hash_password(composed))


@pytest.mark.parametrize("stored", [None, "", "garbage", "scrypt$", "scrypt$a$b$c$d$e", "salt:nothex", ":"])
def test_garbage_stored_values_never_verify_and_never_raise(stored):
    assert pw.verify_password("anything", stored) is False


def test_absurd_parameters_in_a_corrupted_row_are_refused_not_executed():
    """A tampered row asking for N=2^30 must not make the server allocate gigabytes."""
    assert pw.verify_password("x", f"scrypt${2**30}$8$3${'00' * 16}${'00' * 32}") is False
    assert pw.verify_password("x", f"scrypt$1024$1000$3${'00' * 16}${'00' * 32}") is False


# ── upgrading old hashes ──────────────────────────────────────────────────

def test_old_pbkdf2_hashes_still_verify_and_are_flagged_for_upgrade():
    old = legacy_hash("old-school-pw")
    assert pw.verify_password("old-school-pw", old) and not pw.verify_password("wrong", old)
    assert pw.needs_rehash(old) is True


def test_hashes_made_with_other_parameters_are_flagged_for_upgrade(monkeypatch):
    monkeypatch.delenv("PASSWORD_HASH_FAST", raising=False)
    weaker = pw.hash_password("x" * 12)                     # production cost
    monkeypatch.setenv("PASSWORD_HASH_FAST", "1")
    assert pw.needs_rehash(weaker) is True                  # "current" is now the cheap setting
    assert pw.needs_rehash(pw.hash_password("x" * 12)) is False


def test_dummy_verification_runs_without_error():
    assert pw.burn_time_like_a_real_check("whatever") is None


# ── policy ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("password, fragment", [
    ("short1", "at least 8"),
    ("", "at least 8"),
    ("x" * 129, "at most 128"),
    ("password123", "too common"),
    ("PASSWORD123", "too common"),          # case-insensitive
    ("aaaaaaaaaa", "too common"),           # one repeated character
    ("12345678", "too common"),
    ("my-ravi-pass-1", "must not contain your username"),
])
def test_weak_passwords_are_rejected(password, fragment):
    msg = pw.validate_password(password, username="Ravi")
    assert msg and fragment in msg


@pytest.mark.parametrize("password", [
    "correct horse battery staple",         # long passphrases are good: no symbol/digit rules
    "Tr0ub4dor&3-xyz",
    "  leading and trailing spaces  ",       # spaces are allowed and kept
    "pässwörd-ünïcode-ok",
    ("Ab1-" * 40)[:128],                     # exactly the maximum length
])
def test_reasonable_passwords_are_accepted(password):
    assert pw.validate_password(password, username="ravi") is None


def test_a_short_username_is_not_banned_inside_passwords():
    assert pw.validate_password("abcdefgh-ij", username="ab") is None      # 2-letter names would reject too much


@pytest.mark.parametrize("name", ["abc", "Ravi_Kumar", "ravi.k-99", "a" * 32, "9lives"])
def test_good_usernames(name):
    assert pw.validate_username(name) is None


@pytest.mark.parametrize("name", ["", "ab", "a" * 33, "has space", "ravi@mail.com", "_start", "-start", ".dot",
                                  "ravi\u200b", "r\u0430vi"])        # zero-width space, Cyrillic 'а' look-alike
def test_bad_usernames(name):
    assert pw.validate_username(name) is not None
