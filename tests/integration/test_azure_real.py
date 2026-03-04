"""Integration tests for Azure provider.

These tests require real Azure credentials. Set the following
environment variables:

- ``AZURE_SUBSCRIPTION_ID``
- ``AZURE_TENANT_ID``
- ``AZURE_CLIENT_ID``
- ``AZURE_CLIENT_SECRET``
- ``AZURE_SSH_KEY`` — public SSH key string

Run with::

    pytest -m integration -k azure
"""

import os
from pathlib import Path
import pytest

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.azure]

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
SSH_KEY = os.environ.get("AZURE_SSH_KEY", "")

skip_reason = "AZURE_SUBSCRIPTION_ID and AZURE_SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(
    not SUBSCRIPTION_ID or not SSH_KEY,
    reason=skip_reason,
)

@skip_if_no_creds
class TestAzureIntegration:
    """End-to-end tests that create real Azure VMs."""

    @pytest.fixture(scope="class")
    def manager(self):
        from auto_proxy_vpn.providers.azure.azure_proxy import ProxyManagerAzure
        return ProxyManagerAzure(
            ssh_key=SSH_KEY,
            log=False,
        )

    def test_sizes_and_regions(self, manager):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["small"]) > 0

    def test_create_and_destroy_proxy(self, manager):
        proxy = manager.get_proxy(
            size="small",
            is_async=False,
            on_exit="destroy",
        )
        try:
            assert proxy.is_active()
            assert proxy.ip
            assert proxy.port > 0
        finally:
            proxy.close()
            assert proxy.stopped

    def test_create_async_proxy(self, manager):
        proxy = manager.get_proxy(
            size="small",
            is_async=True,
            on_exit="destroy",
        )
        proxy.is_active(wait=True)
        try:
            assert proxy.port > 0
        finally:
            proxy.close()

    def test_get_running_proxy_names(self, manager):
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)

    def test_create_batch_via_pool(self, manager):
        from auto_proxy_vpn import ProxyPool, AzureConfig
        config = AzureConfig(
            ssh_key=SSH_KEY,
            credentials=SUBSCRIPTION_ID,
        )
        pool = ProxyPool(config, log=False)
        batch = pool.create_batch(2, sizes="small", is_async=True, on_exit="destroy")
        try:
            assert len(batch) == 2
        finally:
            batch.close()
