"""Tests for configuration dataclasses and their validation logic."""

from os import environ
from unittest.mock import patch

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.configs import (
    AwsConfig,
    AzureConfig,
    DigitalOceanConfig,
    GoogleConfig,
    ManagerRuntimeConfig,
)


# ---------------------------------------------------------------------------
# ManagerRuntimeConfig
# ---------------------------------------------------------------------------


class TestManagerRuntimeConfig:
    def test_defaults(self):
        cfg = ManagerRuntimeConfig()
        assert cfg.log is True
        assert cfg.log_file is None
        assert cfg.logger is None
        assert "%(asctime)" in cfg.log_format

    def test_custom_values(self):
        cfg = ManagerRuntimeConfig(log=False, log_file="/tmp/test.log")
        assert cfg.log is False
        assert cfg.log_file == "/tmp/test.log"


# ---------------------------------------------------------------------------
# DigitalOceanConfig
# ---------------------------------------------------------------------------


class TestDigitalOceanConfig:
    def test_provider_is_digitalocean(self, digitalocean_config):
        assert digitalocean_config.provider == CloudProvider.DIGITALOCEAN

    def test_unique_key_uses_token(self, digitalocean_config):
        key = digitalocean_config.unique_key()
        assert key == (CloudProvider.DIGITALOCEAN, "fake-do-token-1234")

    def test_different_tokens_produce_different_keys(self):
        c1 = DigitalOceanConfig(token="tok-a", ssh_key="a")
        c2 = DigitalOceanConfig(token="tok-b", ssh_key="b")
        assert c1.unique_key() != c2.unique_key()

    def test_same_tokens_produce_equal_keys(self):
        c1 = DigitalOceanConfig(token="same", ssh_key="same")
        c2 = DigitalOceanConfig(token="same", ssh_key="same")
        assert c1.unique_key() == c2.unique_key()

    def test_default_values(self):
        cfg = DigitalOceanConfig(ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...")
        assert cfg.project_name == "AutoProxyVPN"
        assert cfg.project_description == "On demand proxies"
        assert cfg.token == ""


# ---------------------------------------------------------------------------
# GoogleConfig
# ---------------------------------------------------------------------------


class TestGoogleConfig:
    def test_provider_is_google(self, google_config):
        assert google_config.provider == CloudProvider.GOOGLE

    def test_unique_key_uses_credentials(self, google_config):
        key = google_config.unique_key()
        assert key == (
            CloudProvider.GOOGLE,
            "test-gcp-project:/tmp/fake_credentials.json",
        )

    def test_unique_key_falls_back_to_env_when_no_credentials(self):
        with patch.dict(environ, {"GOOGLE_APPLICATION_CREDENTIALS": "/env/path.json"}):
            cfg = GoogleConfig(
                project="proj", ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC..."
            )
            assert cfg.unique_key() == (CloudProvider.GOOGLE, "proj:/env/path.json")

    def test_unique_key_empty_when_no_credentials_and_no_env(self):
        with patch.dict(environ, {}, clear=True):
            cfg = GoogleConfig(
                project="proj", ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC..."
            )
            assert cfg.unique_key() == (CloudProvider.GOOGLE, "proj:")


# ---------------------------------------------------------------------------
# AzureConfig
# ---------------------------------------------------------------------------


class TestAzureConfig:
    def test_provider_is_azure(self, azure_config):
        assert azure_config.provider == CloudProvider.AZURE

    def test_unique_key_with_string_credentials(self, azure_config):
        key = azure_config.unique_key()
        assert key == (CloudProvider.AZURE, "fake-subscription-id")

    def test_unique_key_with_dict_credentials(self):
        cfg = AzureConfig(
            credentials={"AZURE_SUBSCRIPTION_ID": "sub-123"},
            ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...",
        )
        assert cfg.unique_key() == (CloudProvider.AZURE, "sub-123")

    def test_unique_key_falls_back_to_env(self):
        with patch.dict(environ, {"AZURE_SUBSCRIPTION_ID": "env-sub"}):
            cfg = AzureConfig(
                credentials={}, ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC..."
            )
            assert cfg.unique_key() == (CloudProvider.AZURE, "env-sub")

    def test_unique_key_empty_when_nothing(self):
        with patch.dict(environ, {}, clear=True):
            cfg = AzureConfig(
                credentials="", ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC..."
            )
            assert cfg.unique_key() == (CloudProvider.AZURE, "")


# ---------------------------------------------------------------------------
# AwsConfig
# ---------------------------------------------------------------------------


class TestAwsConfig:
    def test_provider_is_aws(self, aws_config):
        assert aws_config.provider == CloudProvider.AWS

    def test_unique_key_with_dict_credentials(self, aws_config):
        key = aws_config.unique_key()
        assert key == (
            CloudProvider.AWS,
            "fake-aws-access-key-id:fake-aws-secret-access-key",
        )

    def test_unique_key_falls_back_to_env(self):
        with patch.dict(
            environ,
            {
                "AWS_ACCESS_KEY_ID": "env-ak",
                "AWS_SECRET_ACCESS_KEY": "env-sk",
            },
            clear=True,
        ):
            cfg = AwsConfig(
                ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...", credentials=None
            )
            assert cfg.unique_key() == (CloudProvider.AWS, "env-ak:env-sk")

    def test_unique_key_empty_when_no_credentials(self):
        with patch.dict(environ, {}, clear=True):
            cfg = AwsConfig(
                ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC...", credentials=None
            )
            assert cfg.unique_key() == (CloudProvider.AWS, ":")
