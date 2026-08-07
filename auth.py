import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# H2 fix: the old 4-character floor made brute-force/guessing trivial. Raise the
# minimum to 8 (override with PASSWORD_MIN_LENGTH). Kept as a small, dependency-free
# helper so it is unit-testable in isolation and applied identically at every place
# a password is set (registration and password reset).
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))


def validate_password_strength(password: str):
    """Return (ok: bool, message: str). message is a user-facing reason when ok is
    False, empty when ok is True. Enforces the minimum length only — no maximum,
    no character-class rules (which push users toward predictable patterns)."""
    if len(password or "") < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters"
    return True, ""


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
