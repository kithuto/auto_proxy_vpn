"""Integration tests for the DigitalOcean provider.

These tests create and destroy real DigitalOcean droplets. Required
variables:

- ``DIGITALOCEAN_API_TOKEN``: DigitalOcean API token
- ``SSH_KEY``: public SSH key string used for droplet access

Variables can be exported in the shell or defined in a ``.env`` file
at the repository root.

Run with::

    pytest -m integration -k digitalocean
"""

import os
import pytest
from pathlib import Path

from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.digitalocean]

TOKEN = os.environ.get("DIGITALOCEAN_API_TOKEN", "")
SSH_KEY = os.environ.get("SSH_KEY", "")

skip_reason = "DIGITALOCEAN_API_TOKEN and SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(not TOKEN or not SSH_KEY, reason=skip_reason)


@skip_if_no_creds
class TestDigitalOceanIntegration:
    """End-to-end tests that create real droplets in DigitalOcean."""

    @pytest.fixture(scope="class")
    def manager(self):
        return ProxyManagerDigitalOcean(
            ssh_key=SSH_KEY,
            token=TOKEN,
            log=False,
        )

    def test_sizes_and_regions(self, manager: ProxyManagerDigitalOcean):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["medium"]) > 0

    def test_create_and_destroy_proxy(self, manager: ProxyManagerDigitalOcean):
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

    def test_create_batch(self, manager: ProxyManagerDigitalOcean):
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

    def test_all_proxies_cleaned_up(self, manager: ProxyManagerDigitalOcean):
        # This test assumes that the previous tests have run and created proxies.
        # It checks that all proxies are properly cleaned up after tests.
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)
        assert len(names) == 0, f"Expected no running proxies, but found: {names}"
