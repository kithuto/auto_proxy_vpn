from abc import ABC, abstractmethod
from logging import Logger
from typing import ClassVar
from dataclasses import dataclass, field
from os import environ

from auto_proxy_vpn import CloudProvider

@dataclass(slots=True)
class ManagerRuntimeConfig:
    log: bool = True
    log_file: str | None = None
    log_format: str = '%(asctime)-10s %(levelname)-5s %(message)s'
    logger: Logger | None = None

@dataclass(kw_only=True)
class BaseConfig(ABC):
    provider: ClassVar['CloudProvider']
    ssh_key: list[dict[str, str] | str] | dict[str, str] | str = field(default_factory=list)
    
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
    credentials: str | dict[str, str] = ''
    
    def _get_credential(self) -> str:
        if isinstance(self.credentials, str):
            return self.credentials
        return self.credentials.get('AZURE_SUBSCRIPTION_ID', environ.get('AZURE_SUBSCRIPTION_ID', ''))
    
    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, self._get_credential())

@dataclass
class DigitalOceanConfig(BaseConfig):
    provider: ClassVar = CloudProvider.DIGITALOCEAN
    project_name: str = 'AutoProxyVPN'
    project_description: str = 'On demand proxies'
    token: str = ''
    
    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, self.token)

@dataclass
class GoogleConfig(BaseConfig):
    provider: ClassVar = CloudProvider.GOOGLE
    project: str
    credentials: str = ''
    
    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, self.credentials if self.credentials else environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""))