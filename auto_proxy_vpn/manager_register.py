from abc import ABC
from typing import ClassVar
from pkgutil import iter_modules
from importlib import import_module
from pathlib import Path

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.utils.base_proxy import BaseProxyManager

class ProxyManagers(ABC):
    """Central registry for provider-specific proxy manager classes.

    This class stores a mapping between :class:`CloudProvider` values and the
    corresponding manager class that handles proxy creation for that provider.
    Manager implementations register themselves through the
    :meth:`register` decorator.

    Notes
    -----
    - Registration is global for the current Python process.
    - A provider can only be registered once.
    """

    _registry: ClassVar[dict[CloudProvider, type["BaseProxyManager"]]] = {}

    @classmethod
    def register(cls, provider: CloudProvider):
        """Class decorator to register a proxy manager class for a specific cloud provider."""
        def decorator(subclass):
            if provider in cls._registry:
                raise ValueError(f"{provider} already registered")
            cls._registry[provider] = subclass
            return subclass
        return decorator
    
    @classmethod
    def get_manager(cls, provider: CloudProvider) -> type["BaseProxyManager"]:
        """Return the registered manager class for a cloud provider.

        Parameters
        ----------
        provider : CloudProvider
            Provider whose manager class is requested.

        Returns
        -------
        type[BaseProxyManager]
            Registered manager class for ``provider``.

        Raises
        ------
        ValueError
            If no manager class is registered for ``provider``.
        """
        if provider not in cls._registry:
            raise ValueError(f"No manager registered for {provider}")
        return cls._registry[provider]

def import_provider_modules():
    """Import provider packages so manager classes self-register.

    This helper discovers allowed provider modules under
    ``auto_proxy_vpn.providers`` and imports each one. Import side effects are
    expected to execute ``@ProxyManagers.register(...)`` decorators.
    """
    package_name = 'auto_proxy_vpn.providers'
    current_dir = Path(__file__).resolve().parent
    allowed_packages = {x.value for x in CloudProvider}
    provider_packages = [x for x in iter_modules([current_dir / "providers"], prefix=f"{package_name}.") if x.name.split(".")[-1] in allowed_packages]
    for package in provider_packages:
        import_module(package.name)