from enum import Enum

class CloudProvider(str, Enum):
    """Enum for supported cloud providers. Only providers defined here will be registered to use in ProxyPool.
    The value should match the name of the provider package in auto_proxy_vpn.providers"""
    GOOGLE = "google"
    AZURE = "azure"
    DIGITALOCEAN = "digitalocean"
    # AWS = "aws"
    # ALIBABA = "alibaba"
    # ORACLE = "oracle"

from auto_proxy_vpn.configs import *
from auto_proxy_vpn.manager_register import ProxyManagers, import_provider_modules
import_provider_modules()
from auto_proxy_vpn.proxy_pool import ProxyPool

__all__ = [
    'CloudProvider',
    'ProxyManagers',
    'ManagerRuntimeConfig',
    'GoogleConfig',
    'AzureConfig',
    'DigitalOceanConfig',
    'ProxyPool'
    ]