from typing import Any

from config.logger import logger
from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.errors import sanitize
from trading.exchanges.registry import ExchangeSpec

_NO_ATTESTATION_REASON = "no_endpoint_attestation_required"
_VERBS = frozenset({"GET", "POST", "PUT", "DELETE"})


def _path_candidates(path: str) -> list[str]:
    candidates = [path]
    trimmed = path
    while "/" in trimmed:
        trimmed = trimmed.split("/", 1)[1]
        candidates.append(trimmed)
    return candidates


def _matches(path: str, key: str) -> bool:
    if path == key:
        return True
    for candidate in _path_candidates(path):
        if key.endswith(candidate):
            return True
    return False


def _endpoint_key(entries: dict, path: str) -> str | None:
    for key in entries:
        if _matches(path, str(key)):
            return str(key)
    return None


def _resolve(client: Any, path: str) -> tuple[list[str], str, str] | None:
    described = client.describe() if hasattr(client, "describe") else {}
    api = described.get("api") if isinstance(described, dict) else None
    if not isinstance(api, dict):
        return None
    for section_name in api:
        section = api[section_name]
        if not isinstance(section, dict):
            continue
        section_token = str(section_name).upper()
        if section_token in _VERBS:
            key = _endpoint_key(section, path)
            if key is not None:
                return [str(section_name)], section_token, key
            continue
        for group_name in section:
            group = section[group_name]
            if not isinstance(group, dict):
                continue
            group_token = str(group_name).upper()
            if group_token in _VERBS:
                key = _endpoint_key(group, path)
                if key is not None:
                    return [str(section_name), str(group_name)], group_token, key
                continue
            for verb in group:
                verb_token = str(verb).upper()
                if verb_token not in _VERBS:
                    continue
                endpoints = group[verb]
                if not isinstance(endpoints, dict):
                    continue
                key = _endpoint_key(endpoints, path)
                if key is not None:
                    return (
                        [
                            str(section_name),
                            str(group_name),
                            str(verb),
                        ],
                        verb_token,
                        key,
                    )
    return None


def _find_api_section(client: Any, path: str) -> tuple[list[str], str] | None:
    resolved = _resolve(client, path)
    if resolved is None:
        return None
    section, verb, _ = resolved
    return section, verb


def _relative_path(client: Any, path: str) -> str:
    resolved = _resolve(client, path)
    if resolved is None:
        return path
    return resolved[2]


def _binance_withdrawal_enabled(payload: Any) -> bool | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("enableWithdrawals")
    if isinstance(value, bool):
        return value
    return None


async def verify_key_permissions(gateway: CcxtGateway, spec: ExchangeSpec) -> tuple[bool, str]:
    if spec.permission_endpoint is None:
        return True, _NO_ATTESTATION_REASON
    located = _find_api_section(gateway.client, spec.permission_endpoint)
    if located is None:
        return False, "permission_endpoint_not_found"
    section, verb = located
    request_path = _relative_path(gateway.client, spec.permission_endpoint)
    try:
        payload = await gateway.client.request(request_path, section, verb, {})
    except Exception as exc:
        logger.error(
            f"Permission check failed for {spec.exchange_id}: "
            f"{sanitize(str(exc), gateway._secrets)}"
        )
        return False, "permission_check_failed"
    if spec.exchange_id == "binance":
        withdrawal_enabled = _binance_withdrawal_enabled(payload)
        if withdrawal_enabled is None or withdrawal_enabled:
            return False, "withdraw_enabled_or_unknown"
        return True, "ok"
    if spec.exchange_id == "lbank":
        return False, "lbank_rule_not_defined"
    return False, "permission_rule_not_defined"
