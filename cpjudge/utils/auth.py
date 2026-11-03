"""Authentication and password hashing utilities for CPJudge.

Supports Argon2 and bcrypt password hashing algorithms.
"""
import secrets
import string
from typing import Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _ARGON2_HASHER = PasswordHasher()
except ImportError:
    _ARGON2_HASHER = None

try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def hash_password(password: str, method: str = "argon2") -> str:
    """Hashes a plain-text password using Argon2 or bcrypt.

    Args:
        password: The plain-text password to hash.
        method: Hashing method ('argon2' or 'bcrypt'). Defaults to 'argon2'.

    Returns:
        Hashed password string.
    """
    if method == "argon2" and _ARGON2_HASHER is not None:
        return _ARGON2_HASHER.hash(password)

    if _HAS_BCRYPT:
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    # Fallback to argon2 if available
    if _ARGON2_HASHER is not None:
        return _ARGON2_HASHER.hash(password)

    raise RuntimeError("Neither argon2-cffi nor bcrypt is available for password hashing.")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain-text password against a hashed password.

    Supports Argon2 ($argon2id$, $argon2i$), bcrypt ($2a$, $2b$), and standard formats.

    Args:
        plain_password: The user-supplied plain-text password.
        hashed_password: The stored hashed password.

    Returns:
        True if the password matches, False otherwise.
    """
    if not hashed_password or not plain_password:
        return False

    # Check for Argon2 hash format
    if hashed_password.startswith("$argon2"):
        if _ARGON2_HASHER is not None:
            try:
                return _ARGON2_HASHER.verify(hashed_password, plain_password)
            except VerifyMismatchError:
                return False
            except Exception:
                return False
        return False

    # Check for bcrypt format
    if hashed_password.startswith("$2a$") or hashed_password.startswith("$2b$") or hashed_password.startswith("$2y$"):
        if _HAS_BCRYPT:
            try:
                return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
            except Exception:
                return False
        return False

    # Try Argon2 as fallback
    if _ARGON2_HASHER is not None:
        try:
            return _ARGON2_HASHER.verify(hashed_password, plain_password)
        except Exception:
            pass

    return False


def generate_random_password(length: int = 10) -> str:
    """Generates a secure, human-friendly random password for initial student accounts."""
    # Use characters that avoid visual ambiguity (exclude 0, O, 1, l, I)
    alphabet = "23456789abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ#$*@!"
    return "".join(secrets.choice(alphabet) for _ in range(length))
