"""Shared fixtures and configuration for the auto_proxy_vpn test suite.

This module provides common mocks, fixtures, and helpers used across unit
and integration tests. Fixtures are organized by scope so that expensive
setups (e.g. provider manager stubs) are reused across a session whenever
possible.

Contributing
------------
* Add new fixtures here when they are shared across multiple test modules.
* Keep module-specific fixtures in the test file itself.
* Use ``@pytest.mark.integration`` for any test that talks to a real cloud API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from auto_proxy_vpn.configs import (
    AzureConfig,
    BaseConfig,
    DigitalOceanConfig,
    GoogleConfig,
    ManagerRuntimeConfig,
)
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager, ProxyBatch


# ---------------------------------------------------------------------------
# Concrete stubs for abstract classes (used by many tests)
# ---------------------------------------------------------------------------

class StubProxy(BaseProxy):
    """Minimal concrete proxy for unit-testing base behaviour."""

    def __init__(
        self,
        ip: str = "1.2.3.4",
        name: str = "stub-proxy",
        port: int = 12345,
        user: str = "",
        password: str = "",
        active: bool = True,
        is_async: bool = False,
        destroy: bool = True,
    ):
        self.ip = ip
        self.name = name
        self.port = port
        self.user = user
        self.password = password
        self.active = active
        self.is_async = is_async
        self.destroy = destroy
        self.log = False
        self.output = False
        self.stopped = False

    def _stop_proxy(self, wait: bool = True):
        self.stopped = True
        self.active = False


class StubProxyManager(BaseProxyManager[StubProxy]):
    """Minimal concrete manager for unit-testing ProxyPool logic."""

    _sizes_regions = {
        "small": ["region-a", "region-b"],
        "medium": ["region-a", "region-b", "region-c"],
        "large": ["region-a"],
    }

    def __init__(self, label: str = "stub"):
        self.label = label
        self._get_proxy_calls: list[dict] = []

    @classmethod
    def from_config(cls, config=None, runtime_config=None):
        return cls()

    def get_proxy(
        self,
        port=0,
        size="medium",
        region="",
        auth={},
        allowed_ips=[],
        is_async=False,
        retry=True,
        proxy_name="",
        on_exit="destroy",
    ) -> StubProxy:
        call = dict(port=port, size=size, region=region, auth=auth, on_exit=on_exit)
        self._get_proxy_calls.append(call)
        return StubProxy(name=f"{self.label}-proxy-{len(self._get_proxy_calls)}")

    def get_proxy_by_name(self, name, is_async=False, on_exit="destroy"):
        return StubProxy(name=name)

    def get_running_proxy_names(self):
        return [f"{self.label}-proxy-{i}" for i in range(1, len(self._get_proxy_calls) + 1)]


# ---------------------------------------------------------------------------
# Fixtures — Configs
# ---------------------------------------------------------------------------

@pytest.fixture
def runtime_config():
    """A ManagerRuntimeConfig with logging disabled."""
    return ManagerRuntimeConfig(log=False)


@pytest.fixture
def runtime_config_with_logger():
    """A ManagerRuntimeConfig with a real logger (no file output)."""
    logger = logging.getLogger("test_logger")
    logger.setLevel(logging.DEBUG)
    return ManagerRuntimeConfig(log=True, logger=logger)


@pytest.fixture
def digitalocean_config():
    return DigitalOceanConfig(
        ssh_key=[{"name": "test-key", "public_key": "ssh-rsa AAAA..."}],
        token="fake-do-token-1234",
        project_name="TestProject",
    )


@pytest.fixture
def google_config():
    return GoogleConfig(
        project="test-gcp-project",
        credentials="/tmp/fake_credentials.json",
        ssh_key="ssh-rsa AAAA...",
    )


@pytest.fixture
def azure_config():
    return AzureConfig(
        ssh_key="ssh-rsa AAAA...",
        credentials="fake-subscription-id",
    )


# ---------------------------------------------------------------------------
# Fixtures — Stubs
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_proxy():
    return StubProxy()


@pytest.fixture
def stub_proxy_with_auth():
    return StubProxy(user="admin", password="s3cret")


@pytest.fixture
def inactive_proxy():
    return StubProxy(active=False, ip="")


@pytest.fixture
def stub_manager():
    return StubProxyManager(label="mgr1")


@pytest.fixture
def stub_managers():
    """Return a list of 3 distinct stub managers."""
    return [StubProxyManager(label=f"mgr{i}") for i in range(1, 4)]


@pytest.fixture
def proxy_batch():
    """A ProxyBatch with 5 active stub proxies."""
    proxies = [StubProxy(name=f"proxy-{i}") for i in range(5)]
    return ProxyBatch(proxies)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_do_regions_response(slugs: list[str] | None = None):
    """Build a fake DigitalOcean /v2/regions JSON body."""
    slugs = slugs or ["nyc1", "sfo3", "ams3", "lon1"]
    return {
        "regions": [
            {
                "slug": s,
                "name": s.upper(),
                "available": True,
                "sizes": ["s-1vcpu-512mb-10gb", "s-1vcpu-1gb", "s-1vcpu-2gb"],
            }
            for s in slugs
        ]
    }


def make_do_droplet(droplet_id: int = 123, name: str = "proxy1", ip: str = "10.0.0.1", status: str = "active"):
    """Return a minimal DigitalOcean droplet dict."""
    return {
        "id": droplet_id,
        "name": name,
        "status": status,
        "region": {"slug": "nyc1"},
        "networks": {
            "v4": [{"type": "public", "ip_address": ip}]
        },
    }
