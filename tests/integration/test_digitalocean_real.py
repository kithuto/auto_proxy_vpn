"""Integration tests for DigitalOcean provider.

These tests require a real DigitalOcean API token set via the
``DIGITALOCEAN_API_TOKEN`` environment variable and SSH keys
already configured in the account.

Run with::

    pytest -m integration -k digitalocean
"""

import os
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.digitalocean, pytest.mark.slow]

TOKEN = os.environ.get("DIGITALOCEAN_API_TOKEN", "")
SSH_KEY_NAME = os.environ.get("DO_SSH_KEY_NAME", "")

skip_reason = "DIGITALOCEAN_API_TOKEN and DO_SSH_KEY_NAME must be set"
skip_if_no_creds = pytest.mark.skipif(not TOKEN or not SSH_KEY_NAME, reason=skip_reason)


@skip_if_no_creds
class TestDigitalOceanIntegration:
    """End-to-end tests that create real droplets in DigitalOcean."""

    @pytest.fixture(scope="class")
    def manager(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        return ProxyManagerDigitalOcean(
            ssh_key=SSH_KEY_NAME,
            token=TOKEN,
            project_name="AutoProxyVPN-Test",
            log=False,
        )

    def test_sizes_and_regions(self, manager):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["medium"]) > 0

    def test_create_and_destroy_proxy(self, manager):
        proxy = manager.get_proxy(
            size="small",
            is_async=False,
            on_exit="destroy",
        )
        try:
            assert proxy.ip
            assert proxy.port > 0
            assert proxy.is_active(wait=True)
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
            # Async proxy may not be active yet
            assert proxy.port > 0
        finally:
            proxy.close()

    def test_get_running_proxy_names(self, manager):
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)

    def test_create_batch(self, manager):
        from auto_proxy_vpn import ProxyPool, DigitalOceanConfig
        config = DigitalOceanConfig(
            ssh_key=SSH_KEY_NAME,
            token=TOKEN,
            project_name="AutoProxyVPN-Test",
        )
        pool = ProxyPool(config, log=False)
        batch = pool.create_batch(2, sizes="small", is_async=True, on_exit="destroy")
        try:
            assert len(batch) == 2
        finally:
            batch.close()
