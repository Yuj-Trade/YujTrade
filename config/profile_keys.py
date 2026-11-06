import json
import os
import tempfile
from pathlib import Path
from typing import Any

from config.logger import logger
from config.settings import SecretsManager

DEFAULT_STORE_PATH = "runs/profile_keys.enc.json"

EXCHANGE_ENVIRONMENTS: tuple[str, ...] = ("sandbox", "live")

EXCHANGE_FIELDS: tuple[str, ...] = ("api_key", "api_secret", "api_passphrase")


class ProfileKeyStoreError(RuntimeError):
    pass


def _empty_document() -> dict[str, Any]:
    return {"exchanges": {}, "providers": {}}


def _normalize(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return _empty_document()
    exchanges = document.get("exchanges")
    providers = document.get("providers")
    return {
        "exchanges": exchanges if isinstance(exchanges, dict) else {},
        "providers": providers if isinstance(providers, dict) else {},
    }


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError, TypeError, ValueError):
        logger.debug("Profile key store permissions left at the platform default.")


class ProfileKeyStore:
    def __init__(self, path: str | Path = DEFAULT_STORE_PATH):
        self.path = Path(path)

    def available(self) -> bool:
        return SecretsManager.active_encryptor() is not None

    def _document(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _empty_document()
        except OSError as exc:
            raise ProfileKeyStoreError(f"Profile key store unreadable: {exc}") from exc
        try:
            return _normalize(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ProfileKeyStoreError(f"Profile key store is not valid JSON: {exc}") from exc

    def _commit(self, document: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=self.path.name,
                suffix=".tmp",
                delete=False,
            )
            temporary = Path(handle.name)
            with handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ProfileKeyStoreError(f"Profile key store unwritable: {exc}") from exc
        _restrict_permissions(self.path)

    def _encrypt(self, value: str) -> str:
        encryptor = SecretsManager.active_encryptor()
        if encryptor is None:
            raise ProfileKeyStoreError(
                "No encryption password is available; set SECRET_ENCRYPTION_PASSWORD."
            )
        token = encryptor.encrypt(value)
        if not token:
            raise ProfileKeyStoreError("Encryption failed; the key was not stored.")
        return token

    def _decrypt(self, token: Any) -> str | None:
        if not isinstance(token, str) or not token:
            return None
        encryptor = SecretsManager.active_encryptor()
        if encryptor is None:
            return None
        return encryptor.decrypt(token) or None

    def _bucket(
        self, document: dict[str, Any], exchange_id: str, environment: str
    ) -> dict[str, Any]:
        exchanges = document["exchanges"]
        venue = exchanges.setdefault(exchange_id, {})
        bucket = venue.setdefault(environment, {})
        if not isinstance(bucket, dict):
            venue[environment] = {}
            bucket = venue[environment]
        return bucket

    def set_exchange_value(self, exchange_id: str, environment: str, field: str, plaintext: str):
        token = self._encrypt(plaintext)
        document = self._document()
        self._bucket(document, exchange_id, environment)[field] = token
        self._commit(document)
        logger.info(f"Profile exchange key stored for {exchange_id} ({environment}, {field}).")

    def set_provider_value(self, name: str, plaintext: str):
        token = self._encrypt(plaintext)
        document = self._document()
        document["providers"][name] = token
        self._commit(document)
        logger.info(f"Profile provider key stored for {name}.")

    def delete_exchange_value(self, exchange_id: str, environment: str, field: str) -> None:
        document = self._document()
        bucket = self._bucket(document, exchange_id, environment)
        if field not in bucket:
            return
        del bucket[field]
        self._commit(document)

    def delete_provider_value(self, name: str) -> None:
        document = self._document()
        if name not in document["providers"]:
            return
        del document["providers"][name]
        self._commit(document)

    def exchange_value(self, exchange_id: str, environment: str, field: str) -> str | None:
        bucket = self._document()["exchanges"].get(exchange_id, {})
        stored = bucket.get(environment, {}) if isinstance(bucket, dict) else {}
        return self._decrypt(stored.get(field) if isinstance(stored, dict) else None)

    def provider_value(self, name: str) -> str | None:
        return self._decrypt(self._document()["providers"].get(name))

    def has_exchange_value(self, exchange_id: str, environment: str, field: str) -> bool:
        bucket = self._document()["exchanges"].get(exchange_id, {})
        stored = bucket.get(environment, {}) if isinstance(bucket, dict) else {}
        if not isinstance(stored, dict):
            return False
        token = stored.get(field)
        return isinstance(token, str) and bool(token)

    def has_provider_value(self, name: str) -> bool:
        token = self._document()["providers"].get(name)
        return isinstance(token, str) and bool(token)


_STORE: ProfileKeyStore | None = None


def get_store() -> ProfileKeyStore:
    global _STORE
    if _STORE is None:
        _STORE = ProfileKeyStore()
    return _STORE


def set_store(store: ProfileKeyStore | None) -> None:
    global _STORE
    _STORE = store


def reset_store() -> None:
    global _STORE
    _STORE = None


def exchange_secret_from_profile(name: str) -> str | None:
    from trading.exchanges.registry import EXCHANGE_REGISTRY

    for spec in EXCHANGE_REGISTRY:
        for sandbox in (True, False):
            environment = "sandbox" if sandbox else "live"
            names = spec.secret_names(sandbox)
            for index, field in enumerate(("api_key", "api_secret", "api_passphrase")):
                if index < len(names) and names[index] == name:
                    return get_store().exchange_value(spec.exchange_id, environment, field)
    return None


def provider_key_from_profile(name: str) -> str | None:
    return get_store().provider_value(name)
