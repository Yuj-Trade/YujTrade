import base64
import binascii
from dataclasses import dataclass

from decouple import config as decouple_config

from config.logger import logger
from config.settings import SecretsManager
from trading.exchanges.registry import ExchangeSpec


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str
    passphrase: str = ""

    def as_list(self) -> list[str]:
        return [self.api_key, self.api_secret, self.passphrase]


def _decode(value: str, spec: ExchangeSpec, name: str) -> str | None:
    if spec.secret_encoding != "base64":
        return value
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        logger.error(f"Exchange secret {name} is not valid base64 for {spec.exchange_id}.")
        return None


def find_plaintext_exchange_secrets(spec: ExchangeSpec, sandbox: bool) -> list[str]:
    found = []
    for name in spec.secret_names(sandbox):
        if decouple_config(name, default="") and not decouple_config(
            f"ENCRYPTED_{name}", default=""
        ):
            found.append(name)
    return found


def load_exchange_credentials(spec: ExchangeSpec, sandbox: bool) -> ExchangeCredentials | None:
    names = spec.secret_names(sandbox)
    api_key_name, api_secret_name = names[0], names[1]
    raw_key = SecretsManager.get_exchange_secret(api_key_name)
    raw_secret = SecretsManager.get_exchange_secret(api_secret_name)
    if not raw_key or not raw_secret:
        return None
    raw_passphrase = ""
    if spec.needs_passphrase:
        raw_passphrase = SecretsManager.get_exchange_secret(names[2]) or ""
        if not raw_passphrase:
            return None
    api_key = _decode(raw_key, spec, api_key_name)
    api_secret = _decode(raw_secret, spec, api_secret_name)
    if api_key is None or api_secret is None:
        return None
    passphrase = ""
    if raw_passphrase:
        decoded = _decode(raw_passphrase, spec, names[2])
        if decoded is None:
            return None
        passphrase = decoded
    return ExchangeCredentials(api_key=api_key, api_secret=api_secret, passphrase=passphrase)


def credentials_usable(spec: ExchangeSpec, sandbox: bool) -> tuple[bool, list[str]]:
    plaintext = find_plaintext_exchange_secrets(spec, sandbox)
    credentials = load_exchange_credentials(spec, sandbox)
    secrets = credentials.as_list() if credentials is not None else []
    if plaintext:
        logger.warning(
            f"Plaintext exchange secrets detected for {spec.exchange_id} ({', '.join(plaintext)}). "
            "Run scripts/encrypt_keys.py; credentials stay disabled."
        )
        return False, secrets
    return credentials is not None, secrets
