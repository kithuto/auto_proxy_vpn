from abc import ABC, abstractmethod
from hashlib import sha256
from logging import Logger
from typing import ClassVar
from dataclasses import dataclass
from os import environ
from pathlib import Path

from auto_proxy_vpn.cloud_provider import CloudProvider


def _fingerprint(*values: str) -> str:
    digest = sha256("\0".join(values).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass
class ManagerRuntimeConfig:
    log: bool = True
    log_file: str | None = None
    log_format: str = "%(asctime)-10s %(levelname)-5s %(message)s"
    logger: Logger | None = None


@dataclass
class BaseConfig(ABC):
    provider: ClassVar["CloudProvider"]
    ssh_key: list[dict[str, str] | str] | dict[str, str] | str | Path

    @abstractmethod
    def unique_key(self) -> tuple[CloudProvider, str]:
        """
        Returns a hashable value that uniquely identifies this configuration.
        Used to detect duplicates inside ProxyPool.
        """
        ...


@dataclass
class AzureConfig(BaseConfig):
    provider: ClassVar = CloudProvider.AZURE
    credentials: str | dict[str, str] = ""

    def _get_credential(self) -> str:
        if isinstance(self.credentials, str):
            return self.credentials
        return self.credentials.get(
            "AZURE_SUBSCRIPTION_ID", environ.get("AZURE_SUBSCRIPTION_ID", "")
        )

    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, self._get_credential())


@dataclass
class DigitalOceanConfig(BaseConfig):
    provider: ClassVar = CloudProvider.DIGITALOCEAN
    project_name: str = "AutoProxyVPN"
    project_description: str = "On demand proxies"
    token: str = ""

    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, _fingerprint(self.token))


@dataclass
class GoogleConfig(BaseConfig):
    provider: ClassVar = CloudProvider.GOOGLE
    project: str
    credentials: str = ""

    def unique_key(self) -> tuple[CloudProvider, str]:
        credentials_path = (
            self.credentials
            if self.credentials
            else environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        )
        return (
            self.provider,
            f"{self.project}:{_fingerprint(credentials_path)}",
        )


@dataclass
class AwsConfig(BaseConfig):
    provider: ClassVar = CloudProvider.AWS
    credentials: dict[str, str] | None = None

    def unique_key(self) -> tuple[CloudProvider, str]:
        aws_access_key_id = (
            self.credentials.get("AWS_ACCESS_KEY_ID", "")
            if self.credentials
            else environ.get("AWS_ACCESS_KEY_ID", "")
        )
        aws_secret_access_key = (
            self.credentials.get("AWS_SECRET_ACCESS_KEY", "")
            if self.credentials
            else environ.get("AWS_SECRET_ACCESS_KEY", "")
        )
        return (self.provider, _fingerprint(aws_access_key_id, aws_secret_access_key))
