import base64
import hashlib
import hmac
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config.logger import logger


def generate_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key


def get_encryption_key(password: str, salt_path="secret.salt") -> bytes:
    try:
        if os.path.exists(salt_path):
            with open(salt_path, "rb") as salt_file:
                salt = salt_file.read()
        else:
            salt = os.urandom(16)
            with open(salt_path, "wb") as salt_file:
                salt_file.write(salt)
            logger.info(f"New salt created at {salt_path}")
        return generate_key_from_password(password, salt)
    except Exception as e:
        logger.error(f"Error getting encryption key: {e}")
        raise


class KeyEncryptor:
    def __init__(self, password: str):
        try:
            self.key = get_encryption_key(password)
            self.fernet = Fernet(self.key)
        except Exception as e:
            logger.error(f"Failed to initialize KeyEncryptor: {e}")
            raise

    def encrypt(self, data: str) -> str:
        if not data:
            return ""
        try:
            return self.fernet.encrypt(data.encode()).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return ""

    def decrypt(self, encrypted_data: str) -> str:
        if not encrypted_data:
            return ""
        try:
            return self.fernet.decrypt(encrypted_data.encode()).decode()
        except Exception:
            logger.error(f"Decryption failed for data. It might be invalid or corrupted.")
            return ""


def hash_data(data: str, salt: str = None) -> str:
    salt_val = salt or os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", data.encode(), salt_val.encode(), 480000)
    return f"{salt_val}${hashed.hex()}"


def verify_hashed_data(stored_hash: str, provided_data: str) -> bool:
    try:
        salt, h = stored_hash.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", provided_data.encode(), salt.encode(), 480000
        ).hex()
        return hmac.compare_digest(h, candidate)
    except (ValueError, TypeError):
        return False


def get_password_from_key_manager() -> Optional[str]:
    secret_path = Path("/run/secrets/SECRET_ENCRYPTION_PASSWORD")
    try:
        password = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        password = ""
    except OSError as exc:
        logger.warning(f"Unable to read encryption password secret: {exc}")
        password = ""
    if password:
        logger.info("Loaded encryption password from mounted secret.")
        return password

    password = os.environ.get("SECRET_ENCRYPTION_PASSWORD")
    if password:
        logger.info("Loaded encryption password from protected environment variable.")
        return password
    return None
