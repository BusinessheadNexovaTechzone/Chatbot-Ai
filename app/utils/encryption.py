import base64
import hashlib
from cryptography.fernet import Fernet

def _fernet(key: str) -> Fernet:
    """Derive a URL-safe 32-byte Fernet key from an arbitrary string secret."""
    key_bytes = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))

def encrypt(text: str, key: str) -> str:
    """Encrypt plain text and return a URL-safe base64 token."""
    return _fernet(key).encrypt(text.encode()).decode()

def decrypt(token: str, key: str) -> str:
    """Decrypt a token produced by encrypt()."""
    return _fernet(key).decrypt(token.encode()).decode()
