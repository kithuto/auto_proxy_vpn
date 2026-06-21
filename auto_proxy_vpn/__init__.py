from auto_proxy_vpn.cloud_provider import CloudProvider
from auto_proxy_vpn.configs import (
    AwsConfig,
    AzureConfig,
    BaseConfig,
    DigitalOceanConfig,
    GoogleConfig,
    ManagerRuntimeConfig,
)
from auto_proxy_vpn.manager_register import ProxyManagers, import_provider_modules
from auto_proxy_vpn.proxy_pool import ProxyPool
from auto_proxy_vpn.utils._version import get_version

__version__ = get_version()

import_provider_modules()

__all__ = [
    "__version__",
    "CloudProvider",
    "ProxyManagers",
    "BaseConfig",
    "ManagerRuntimeConfig",
    "GoogleConfig",
    "AzureConfig",
    "DigitalOceanConfig",
    "AwsConfig",
    "ProxyPool",
]
