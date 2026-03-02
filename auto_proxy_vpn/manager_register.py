from abc import ABC
from typing import ClassVar
from pkgutil import iter_modules
from importlib import import_module
from pathlib import Path

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.utils.base_proxy import BaseProxyManager

class ProxyManagers(ABC):
    _registry: ClassVar[dict[CloudProvider, type["BaseProxyManager"]]] = {}

    @classmethod
    def register(cls, provider: CloudProvider):
        def decorator(subclass):
            if provider in cls._registry:
                raise ValueError(f"{provider} already registered")
            cls._registry[provider] = subclass
            return subclass
        return decorator
    
    @classmethod
    def get_manager(cls, provider: CloudProvider) -> type["BaseProxyManager"]:
        if provider not in cls._registry:
            raise ValueError(f"No manager registered for {provider}")
        return cls._registry[provider]

def import_provider_modules():
    package_name = 'auto_proxy_vpn.providers'
    current_dir = Path(__file__).resolve().parent
    allowed_packages = {x.value for x in CloudProvider}
    provider_packages = [x for x in iter_modules([current_dir / "providers"], prefix=f"{package_name}.") if x.name.split(".")[-1] in allowed_packages]
    for package in provider_packages:
        import_module(package.name)