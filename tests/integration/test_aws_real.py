"""Integration tests for AWS provider.

These tests require real AWS credentials. Set the following
environment variables:

- ``AWS_ACCESS_KEY_ID``
- ``AWS_SECRET_ACCESS_KEY``
- ``SSH_KEY`` — public SSH key string

Run with::

    pytest -m integration -k aws
"""

from __future__ import annotations

import os
from pathlib import Path

from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

import pytest
from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.aws]

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
SSH_KEY = os.environ.get("SSH_KEY", "")

skip_reason = "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and SSH_KEY must be set"
skip_if_no_creds = pytest.mark.skipif(
    not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not SSH_KEY,
    reason=skip_reason,
)


@skip_if_no_creds
class TestAwsIntegration:
    """End-to-end tests that create real EC2 instances."""

    @pytest.fixture(scope="class")
    def manager(self):
        return ProxyManagerAws(
            ssh_key=SSH_KEY,
            credentials={
                "AWS_ACCESS_KEY_ID": AWS_ACCESS_KEY_ID,
                "AWS_SECRET_ACCESS_KEY": AWS_SECRET_ACCESS_KEY,
            },
            log=False,
        )

    def test_sizes_and_regions(self, manager: ProxyManagerAws):
        sr = manager.get_sizes_and_regions()
        assert "small" in sr
        assert len(sr["small"]) > 0

    def test_create_and_destroy_proxy(self, manager: ProxyManagerAws):
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

    def test_create_batch_via_pool(self, manager: ProxyManagerAws):
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

    def test_all_proxies_cleaned_up(self, manager: ProxyManagerAws):
        # This test assumes that the previous tests have run and created proxies.
        # It checks that all proxies are properly cleaned up after tests.
        names = manager.get_running_proxy_names()
        assert isinstance(names, list)
        assert len(names) == 0, f"Expected no running proxies, but found: {names}"
