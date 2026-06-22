"""Real integration tests for ProxyPool.

These tests use whichever provider credentials are available in the
environment and are skipped when no provider is configured.

Supported provider env vars:
- DigitalOcean: DIGITALOCEAN_API_TOKEN
- AWS: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
- Azure: AZURE_SUBSCRIPTION_ID
- Google: GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_PROJECT
- SSH keys: SSH_KEY file with the ssh keys

Run with::

    pytest -m integration -k pool
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from auto_proxy_vpn import (
    BaseConfig,
    AwsConfig,
    AzureConfig,
    DigitalOceanConfig,
    GoogleConfig,
    ProxyPool,
)


load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.integration, pytest.mark.pool]


def _available_provider_configs() -> list[BaseConfig]:
    configs: list[BaseConfig] = []

    # DigitalOcean
    do_token = os.environ.get("DIGITALOCEAN_API_TOKEN", "")
    do_ssh_key_name = os.environ.get("SSH_KEY", "")
    if do_token and do_ssh_key_name:
        configs.append(
            DigitalOceanConfig(
                ssh_key=do_ssh_key_name,
                token=do_token,
                project_name="AutoProxyVPN-Test",
            )
        )

    # AWS
    aws_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    aws_ssh_key = os.environ.get("SSH_KEY", "")
    if aws_key and aws_secret and aws_ssh_key:
        configs.append(
            AwsConfig(
                ssh_key=aws_ssh_key,
                credentials={
                    "AWS_ACCESS_KEY_ID": aws_key,
                    "AWS_SECRET_ACCESS_KEY": aws_secret,
                },
            )
        )

    # Azure
    azure_subscription = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    azure_ssh_key = os.environ.get("SSH_KEY", "")
    if azure_subscription and azure_ssh_key:
        configs.append(
            AzureConfig(
                ssh_key=azure_ssh_key,
                credentials=azure_subscription,
            )
        )

    # Google
    gcp_credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    gcp_project = os.environ.get("GOOGLE_PROJECT", "")
    gcp_ssh_key = os.environ.get("SSH_KEY", "")
    if gcp_credentials and gcp_project and gcp_ssh_key:
        configs.append(
            GoogleConfig(
                project=gcp_project,
                credentials=gcp_credentials,
                ssh_key=gcp_ssh_key,
            )
        )

    return configs


AVAILABLE_CONFIGS = _available_provider_configs()
skip_if_no_provider_creds = pytest.mark.skipif(
    not AVAILABLE_CONFIGS,
    reason=(
        "No provider credentials found. Configure at least one provider "
        "(DigitalOcean, AWS, Azure, or Google)."
    ),
)


@skip_if_no_provider_creds
class TestProxyPoolRealIntegration:
    @pytest.fixture(scope="class")
    def pool(self):
        return ProxyPool(*AVAILABLE_CONFIGS, log=False)

    def test_create_one_real_and_cleanup(self, pool: ProxyPool):
        proxy = pool.create_one(size="small", is_async=True, on_exit="destroy")
        try:
            assert proxy.port > 0
            assert proxy.is_active(wait=True)
            assert proxy.ip
        finally:
            proxy.close()

    def test_create_batch_real_and_cleanup(self, pool: ProxyPool):
        # Keep this small to reduce cloud resource usage during integration runs.
        batch = pool.create_batch(
            len(AVAILABLE_CONFIGS), sizes="small", on_exit="destroy"
        )
        try:
            assert len(batch) <= len(AVAILABLE_CONFIGS)
            for proxy in batch:
                assert proxy.is_active(wait=True)
                assert proxy.ip
                assert proxy.port > 0
        finally:
            batch.close(wait=True)

    def test_all_proxies_cleaned_up(self, pool: ProxyPool):
        # This test assumes that the previous tests have run and created proxies.
        # It checks that all proxies are properly cleaned up after tests.
        running = pool.get_running_proxy_names()
        for provider, accounts in running.items():
            for _, names in accounts.items():
                assert len(names) == 0, (
                    f"Expected no running proxies for {provider}, but found: {names}"
                )
