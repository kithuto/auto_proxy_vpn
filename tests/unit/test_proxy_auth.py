import hmac

import pytest

from auto_proxy_vpn.utils.exceptions import (
    ProxyAuthenticationError,
    ProxyAuthRequiredError,
    UnsupportedLegacyProxyAuthError,
)
from auto_proxy_vpn.utils.proxy_auth import (
    format_proxy_auth_metadata_comment,
    hash_proxy_password,
    parse_proxy_auth_metadata,
    resolve_reloaded_proxy_auth,
    verify_proxy_password,
)


def _test_hash(password: str = "secret") -> str:
    return hash_proxy_password(password, salt=b"1" * 32, iterations=1)


def test_hash_proxy_password_uses_stable_format_and_verifies():
    password_hash = _test_hash()

    assert password_hash.startswith("apv1$pbkdf2_sha256$1$")
    assert verify_proxy_password("secret", password_hash) is True
    assert verify_proxy_password("wrong", password_hash) is False


@pytest.mark.parametrize(
    "password_hash",
    [
        "",
        "not-a-hash",
        "apv1$pbkdf2_sha256$1$bad-salt$bad-digest",
        "apv1$unknown$1$c2FsdA$ZGlnZXN0",
    ],
)
def test_verify_proxy_password_rejects_invalid_hashes(password_hash):
    assert verify_proxy_password("secret", password_hash) is False


def test_verify_proxy_password_uses_constant_time_compare(monkeypatch):
    calls = []
    original_compare_digest = hmac.compare_digest

    def fake_compare_digest(left, right):
        calls.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(
        "auto_proxy_vpn.utils.proxy_auth.hmac.compare_digest",
        fake_compare_digest,
    )

    assert verify_proxy_password("secret", _test_hash()) is True
    assert calls


def test_resolve_reloaded_proxy_auth_returns_supplied_credentials():
    proxy_config = (
        "http_port 3128\n"
        f"{format_proxy_auth_metadata_comment('alice', _test_hash())}\n"
        "auth_param basic program /usr/local/bin/auto_proxy_vpn_basic_auth.py\n"
    )

    assert resolve_reloaded_proxy_auth(
        proxy_config,
        {"user": "alice", "password": "secret"},
    ) == {"user": "alice", "password": "secret"}


def test_resolve_reloaded_proxy_auth_requires_auth():
    proxy_config = (
        f"http_port 3128\n{format_proxy_auth_metadata_comment('alice', _test_hash())}\n"
    )

    with pytest.raises(ProxyAuthRequiredError):
        resolve_reloaded_proxy_auth(proxy_config, None)


@pytest.mark.parametrize(
    "auth",
    [
        {"user": "alice", "password": "wrong"},
        {"user": "bob", "password": "secret"},
    ],
)
def test_resolve_reloaded_proxy_auth_rejects_mismatches(auth):
    proxy_config = (
        f"http_port 3128\n{format_proxy_auth_metadata_comment('alice', _test_hash())}\n"
    )

    with pytest.raises(ProxyAuthenticationError):
        resolve_reloaded_proxy_auth(proxy_config, auth)


def test_parse_proxy_auth_metadata_rejects_auth_without_secure_metadata():
    proxy_config = "http_port 3128\nauth_param basic realm proxy\n"

    with pytest.raises(UnsupportedLegacyProxyAuthError):
        parse_proxy_auth_metadata(proxy_config)


def test_parse_proxy_auth_metadata_returns_none_without_auth():
    assert parse_proxy_auth_metadata("http_port 3128\nhttp_access allow all\n") is None
