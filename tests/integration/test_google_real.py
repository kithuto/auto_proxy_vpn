"""Integration tests for the Google Cloud provider.

These tests create and destroy real GCE instances. Required variables:

- ``GOOGLE_APPLICATION_CREDENTIALS``: path to a service account JSON file
- ``GOOGLE_PROJECT``: target Google Cloud project ID
- ``SSH_KEY``: public SSH key string used for instance access

Variables can be exported in the shell or defined in a ``.env`` file
at the repository root.

Run with::

    pytest -m integration -k google
"""

import os
import pytest
from pathlib import Path

from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.google]

CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT = os.environ.get("GOOGLE_PROJECT", "")
SSH_KEY = os.environ.get("SSH_KEY", "")

skip_reason = "GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_PROJECT, and SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(
    not CREDENTIALS or not PROJECT or not SSH_KEY,
    reason=skip_reason,
)


@skip_if_no_creds
class TestGoogleIntegration:
    """End-to-end tests that create real GCE instances."""

    @pytest.fixture(scope="class")
    def manager(self):
        return ProxyManagerGoogle(
            ssh_key=SSH_KEY,
            project=PROJECT,
            credentials=CREDENTIALS,
            log=False,
        )

    def test_sizes_and_regions(self, manager: ProxyManagerGoogle):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["small"]) > 0

    def test_create_and_destroy_proxy(self, manager: ProxyManagerGoogle):
        proxy = manager.get_proxy(
            size="small",
            is_async=False,
            on_exit="destroy",
        )
        try:
            assert proxy.ip
            assert proxy.port > 0
            assert proxy.is_active()
        finally:
            proxy.close()
            assert proxy.stopped

    def test_create_batch_via_pool(self, manager: ProxyManagerGoogle):
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

    def test_all_proxies_cleaned_up(self, manager: ProxyManagerGoogle):
        # This test assumes that the previous tests have run and created proxies.
        # It checks that all proxies are properly cleaned up after tests.
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)
        assert len(names) == 0, f"Expected no running proxies, but found: {names}"
