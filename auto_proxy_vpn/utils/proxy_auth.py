from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from secrets import token_bytes
from typing import Literal, Mapping

from auto_proxy_vpn.utils.exceptions import (
    ProxyAuthenticationError,
    ProxyAuthRequiredError,
    UnsupportedLegacyProxyAuthError,
)

AuthDict = dict[Literal["user", "password"], str]

AUTH_METADATA_PREFIX = "# auto_proxy_vpn_auth "
PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
PASSWORD_HASH_VERSION = "apv1"
SALT_BYTES = 32
DIGEST_BYTES = 32

_AUTH_METADATA_RE = re.compile(r"^# auto_proxy_vpn_auth (?P<payload>\{.*\})$", re.M)


@dataclass(frozen=True)
class ProxyAuthMetadata:
    user: str
    password_hash: str


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_proxy_password(
    password: str,
    *,
    salt: bytes | None = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if salt is None:
        salt = token_bytes(SALT_BYTES)
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=DIGEST_BYTES,
    )
    return (
        f"{PASSWORD_HASH_VERSION}${PBKDF2_ALGORITHM}${iterations}$"
        f"{_b64_encode(salt)}${_b64_encode(digest)}"
    )


def verify_proxy_password(password: str, password_hash: str) -> bool:
    try:
        version, algorithm, iterations, salt, digest = password_hash.split("$", 4)
        if version != PASSWORD_HASH_VERSION or algorithm != PBKDF2_ALGORITHM:
            return False
        iteration_count = int(iterations)
        salt_bytes = _b64_decode(salt)
        expected_digest = _b64_decode(digest)
    except (TypeError, ValueError, binascii.Error):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iteration_count,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def normalize_proxy_auth(auth: Mapping[str, str] | None) -> AuthDict:
    if not auth:
        return {}
    if not isinstance(auth, Mapping):
        raise TypeError("Bad auth format, auth must be a dict")
    if "user" not in auth or "password" not in auth:
        raise KeyError("Auth dict must have two keys name and password")
    return {"user": auth["user"], "password": auth["password"]}


def format_proxy_auth_metadata_comment(user: str, password_hash: str) -> str:
    payload = {
        "version": 1,
        "user": user,
        "password_hash": password_hash,
    }
    return AUTH_METADATA_PREFIX + json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    )


def get_proxy_auth_metadata_comment(user: str, password: str) -> str:
    return format_proxy_auth_metadata_comment(user, hash_proxy_password(password))


def parse_proxy_auth_metadata(proxy_config: str) -> ProxyAuthMetadata | None:
    match = _AUTH_METADATA_RE.search(proxy_config)
    if not match and (
        "auth_param basic" in proxy_config or "proxy_auth" in proxy_config
    ):
        raise UnsupportedLegacyProxyAuthError(
            "This proxy uses unsupported authentication metadata. Recreate the proxy."
        )
    if not match:
        return None

    try:
        payload = json.loads(match.group("payload"))
        if payload["version"] != 1:
            raise ValueError
        user = payload["user"]
        password_hash = payload["password_hash"]
        if not isinstance(user, str) or not isinstance(password_hash, str):
            raise ValueError
        password_hash.split("$", 4)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProxyAuthenticationError(
            "Proxy authentication metadata is invalid."
        ) from exc

    return ProxyAuthMetadata(user=user, password_hash=password_hash)


def resolve_reloaded_proxy_auth(
    proxy_config: str,
    auth: Mapping[str, str] | None,
) -> AuthDict:
    metadata = parse_proxy_auth_metadata(proxy_config)
    if metadata is None:
        return {}

    if auth is None:
        raise ProxyAuthRequiredError(
            "Proxy authentication is required to reload this proxy."
        )

    credentials = normalize_proxy_auth(auth)
    if credentials["user"] != metadata.user or not verify_proxy_password(
        credentials["password"], metadata.password_hash
    ):
        raise ProxyAuthenticationError("Proxy authentication failed.")

    return credentials
