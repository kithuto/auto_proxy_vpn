"""Integration tests for Google Cloud provider.

These tests require real Google Cloud credentials. Set the
``GOOGLE_APPLICATION_CREDENTIALS`` environment variable to the path
of a service account JSON file.

Run with::

    pytest -m integration -k google
"""

import os
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.google, pytest.mark.slow]

CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT = os.environ.get("GOOGLE_PROJECT", "")
SSH_KEY = os.environ.get("GOOGLE_SSH_KEY", "")

skip_reason = "GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_PROJECT, and GOOGLE_SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(
    not CREDENTIALS or not PROJECT or not SSH_KEY,
    reason=skip_reason,
)


@skip_if_no_creds
class TestGoogleIntegration:
    """End-to-end tests that create real GCE instances."""

    @pytest.fixture(scope="class")
    def manager(self):
        from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
        return ProxyManagerGoogle(
            ssh_key=SSH_KEY,
            project=PROJECT,
            credentials=CREDENTIALS,
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
            assert proxy.port > 0
        finally:
            proxy.close()

    def test_get_running_proxy_names(self, manager):
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)

    def test_create_batch_via_pool(self, manager):
        from auto_proxy_vpn import ProxyPool, GoogleConfig
        config = GoogleConfig(
            project=PROJECT,
            credentials=CREDENTIALS,
            ssh_key=SSH_KEY,
        )
        pool = ProxyPool(config, log=False)
        batch = pool.create_batch(2, sizes="small", is_async=True, on_exit="destroy")
        try:
            assert len(batch) == 2
        finally:
            batch.close()
