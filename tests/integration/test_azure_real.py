"""Integration tests for Azure provider.

These tests require real Azure credentials. Set the following
environment variables:

- ``AZURE_SUBSCRIPTION_ID``
- ``AZURE_TENANT_ID``
- ``AZURE_CLIENT_ID``
- ``AZURE_CLIENT_SECRET``
- ``SSH_KEY`` — public SSH key string

Run with::

    pytest -m integration -k azure
"""

import os
from pathlib import Path
import pytest

from auto_proxy_vpn.providers.azure.azure_proxy import ProxyManagerAzure

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.azure]

SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
SSH_KEY = os.environ.get("SSH_KEY", "")

skip_reason = "AZURE_SUBSCRIPTION_ID and SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(
    not SUBSCRIPTION_ID or not SSH_KEY,
    reason=skip_reason,
)

@skip_if_no_creds
class TestAzureIntegration:
    """End-to-end tests that create real Azure VMs."""

    @pytest.fixture(scope="class")
    def manager(self):
        return ProxyManagerAzure(
            ssh_key=SSH_KEY,
            log=False,
        )

    def test_sizes_and_regions(self, manager: ProxyManagerAzure):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["small"]) > 0

    def test_create_and_destroy_proxy(self, manager: ProxyManagerAzure):
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

    def test_create_batch_via_pool(self, manager: ProxyManagerAzure):
        batch = manager.get_proxies(2, sizes="small", on_exit="destroy")
        
        for proxy in batch:
            assert proxy.is_active(wait=True)
            assert proxy.ip
            assert proxy.port > 0
        
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)
        try:
            assert len(batch) == len(names) == 2
        finally:
            batch.close(wait=True)

    def test_all_proxies_cleaned_up(self, manager: ProxyManagerAzure):
        # This test assumes that the previous tests have run and created proxies.
        # It checks that all proxies are properly cleaned up after tests.
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)
        assert len(names) == 0, f"Expected no running proxies, but found: {names}"
